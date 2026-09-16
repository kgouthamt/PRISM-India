"""Deterministic pharmacogenomic + phenotypic rule engine with dosage guidance.

Public API: evaluate_prescription(drug, test_type, test_result, *, indication=None,
reference_range_low=None) -> dict, where the returned dict always has exactly
these keys:
    - risk: RISK_HIGH | RISK_NO_ALERT | RISK_UNKNOWN
    - reason: human-readable clinical rationale
    - recommendation_and_dosage: action + dosage text, or None when risk is UNKNOWN
    - evidence_type: which test/marker the verdict was based on, or None if unrecognized
    - guideline_url: link to the specific guideline this rule was drawn from, or
      None if no rule matched (e.g. an unrecognized drug or test value)
    - evidence_date: the publication date of that specific guideline, or None
    - rule_hash: a short MD5 fingerprint of this rule's key/reason/recommendation,
      or None if no rule matched -- changes whenever the rule's content changes,
      giving each individual evaluation its own lightweight version marker

There is deliberately no single blanket "CPIC" label describing every rule in
this module: not every rule here traces to a CPIC guideline (e.g. the G6PD
phenotype cutoff and the Tacrolimus TDM target ranges are drawn from other
sources), so provenance is tracked per rule via RULE_PROVENANCE and surfaced
on every evaluation through guideline_url/evidence_date/rule_hash above,
rather than asserted once for the whole engine.

RULE_VERSION / GUIDELINE_VERSION / EVIDENCE_SOURCE remain as coarse,
whole-engine fallback provenance for the audit log and FHIR export when a
caller wants a single summary string; GUIDELINE_VERSION / EVIDENCE_SOURCE no
longer claim a single named guideline body, since the per-rule fields above
are the authoritative source for any individual evaluation.

`indication` (Tacrolimus only, e.g. "Kidney Transplant" / "Liver Transplant")
selects the therapeutic trough target range used by the TDM alert -- see
TACROLIMUS_TDM_TARGETS. `reference_range_low` (G6PD phenotype only) is the
ordering lab's own lower limit of normal for its G6PD enzyme-activity assay,
since that assay is not standardized across labs; when omitted, a documented
MVP default is used instead of silently guessing.
"""

import hashlib
import json
import re

RISK_HIGH = "HIGH"
RISK_NO_ALERT = "NO ACTIONABLE ALERT"
RISK_UNKNOWN = "UNKNOWN"

RULE_VERSION = "4.0.0"
GUIDELINE_VERSION = "Multiple guideline sources (see per-rule provenance)"
EVIDENCE_SOURCE = "Per-rule provenance (see guideline_url / evidence_date per evaluation)"

# Granular, per-rule provenance -- looked up by _result()'s provenance_key and
# surfaced on every evaluation, replacing a single blanket engine-wide label.
RULE_PROVENANCE = {
    "clopidogrel_cyp2c19": {
        "guideline_url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
        "evidence_date": "2022-05-01",
    },
    "clopidogrel_pru": {
        "guideline_url": "https://www.fda.gov/drugs/drug-safety-and-availability/"
                          "fda-drug-safety-communication-reduced-effectiveness-plavix-clopidogrel-patients-who-are-poor",
        "evidence_date": "2010-03-12",
    },
    "carbamazepine_hla": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-carbamazepine-and-hla-b/",
        "evidence_date": "2018-08-01",
    },
    "allopurinol_hla": {
        "guideline_url": "https://cpicpgx.org/guidelines/guideline-for-allopurinol-and-hla-b/",
        "evidence_date": "2015-11-01",
    },
    "abacavir_hla": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-abacavir-and-hla-b/",
        "evidence_date": "2014-06-01",
    },
    "g6pd_genotype": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-rasburicase-and-g6pd/",
        "evidence_date": "2022-11-01",
    },
    "g6pd_phenotype": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-rasburicase-and-g6pd/",
        "evidence_date": "2022-11-01",
    },
    "tacrolimus_cyp3a5_pgx": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-tacrolimus-and-cyp3a5/",
        "evidence_date": "2015-03-01",
    },
    "tacrolimus_tdm": {
        "guideline_url": "https://kdigo.org/guidelines/transplant-candidate/",
        "evidence_date": "2009-11-01",
    },
    "warfarin_cyp2c9_vkorc1": {
        "guideline_url": "https://cpicpgx.org/guidelines/cpic-guideline-for-pharmacogenetics-guided-warfarin-dosing/",
        "evidence_date": "2017-06-01",
    },
}

