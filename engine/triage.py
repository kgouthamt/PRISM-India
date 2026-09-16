"""PGx Actionability Triage: the pharmacogenomic testing gatekeeper for the
PRISM-AIIMS pre-test triage pipeline.

Combines the Clinical Engine (engine.clinical) and DDI Engine (engine.ddi)
outputs into a single pre-test recommendation: is a pharmacogenomic test for
this drug actually likely to change management, *before* any genetic result
exists? This is deliberately independent of engine.rules, which handles the
downstream genotype/phenotype -> dosing decision *after* a PGx test result is
already available -- triage answers "should we test at all," rules.py
answers "given the test result, what do we do."

The HIGH PRIORITY / CONSIDER / LOW PRIORITY recommendation is driven by the
drug, exact numeric routine lab values (eGFR, ALT/AST, Platelets, PT/INR),
age/weight, and the DDI Engine's findings. Any lab a clinician marks "Test
Not Done / Unknown" is passed through as `None` and never raises a flag.

General ADR risk vs. PGx actionability are deliberately kept as two
distinct conceptual outputs, per clinical reviewer feedback: a patient's
general baseline ADR risk (from the Clinical Risk Assessment's
calculate_adr_risk()) makes them generally *fragile*, but that alone does
not mean every drug's genetic risk is amplified by it. This module never
receives or reasons about the raw subjective predictor checkboxes behind
that flag (e.g. "previous ADR history" or "heart failure") -- only the
single boolean verdict crosses in, exactly like a lab result crosses in as
"NORMAL"/"REDUCED"/"UNKNOWN" rather than a raw lab value plus its
interpretation logic. The result of that separation is surfaced as its own
`general_adr_risk` field, distinct from `triage` and `rationale`:

    - `triage` / `rationale` / `warnings`: purely about whether *this drug's*
      genetic risk is actionable -- driven only by labs, DDIs, and (for
      Warfarin specifically) an amplification rule tied to the genetic
      danger itself, never by general ADR fragility alone.
    - `general_adr_risk`: the patient's baseline ADR risk status and whether
      it specifically amplified this drug's triage priority, reported
      separately so the two concepts are never conflated.

For Warfarin specifically, a "High Baseline ADR Risk" flag amplifies the
*genetic* danger: combined with an elderly patient (age >= 65, matching
GerontoNet's own target population), bleeding risk from genotype-driven
over-anticoagulation is materially higher, so it escalates the triage to
HIGH PRIORITY immediately, on top of the existing lab/DDI-driven escalation
conditions. For Clopidogrel and Tacrolimus, which are already always HIGH
PRIORITY, the same general ADR risk flag never changes the triage state
(there is no higher state, and general fragility does not by itself change
either drug's genetic actionability) -- it is only surfaced via
`general_adr_risk` as a monitoring consideration.

Output triage states:
    HIGH PRIORITY   -- testing strongly indicated
    CONSIDER        -- genetic info may influence treatment
    LOW PRIORITY    -- testing unlikely to change management
"""

from engine.clinical import (
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    ELDERLY_AGE_THRESHOLD,
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
)
from engine.ddi import check_drug_interactions

TRIAGE_HIGH = "HIGH PRIORITY"
TRIAGE_CONSIDER = "CONSIDER"
TRIAGE_LOW = "LOW PRIORITY"


def _general_adr_risk_output(high_baseline_adr_risk: bool, amplifies_pgx_triage: bool, is_ceiling_priority: bool) -> dict:
    """Build the general-ADR-risk output, kept structurally separate from
    the drug's PGx actionability triage/rationale (see module docstring).
    """
    if high_baseline_adr_risk and amplifies_pgx_triage:
        note = (
            "High Baseline ADR Risk specifically amplifies this drug's genetic "
            "risk (elderly patient, GerontoNet-anchored fragility) and has "
            "escalated PGx triage priority."
        )
    elif high_baseline_adr_risk and is_ceiling_priority:
        note = (
            "High Baseline ADR Risk makes this patient generally fragile; it "
            "does not change PGx triage priority (already at the highest "
            "priority for this drug) but warrants closer monitoring for "
            "adverse effects."
        )
    elif high_baseline_adr_risk:
        note = (
            "High Baseline ADR Risk makes this patient generally fragile, but "
            "does not, on its own, amplify this drug's genetic risk -- PGx "
            "triage priority is unaffected."
        )
    else:
        note = "Standard baseline ADR risk; no amplification applicable to PGx triage."

    return {
        "high_baseline_adr_risk": high_baseline_adr_risk,
        "amplifies_pgx_triage": amplifies_pgx_triage,
        "note": note,
    }


