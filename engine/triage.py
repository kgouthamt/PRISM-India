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
age/weight, the DDI Engine's findings, and the calculated baseline ADR risk
flag from engine.clinical.calculate_adr_risk() (the Clinical Risk
Assessment). It is never driven by raw subjective predictor checkboxes
themselves (this module never sees "previous ADR history" or "heart
failure" directly): only the single boolean verdict the Clinical Risk
Assessment already computed crosses into this triage, exactly like a lab
result crosses in as "HIGH"/"LOW"/"UNKNOWN" rather than a raw lab value plus
its interpretation logic. Any lab a clinician marks "Test Not Done /
Unknown" is passed through as `None` and never raises a risk flag.

For Warfarin specifically, a "High Baseline ADR Risk" flag from the
Clinical Risk Assessment acts as an amplifying factor: combined with an
elderly patient (age >= 65, matching GerontoNet's own target population),
it escalates the triage to HIGH PRIORITY immediately, on top of the
existing lab/DDI-driven escalation conditions. For Clopidogrel and
Tacrolimus, which are already always HIGH PRIORITY, the same flag is
instead surfaced as an additional rationale line, since there is no higher
triage state to escalate to.

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


def _clopidogrel_triage(concurrent_medications, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("clopidogrel", concurrent_medications)
    rationale = [
        "CYP2C19 poor/intermediate metabolizer status changes first-line "
        "antiplatelet selection and carries an FDA boxed warning for reduced "
        "effectiveness; PGx is highly actionable for efficacy regardless of "
        "routine labs.",
    ]
    if high_baseline_adr_risk:
        rationale.append(
            "The Clinical Risk Assessment flags High Baseline ADR Risk; already at the highest "
            "triage priority, but this warrants extra vigilance when "
            "monitoring for adverse effects."
        )
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
    if high_baseline_adr_risk:
        rationale.append(
            "The Clinical Risk Assessment flags High Baseline ADR Risk; already at the highest "
            "triage priority, but this warrants extra vigilance when "
            "monitoring for adverse effects."
        )
    warnings = []
    if renal["nephrotoxicity_risk"] == "HIGH":
        warnings.append(
            f"eGFR {renal['egfr']} (< {EGFR_THRESHOLD}): while PGx sets the "
            "starting-dose baseline, lab-driven therapeutic drug monitoring "
            "(TDM) is mandatory -- nephrotoxicity risk per KDIGO 2024."
        )
    if hepatic["impairment_risk"] == "HIGH":
        warnings.append(
            f"ALT/AST {hepatic['alt_ast']} U/L (> {ALT_AST_THRESHOLD}): while "
            "PGx sets the starting-dose baseline, lab-driven TDM and "
            "empirical dose caution are mandatory per NFI."
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
    }


def _warfarin_triage(concurrent_medications, platelets=None, pt_inr=None, high_baseline_adr_risk=False, age=None):
    ddi_findings = check_drug_interactions("warfarin", concurrent_medications)
    bleeding_risk = assess_bleeding_risk_labs(platelets, pt_inr)

    severe_ddi = any(finding["severity"] == "MAJOR" for finding in ddi_findings)
    high_baseline_bleeding_risk = bleeding_risk["baseline_bleeding_risk"] == "HIGH"
    is_elderly = age is not None and age >= ELDERLY_AGE_THRESHOLD
    elderly_high_adr_risk = high_baseline_adr_risk and is_elderly

    rationale = [
        "Routine PT/INR monitoring and dose titration is often sufficient for "
        "warfarin management without upfront genetic testing.",
    ]
    warnings = []
    if high_baseline_bleeding_risk:
        warnings.append(
            "High baseline bleeding risk (" + "; ".join(bleeding_risk["flags"]) +
            ") makes genotype-guided starting-dose selection more valuable."
        )
    if severe_ddi:
        warnings.append(
            "A severe drug-drug interaction is present (e.g. amiodarone or an "
            "NSAID); this independently elevates bleeding risk and warrants "
            "closer management regardless of genotype."
        )
    if elderly_high_adr_risk:
        warnings.append(
            f"Elderly patient (age {age} >= {ELDERLY_AGE_THRESHOLD}) with a High "
            "Baseline ADR Risk flag from the Clinical Risk Assessment "
            "(GerontoNet-anchored): this population is at "
            "materially higher risk of an adverse drug reaction, and "
            "genotype-guided starting-dose selection is correspondingly "
            "more valuable than routine titration alone."
        )
    elif high_baseline_adr_risk:
        rationale.append(
            "The Clinical Risk Assessment flags High Baseline ADR Risk, but "
            "the patient is not elderly (age < 65); this alone does not "
            "escalate warfarin triage per the GerontoNet-anchored "
            "amplification rule."
        )

    triage = (
        TRIAGE_HIGH
        if (high_baseline_bleeding_risk or severe_ddi or elderly_high_adr_risk)
        else TRIAGE_CONSIDER
    )

    return {
        "triage": triage,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [bleeding_risk],
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

    Returns {"triage", "rationale", "warnings", "ddi_findings", "clinical_findings"}.
    `warnings` (distinct from `rationale`) carries strong, lab-driven safety
    flags -- e.g. Tacrolimus's mandatory-TDM warning on an abnormal eGFR/
    ALT-AST, or Warfarin's elderly+high-ADR-risk escalation warning. A drug
    outside this triage's MVP scope (Clopidogrel, Tacrolimus, Warfarin)
    returns LOW PRIORITY with an explanatory rationale, rather than a
    fabricated assessment.
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
        }

    if age_weight["flags"]:
        result["rationale"] = result["rationale"] + age_weight["flags"]
    result["clinical_findings"] = result["clinical_findings"] + [age_weight]
    return result