# CYP2C19 diplotype -> clopidogrel metabolizer phenotype, per current CPIC guidance.
CLOPIDOGREL_NORMAL = {"*1/*1"}
CLOPIDOGREL_INTERMEDIATE = {"*1/*2", "*1/*3"}
CLOPIDOGREL_POOR = {"*2/*2", "*2/*3", "*3/*3"}

HLA_DRUG_GENE = {
    "carbamazepine": "HLA-B*15:02",
    "allopurinol": "HLA-B*58:01",
    "abacavir": "HLA-B*57:01",
}

G6PD_DRUGS = {"primaquine", "rasburicase"}

# CYP3A5 diplotype -> tacrolimus starting-dose expresser status, per CPIC.
TACROLIMUS_CYP3A5_EXPRESSER = {"*1/*1", "*1/*3"}
TACROLIMUS_CYP3A5_NON_EXPRESSER = {"*3/*3"}

# Tacrolimus TDM target trough ranges (ng/mL), by transplant indication --
# these differ enough by protocol that a single fixed range is itself an
# oversimplification. Unrecognized/missing indication falls back to the
# kidney-transplant range, the MVP's original default, rather than guessing.
TACROLIMUS_TDM_TARGETS = {
    "kidney transplant": (5.0, 15.0),
    "liver transplant": (5.0, 20.0),
}
TACROLIMUS_TDM_DEFAULT_TARGET = (5.0, 15.0)

# G6PD enzyme-activity assays are not standardized across labs -- this MVP
# default (percent of normal) is used only when the ordering lab's own
# reference range lower limit isn't supplied.
G6PD_DEFAULT_REFERENCE_LOW = 10.0


