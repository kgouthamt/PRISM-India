"""Deterministic pharmacogenomic + phenotypic rule engine (CPIC-based) with dosage guidance."""

import re

CLOPIDOGREL_NORMAL = {"*1/*1"}
CLOPIDOGREL_INTERMEDIATE = {"*1/*2", "*1/*3"}
CLOPIDOGREL_POOR = {"*2/*2", "*2/*3", "*3/*3"}

HLA_DRUG_GENE = {
    "carbamazepine": "HLA-B*15:02",
    "allopurinol": "HLA-B*58:01",
    "abacavir": "HLA-B*57:01",
}

G6PD_DRUGS = {"primaquine", "rasburicase"}


def _result(risk, reason, recommendation_and_dosage, evidence_type):
    return {
        "risk": risk,
        "reason": reason,
        "recommendation_and_dosage": recommendation_and_dosage,
        "evidence_type": evidence_type,
    }


def _unknown(evidence_type=None):
    return _result(
        "UNKNOWN",
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
                "SAFE",
                "Normal CYP2C19 metabolizer; expected clopidogrel activation",
                "Standard dose: 75 mg/day",
                "CYP2C19 Genotype",
            )
        if diplotype in CLOPIDOGREL_INTERMEDIATE:
            return _result(
                "HIGH",
                "Intermediate CYP2C19 metabolizer; reduced clopidogrel activation",
                "Prefer alternative antiplatelet (Prasugrel or Ticagrelor); "
                "if clopidogrel is unavoidable, escalate to 225 mg/day",
                "CYP2C19 Genotype",
            )
        if diplotype in CLOPIDOGREL_POOR:
            return _result(
                "HIGH",
                "Poor CYP2C19 metabolizer; markedly reduced clopidogrel activation",
                "Avoid clopidogrel entirely; prescribe Prasugrel or Ticagrelor",
                "CYP2C19 Genotype",
            )
        return _unknown("CYP2C19 Genotype")

    if test_type == "Phenotype":
        value = _numeric_estimate(test_result)
        if value is None:
            return _unknown("Platelet Reactivity (PRU) Phenotype")
        if value > 208:
            return _result(
                "HIGH",
                f"High on-treatment platelet reactivity (PRU {test_result.strip()}); "
                "inadequate clopidogrel response",
                "Recommend alternative antiplatelet (Prasugrel or Ticagrelor)",
                "Platelet Reactivity (PRU) Phenotype",
            )
        return _result(
            "SAFE",
            f"Platelet reactivity within therapeutic range (PRU {test_result.strip()})",
            "Standard dose: 75 mg/day",
            "Platelet Reactivity (PRU) Phenotype",
        )

    return _unknown()


def _evaluate_hla(drug_key: str, test_type: str, test_result: str) -> dict:
    gene = HLA_DRUG_GENE[drug_key]
    evidence_type = f"{gene} Genotype"
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
            "allopurinol": "Avoid allopurinol; prescribe Febuxostat instead",
            "abacavir": "Avoid abacavir entirely",
        }
        return _result("HIGH", reason_map[drug_key], dosage_map[drug_key], evidence_type)

    if status == "negative":
        return _result(
            "SAFE",
            f"{gene} allele not detected; no CPIC contraindication",
            "Standard dosing per product label",
            evidence_type,
        )

    return _unknown(evidence_type)


def _evaluate_g6pd(test_type: str, test_result: str) -> dict:
    dosage = "Avoid drug entirely to prevent acute hemolytic anemia"

    if test_type == "Genotype":
        status = (test_result or "").strip().lower()
        if "deficient" in status:
            return _result("HIGH", "G6PD-deficient genotype detected", dosage, "G6PD Genotype")
        if "normal" in status:
            return _result(
                "SAFE", "Normal G6PD genotype", "Standard dosing per product label", "G6PD Genotype"
            )
        return _unknown("G6PD Genotype")

    if test_type == "Phenotype":
        value = _numeric_estimate(test_result)
        if value is None:
            return _unknown("G6PD Enzyme Activity Phenotype")
        if value < 10:
            return _result(
                "HIGH",
                f"G6PD enzyme activity {test_result.strip()} indicates deficiency",
                dosage,
                "G6PD Enzyme Activity Phenotype",
            )
        return _result(
            "SAFE",
            f"G6PD enzyme activity {test_result.strip()} within normal range",
            "Standard dosing per product label",
            "G6PD Enzyme Activity Phenotype",
        )

    return _unknown()


def _evaluate_tacrolimus(test_type: str, test_result: str) -> dict:
    evidence_type = "Tacrolimus Trough Level Phenotype"
    if test_type != "Phenotype":
        return _unknown(evidence_type)

    value = _numeric_estimate(test_result)
    if value is None:
        return _unknown(evidence_type)
    if value > 15:
        return _result(
            "HIGH",
            f"Supratherapeutic tacrolimus trough level ({test_result.strip()}); "
            "risk of nephrotoxicity",
            "Reduce dose and recheck trough level",
            evidence_type,
        )
    if value < 5:
        return _result(
            "HIGH",
            f"Subtherapeutic tacrolimus trough level ({test_result.strip()}); risk of rejection",
            "Increase dose and recheck trough level",
            evidence_type,
        )
    return _result(
        "SAFE",
        f"Tacrolimus trough level within therapeutic range ({test_result.strip()})",
        "Maintain current dose",
        evidence_type,
    )


def evaluate_prescription(drug: str, test_type: str, test_result: str) -> dict:
    """Evaluate a requested drug against a genotype or phenotype test result.

    `test_type` is "Genotype" or "Phenotype"; `test_result` is the free-text
    lab value (a CYP2C19 diplotype, an HLA allele status, a PRU score, a
    G6PD enzyme percentage/status, or a tacrolimus trough level).
    """
    drug_key = (drug or "").strip().lower()
    test_type = (test_type or "").strip().capitalize()

    if drug_key == "clopidogrel":
        return _evaluate_clopidogrel(test_type, test_result)
    if drug_key in HLA_DRUG_GENE:
        return _evaluate_hla(drug_key, test_type, test_result)
    if drug_key in G6PD_DRUGS:
        return _evaluate_g6pd(test_type, test_result)
    if drug_key == "tacrolimus":
        return _evaluate_tacrolimus(test_type, test_result)

    return _unknown()