def _clopidogrel_triage(concurrent_medications, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("clopidogrel", concurrent_medications)
    rationale = [
        "CYP2C19 poor/intermediate metabolizer status changes first-line "
        "antiplatelet selection and carries an FDA boxed warning for reduced "
        "effectiveness; PGx is highly actionable for efficacy regardless of "
        "routine labs.",
    ]
    warnings = []
    if ddi_findings:
        warnings.append(
            "Concurrent CYP2C19-inhibiting medication further reduces expected "
            "clopidogrel activation, compounding any poor/intermediate "
            "metabolizer risk."
        )
    return {
        "triage": TRIAGE_HIGH,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [],
        "general_adr_risk": _general_adr_risk_output(
            high_baseline_adr_risk, amplifies_pgx_triage=False, is_ceiling_priority=True,
        ),
    }


def _tacrolimus_triage(concurrent_medications, egfr=None, alt_ast=None, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("tacrolimus", concurrent_medications)
    renal = assess_renal_function(egfr)
    hepatic = assess_hepatic_function(alt_ast)

    rationale = [
        "CYP3A5 expresser status changes the tacrolimus starting dose by "
        "~1.5-2x per CPIC; PGx sets the starting-dose baseline regardless of "
        "routine labs.",
    ]
    warnings = []
    if renal["renal_function_status"] == "REDUCED":
        warnings.append(
            f"eGFR {renal['egfr']} (< {EGFR_THRESHOLD}): reduced eGFR requires "
            "clinical correlation for renal dose adjustment per KDIGO 2024 -- "
            "while PGx sets the starting-dose baseline, lab-driven "
            "therapeutic drug monitoring (TDM) is mandatory regardless of "
            "genotype."
        )
    if hepatic["transaminase_status"] == "ELEVATED":
        warnings.append(
            f"ALT/AST {hepatic['alt_ast']} U/L (> {ALT_AST_THRESHOLD}): "
            "elevated transaminases are a laboratory abnormality requiring "
            "clinical correlation per NFI, not an automatic hepatic-"
            "impairment diagnosis -- PGx sets the starting-dose baseline, "
            "but lab-driven TDM and empirical dose caution are mandatory "
            "pending that correlation."
        )
    if ddi_findings:
        warnings.append(
            "Concurrent CYP3A4 modulator identified; expect altered tacrolimus "
            "exposure regardless of genotype -- TDM is mandatory."
        )

    return {
        "triage": TRIAGE_HIGH,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [renal, hepatic],
        "general_adr_risk": _general_adr_risk_output(
            high_baseline_adr_risk, amplifies_pgx_triage=False, is_ceiling_priority=True,
        ),
    }


def _warfarin_triage(concurrent_medications, platelets=None, pt_inr=None, high_baseline_adr_risk=False, age=None):
    ddi_findings = check_drug_interactions("warfarin", concurrent_medications)
    coagulation = assess_bleeding_risk_labs(platelets, pt_inr)

    severe_ddi = any(finding["severity"] == "MAJOR" for finding in ddi_findings)
    abnormal_coagulation = coagulation["coagulation_cbc_status"] == "ABNORMAL"
    is_elderly = age is not None and age >= ELDERLY_AGE_THRESHOLD
    amplifies_pgx_triage = high_baseline_adr_risk and is_elderly

    rationale = [
        "Routine PT/INR monitoring and dose titration is often sufficient for "
        "warfarin management without upfront genetic testing.",
    ]
    warnings = []
    if abnormal_coagulation:
        warnings.append(
            "Abnormal coagulation/CBC parameters (" + "; ".join(coagulation["flags"]) +
            ") require clinical correlation and make genotype-guided "
            "starting-dose selection more valuable."
        )
    if severe_ddi:
        warnings.append(
            "A severe drug-drug interaction is present (e.g. amiodarone or an "
            "NSAID); this independently elevates bleeding risk and warrants "
            "closer management regardless of genotype."
        )
    if amplifies_pgx_triage:
        warnings.append(
            f"Elderly patient (age {age} >= {ELDERLY_AGE_THRESHOLD}) with a "
            "High Baseline ADR Risk flag: this population is at materially "
            "higher risk of an adverse drug reaction from genotype-driven "
            "over-anticoagulation specifically, so genotype-guided "
            "starting-dose selection is correspondingly more valuable than "
            "routine titration alone."
        )

    triage = (
        TRIAGE_HIGH
        if (abnormal_coagulation or severe_ddi or amplifies_pgx_triage)
        else TRIAGE_CONSIDER
    )

    return {
        "triage": triage,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [coagulation],
        "general_adr_risk": _general_adr_risk_output(
            high_baseline_adr_risk, amplifies_pgx_triage=amplifies_pgx_triage, is_ceiling_priority=False,
        ),
    }


def triage_pgx_actionability(
    drug: str,
    concurrent_medications: list = None,
    *,
    age: float = None,
    weight: float = None,
    egfr: float = None,
    alt_ast: float = None,
    platelets: float = None,
    pt_inr: float = None,
    high_baseline_adr_risk: bool = False,
) -> dict:
    """Pre-test triage: should a PGx test even be ordered for this drug?

    All clinical-context parameters are objective, exact numeric routine
    inputs: `egfr` (mL/min/1.73m^2), `alt_ast` (U/L), `platelets` (x10^3/uL),
    `pt_inr` (ratio), `age` (years), `weight` (kg). Any of these may be
    `None` when a clinician marks a test "Not Done / Unknown" -- that never
    raises a risk flag. `high_baseline_adr_risk` is the single boolean
    verdict already computed by the Clinical Risk Assessment's
    engine.clinical.calculate_adr_risk() -- this function never receives or
    reasons about the raw subjective predictor checkboxes (previous ADR
    history, heart failure, etc.) behind it.

    Returns {"triage", "rationale", "warnings", "ddi_findings",
    "clinical_findings", "general_adr_risk"}. `warnings` (distinct from
    `rationale`) carries strong, lab-driven safety flags -- e.g. Tacrolimus's
    mandatory-TDM warning on a reduced eGFR / elevated transaminases, or
    Warfarin's elderly+high-ADR-risk escalation warning. `general_adr_risk`
    is kept structurally separate from `triage`/`rationale`: it reports the
    patient's baseline ADR risk status and whether it specifically amplified
    this drug's triage priority, without conflating general fragility with
    this drug's genetic actionability. A drug outside this triage's MVP
    scope (Clopidogrel, Tacrolimus, Warfarin) returns LOW PRIORITY with an
    explanatory rationale, rather than a fabricated assessment.
    """
    drug_key = (drug or "").strip().lower()
    age_weight = assess_age_weight_context(age, weight)

    if drug_key == "clopidogrel":
        result = _clopidogrel_triage(concurrent_medications, high_baseline_adr_risk=high_baseline_adr_risk)
    elif drug_key == "tacrolimus":
        result = _tacrolimus_triage(
            concurrent_medications, egfr=egfr, alt_ast=alt_ast,
            high_baseline_adr_risk=high_baseline_adr_risk,
        )
    elif drug_key == "warfarin":
        result = _warfarin_triage(
            concurrent_medications, platelets=platelets, pt_inr=pt_inr,
            high_baseline_adr_risk=high_baseline_adr_risk, age=age,
        )
    else:
        result = {
            "triage": TRIAGE_LOW,
            "rationale": ["No pre-test triage model is defined for this drug in the current MVP scope."],
            "warnings": [],
            "ddi_findings": [],
            "clinical_findings": [],
            "general_adr_risk": _general_adr_risk_output(
                high_baseline_adr_risk, amplifies_pgx_triage=False, is_ceiling_priority=False,
            ),
        }

    if age_weight["flags"]:
        result["rationale"] = result["rationale"] + age_weight["flags"]
    result["clinical_findings"] = result["clinical_findings"] + [age_weight]
    return result