def _rule_hash(provenance_key, reason, recommendation_and_dosage) -> str:
    """Compact MD5 fingerprint of a rule's content, for lightweight
    per-evaluation versioning -- not a cryptographic integrity guarantee,
    just a value that changes whenever the rule's key, reasoning text, or
    recommendation text changes.
    """
    payload = json.dumps(
        {"key": provenance_key, "reason": reason, "recommendation": recommendation_and_dosage},
        sort_keys=True,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def _result(risk, reason, recommendation_and_dosage, evidence_type, provenance_key=None):
    provenance = RULE_PROVENANCE.get(provenance_key, {})
    return {
        "risk": risk,
        "reason": reason,
        "recommendation_and_dosage": recommendation_and_dosage,
        "evidence_type": evidence_type,
        "guideline_url": provenance.get("guideline_url"),
        "evidence_date": provenance.get("evidence_date"),
        "rule_hash": _rule_hash(provenance_key, reason, recommendation_and_dosage) if provenance_key else None,
    }


def _unknown(evidence_type=None):
    return _result(
        RISK_UNKNOWN,
        "No actionable guidance -> No automated prescribing recommendation",
        None,
        evidence_type,
    )


def _normalize_diplotype(text: str) -> str:
    alleles = [a.strip() for a in (text or "").strip().split("/") if a.strip()]
    return "/".join(sorted(alleles))


def _numeric_estimate(text: str, epsilon: float = 0.01):
    """Best-effort numeric value implied by free text like '> 208', '< 10%', '18 ng/mL'."""
    match = re.search(r"[-+]?\d*\.?\d+", text or "")
    if not match:
        return None
    value = float(match.group())
    if "<" in text:
        return value - epsilon
    if ">" in text:
        return value + epsilon
    return value


def _evaluate_clopidogrel(test_type: str, test_result: str) -> dict:
    if test_type == "Genotype":
        diplotype = _normalize_diplotype(test_result)
        if diplotype in CLOPIDOGREL_NORMAL:
            return _result(
                RISK_NO_ALERT,
                "Normal CYP2C19 metabolizer; expected clopidogrel activation",
                "Standard dose: 75 mg/day",
                "CYP2C19 Genotype",
                provenance_key="clopidogrel_cyp2c19",
            )
        if diplotype in CLOPIDOGREL_INTERMEDIATE:
            return _result(
                RISK_HIGH,
                "Intermediate CYP2C19 metabolizer; reduced clopidogrel activation (CPIC)",
                "Consider alternative P2Y12 inhibitor (prasugrel or ticagrelor) if no contraindication",
                "CYP2C19 Genotype",
                provenance_key="clopidogrel_cyp2c19",
            )
        if diplotype in CLOPIDOGREL_POOR:
            return _result(
                RISK_HIGH,
                "Poor CYP2C19 metabolizer; markedly reduced clopidogrel activation (CPIC)",
                "Avoid clopidogrel; use alternative P2Y12 inhibitor (prasugrel or ticagrelor) "
                "if no contraindication",
                "CYP2C19 Genotype",
                provenance_key="clopidogrel_cyp2c19",
            )
        return _unknown("CYP2C19 Genotype")

    if test_type == "Phenotype":
        value = _numeric_estimate(test_result)
        if value is None:
            return _unknown("Platelet Reactivity (PRU) Phenotype")
        if value > 208:
            return _result(
                RISK_HIGH,
                f"High on-treatment platelet reactivity (PRU {test_result.strip()}); "
                "inadequate clopidogrel response",
                "Recommend alternative P2Y12 inhibitor (prasugrel or ticagrelor)",
                "Platelet Reactivity (PRU) Phenotype",
                provenance_key="clopidogrel_pru",
            )
        return _result(
            RISK_NO_ALERT,
            f"Platelet reactivity within therapeutic range (PRU {test_result.strip()})",
            "Standard dose: 75 mg/day",
            "Platelet Reactivity (PRU) Phenotype",
            provenance_key="clopidogrel_pru",
        )

    return _unknown()


def _evaluate_hla(drug_key: str, test_type: str, test_result: str) -> dict:
    gene = HLA_DRUG_GENE[drug_key]
    evidence_type = f"{gene} Genotype"
    provenance_key = f"{drug_key}_hla"
    if test_type != "Genotype":
        return _unknown(evidence_type)

    status = (test_result or "").strip().lower()
    if status == "positive":
        reason_map = {
            "carbamazepine": "Risk of Stevens-Johnson Syndrome / toxic epidermal necrolysis",
            "allopurinol": "Risk of severe cutaneous adverse reactions (SJS/TEN, DRESS)",
            "abacavir": "Risk of abacavir hypersensitivity reaction",
        }
        dosage_map = {
            "carbamazepine": "Avoid carbamazepine entirely",
            "allopurinol": "Avoid allopurinol; consider alternative therapy based on clinical context.",
            "abacavir": "Avoid abacavir entirely",
        }
        return _result(RISK_HIGH, reason_map[drug_key], dosage_map[drug_key], evidence_type, provenance_key)

    if status == "negative":
        return _result(
            RISK_NO_ALERT,
            f"{gene} allele not detected; no contraindication per current guidance",
            "Standard dosing per product label",
            evidence_type,
            provenance_key,
        )

    return _unknown(evidence_type)


def _evaluate_g6pd(test_type: str, test_result: str, reference_range_low: float = None) -> dict:
    dosage = "Avoid drug entirely to prevent acute hemolytic anemia"

    if test_type == "Genotype":
        status = (test_result or "").strip().lower()
        if "deficient" in status:
            return _result(RISK_HIGH, "G6PD-deficient genotype detected", dosage, "G6PD Genotype", "g6pd_genotype")
        if "normal" in status:
            return _result(
                RISK_NO_ALERT, "Normal G6PD genotype", "Standard dosing per product label",
                "G6PD Genotype", "g6pd_genotype",
            )
        return _unknown("G6PD Genotype")

    if test_type == "Phenotype":
        value = _numeric_estimate(test_result)
        if value is None:
            return _unknown("G6PD Enzyme Activity Phenotype")
        threshold = reference_range_low if reference_range_low is not None else G6PD_DEFAULT_REFERENCE_LOW
        threshold_note = (
            f"the ordering lab's own reference range (lower limit {threshold}%)"
            if reference_range_low is not None
            else f"the MVP default reference range (lower limit {threshold}%, no lab-specific range supplied)"
        )
        if value < threshold:
            return _result(
                RISK_HIGH,
                f"G6PD enzyme activity {test_result.strip()} is below {threshold_note}, "
                "indicating deficiency",
                dosage,
                "G6PD Enzyme Activity Phenotype",
                "g6pd_phenotype",
            )
        return _result(
            RISK_NO_ALERT,
            f"G6PD enzyme activity {test_result.strip()} is within {threshold_note}",
            "Standard dosing per product label",
            "G6PD Enzyme Activity Phenotype",
            "g6pd_phenotype",
        )

    return _unknown()


def _evaluate_tacrolimus_pgx(test_result: str) -> dict:
    """CYP3A5 genotype-guided tacrolimus STARTING-DOSE rule (pre-prescribing PGx).

    Deliberately separate from _evaluate_tacrolimus_tdm: this rule answers "what
    starting dose should this patient begin on," based on a one-time genotype: it
    never depends on, and is never triggered by, a measured trough level.
    """
    evidence_type = "CYP3A5 Genotype (Starting-Dose PGx)"
    diplotype = _normalize_diplotype(test_result)

    if diplotype in TACROLIMUS_CYP3A5_EXPRESSER:
        return _result(
            RISK_HIGH,
            "CYP3A5 expresser genotype; standard weight-based starting dose is "
            "likely subtherapeutic",
            "Increase starting dose (~1.5-2x standard weight-based starting dose per CPIC); "
            "confirm adequacy with early trough monitoring",
            evidence_type,
            "tacrolimus_cyp3a5_pgx",
        )
    if diplotype in TACROLIMUS_CYP3A5_NON_EXPRESSER:
        return _result(
            RISK_NO_ALERT,
            "CYP3A5 non-expresser genotype; standard tacrolimus exposure expected",
            "Standard weight-based starting dose per product label",
            evidence_type,
            "tacrolimus_cyp3a5_pgx",
        )
    return _unknown(evidence_type)


def _evaluate_tacrolimus_tdm(test_result: str, indication: str = None) -> dict:
    """Tacrolimus trough-level therapeutic drug monitoring (TDM) alert.

    Deliberately separate from _evaluate_tacrolimus_pgx: this is a recurring,
    post-prescribing monitoring signal based on a measured blood level, not a
    one-time genotype-driven starting-dose decision.

    The target trough range is indication-dependent (transplant protocols
    differ in target trough by organ) -- see TACROLIMUS_TDM_TARGETS. An
    unrecognized or missing `indication` falls back to the kidney-transplant
    range rather than silently assuming a single universal target.
    """
    evidence_type = "Tacrolimus Trough Level (TDM Alert)"
    value = _numeric_estimate(test_result)
    if value is None:
        return _unknown(evidence_type)

    indication_key = (indication or "").strip().lower()
    if indication_key in TACROLIMUS_TDM_TARGETS:
        low, high = TACROLIMUS_TDM_TARGETS[indication_key]
        indication_label = indication.strip()
    else:
        low, high = TACROLIMUS_TDM_DEFAULT_TARGET
        indication_label = "unspecified indication (default kidney-transplant range applied)"

    if value > high:
        return _result(
            RISK_HIGH,
            f"Supratherapeutic tacrolimus trough level ({test_result.strip()}) for "
            f"{indication_label} (target {low}-{high} ng/mL); risk of nephrotoxicity",
            "Reduce dose and recheck trough level",
            evidence_type,
            "tacrolimus_tdm",
        )
    if value < low:
        return _result(
            RISK_HIGH,
            f"Subtherapeutic tacrolimus trough level ({test_result.strip()}) for "
            f"{indication_label} (target {low}-{high} ng/mL); risk of rejection",
            "Increase dose and recheck trough level",
            evidence_type,
            "tacrolimus_tdm",
        )
    return _result(
        RISK_NO_ALERT,
        f"Tacrolimus trough level within the {indication_label} therapeutic range "
        f"({test_result.strip()}; target {low}-{high} ng/mL)",
        "Maintain current dose",
        evidence_type,
        "tacrolimus_tdm",
    )


def _evaluate_tacrolimus(test_type: str, test_result: str, indication: str = None) -> dict:
    if test_type == "Genotype":
        return _evaluate_tacrolimus_pgx(test_result)
    if test_type == "Phenotype":
        return _evaluate_tacrolimus_tdm(test_result, indication=indication)
    return _unknown()


def _parse_warfarin_genotype(test_result: str):
    """Parse 'CYP2C9=*1/*2;VKORC1=AG' (case/spacing tolerant) into (cyp2c9, vkorc1)."""
    cyp2c9 = None
    vkorc1 = None
    for part in (test_result or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().upper()
        if key == "CYP2C9":
            cyp2c9 = _normalize_diplotype(value)
        elif key == "VKORC1":
            vkorc1 = value.strip().upper()
    return cyp2c9, vkorc1


def _cyp2c9_category(diplotype):
    if diplotype in {"*1/*1"}:
        return "normal"
    if diplotype in {"*1/*2", "*1/*3"}:
        return "intermediate"
    if diplotype in {"*2/*2", "*2/*3", "*3/*3"}:
        return "poor"
    return None


def _vkorc1_category(genotype):
    if genotype in {"GG"}:
        return "normal"
    if genotype in {"AG"}:
        return "intermediate"
    if genotype in {"AA"}:
        return "high"
    return None


def _evaluate_warfarin_pgx(test_result: str) -> dict:
    """Simplified CYP2C9 + VKORC1 combined warfarin sensitivity category.

    This is a categorical simplification of CPIC's warfarin dosing guideline
    (which uses a full pharmacogenetic dosing algorithm incorporating age,
    weight, amiodarone use, and other covariates) -- it classifies relative
    dose-reduction need and monitoring intensity, not an exact starting
    mg/day dose.
    """
    evidence_type = "CYP2C9 + VKORC1 Genotype"
    cyp2c9_dip, vkorc1_geno = _parse_warfarin_genotype(test_result)
    cyp2c9_cat = _cyp2c9_category(cyp2c9_dip)
    vkorc1_cat = _vkorc1_category(vkorc1_geno)

    if cyp2c9_cat is None or vkorc1_cat is None:
        return _unknown(evidence_type)

    if cyp2c9_cat == "poor" or vkorc1_cat == "high":
        return _result(
            RISK_HIGH,
            f"Highly increased warfarin sensitivity (CYP2C9 {cyp2c9_dip}, VKORC1 {vkorc1_geno})",
            "Substantially reduce initial dose (~50-80% below standard, per CPIC "
            "categorical guidance) and increase INR monitoring frequency",
            evidence_type,
            "warfarin_cyp2c9_vkorc1",
        )
    if cyp2c9_cat == "intermediate" or vkorc1_cat == "intermediate":
        return _result(
            RISK_HIGH,
            f"Increased warfarin sensitivity (CYP2C9 {cyp2c9_dip}, VKORC1 {vkorc1_geno})",
            "Reduce initial dose (~30-50% below standard, per CPIC categorical "
            "guidance) and increase INR monitoring frequency",
            evidence_type,
            "warfarin_cyp2c9_vkorc1",
        )
    return _result(
        RISK_NO_ALERT,
        f"Normal warfarin sensitivity (CYP2C9 {cyp2c9_dip}, VKORC1 {vkorc1_geno})",
        "Standard initial dosing with routine INR-guided titration",
        evidence_type,
        "warfarin_cyp2c9_vkorc1",
    )


def _evaluate_warfarin(test_type: str, test_result: str) -> dict:
    if test_type == "Genotype":
        return _evaluate_warfarin_pgx(test_result)
    return _unknown()


def evaluate_prescription(
    drug: str, test_type: str, test_result: str, *, indication: str = None,
    reference_range_low: float = None,
) -> dict:
    """Evaluate a requested drug against a genotype or phenotype test result.

    `test_type` is "Genotype" or "Phenotype"; `test_result` is the free-text
    lab value (a CYP2C19 or CYP3A5 diplotype, an HLA allele status, a PRU score,
    a G6PD enzyme percentage/status, or a tacrolimus trough level).

    Supported drugs: Clopidogrel (Genotype + Phenotype), Carbamazepine,
    Allopurinol, Abacavir (Genotype), Primaquine, Rasburicase
    (Genotype + Phenotype), Tacrolimus (Genotype PGx + Phenotype TDM),
    Warfarin (Genotype: combined CYP2C9 + VKORC1).

    `indication` (Tacrolimus only) is the transplant indication (e.g.
    "Kidney Transplant", "Liver Transplant") that selects the TDM target
    trough range; ignored for every other drug. `reference_range_low`
    (Primaquine/Rasburicase Phenotype only) is the ordering lab's own
    G6PD reference-range lower limit; ignored otherwise. Both default to
    None, preserving the documented MVP defaults when omitted.
    """
    drug_key = (drug or "").strip().lower()
    test_type = (test_type or "").strip().capitalize()

    if drug_key == "clopidogrel":
        return _evaluate_clopidogrel(test_type, test_result)
    if drug_key in HLA_DRUG_GENE:
        return _evaluate_hla(drug_key, test_type, test_result)
    if drug_key in G6PD_DRUGS:
        return _evaluate_g6pd(test_type, test_result, reference_range_low=reference_range_low)
    if drug_key == "tacrolimus":
        return _evaluate_tacrolimus(test_type, test_result, indication=indication)
    if drug_key == "warfarin":
        return _evaluate_warfarin(test_type, test_result)

    return _unknown()
