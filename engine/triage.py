"""Tier 3 of the PRISM-India pre-test triage pipeline: PGx Actionability Triage.

Combines the Clinical Engine (engine.clinical) and DDI Engine (engine.ddi)
outputs into a single pre-test recommendation: is a pharmacogenomic test for
this drug actually likely to change management, *before* any genetic result
exists? This is deliberately independent of engine.rules, which handles the
downstream genotype/phenotype -> dosing decision *after* a PGx test result is
already available -- triage answers "should we test at all," rules.py
answers "given the test result, what do we do."

The 🔴/🟡/🟢 score is driven strictly by the drug, exact numeric routine lab
values (eGFR, ALT/AST, Platelets, PT/INR), age/weight, and the DDI Engine's
findings -- never by subjective patient-reported history (a prior adverse
drug reaction, a prior treatment failure). That data is real and clinically
relevant, but it is not the kind of routine, verifiable input this triage
layer is scoped to reason about. Any lab a clinician marks "Test Not Done /
Unknown" is passed through as `None` and never raises a risk flag.

Output triage states:
    HIGH PRIORITY   -- testing strongly indicated
    CONSIDER        -- genetic info may influence treatment
    LOW PRIORITY    -- testing unlikely to change management
"""

from engine.clinical import (
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
)
from engine.ddi import check_drug_interactions

TRIAGE_HIGH = "HIGH PRIORITY"
TRIAGE_CONSIDER = "CONSIDER"
TRIAGE_LOW = "LOW PRIORITY"


def _clopidogrel_triage(concurrent_medications):
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
    }


def _tacrolimus_triage(concurrent_medications, egfr=None, alt_ast=None):
    ddi_findings = check_drug_interactions("tacrolimus", concurrent_medications)
    renal = assess_renal_function(egfr)
    hepatic = assess_hepatic_function(alt_ast)

    rationale = [
        "CYP3A5 expresser status changes the tacrolimus starting dose by "
        "~1.5-2x per CPIC; PGx sets the starting-dose baseline regardless of "
        "routine labs.",
    ]
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


def _warfarin_triage(concurrent_medications, platelets=None, pt_inr=None):
    ddi_findings = check_drug_interactions("warfarin", concurrent_medications)
    bleeding_risk = assess_bleeding_risk_labs(platelets, pt_inr)

    severe_ddi = any(finding["severity"] == "MAJOR" for finding in ddi_findings)
    high_baseline_risk = bleeding_risk["baseline_bleeding_risk"] == "HIGH"

    rationale = [
        "Routine PT/INR monitoring and dose titration is often sufficient for "
        "warfarin management without upfront genetic testing.",
    ]
    warnings = []
    if high_baseline_risk:
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

    triage = TRIAGE_HIGH if (high_baseline_risk or severe_ddi) else TRIAGE_CONSIDER

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
) -> dict:
    """Pre-test triage: should a PGx test even be ordered for this drug?

    All clinical-context parameters are objective, exact numeric routine
    inputs: `egfr` (mL/min/1.73m^2), `alt_ast` (U/L), `platelets` (x10^3/uL),
    `pt_inr` (ratio), `age` (years), `weight` (kg). Any of these may be
    `None` when a clinician marks a test "Not Done / Unknown" -- that never
    raises a risk flag. There is no parameter for patient-reported history
    (e.g. a prior ADR or treatment failure) -- this triage layer does not
    use subjective inputs.

    Returns {"triage", "rationale", "warnings", "ddi_findings", "clinical_findings"}.
    `warnings` (distinct from `rationale`) carries strong, lab-driven safety
    flags -- e.g. Tacrolimus's mandatory-TDM warning on an abnormal eGFR/
    ALT-AST. A drug outside this triage layer's MVP scope (Clopidogrel,
    Tacrolimus, Warfarin) returns LOW PRIORITY with an explanatory
    rationale, rather than a fabricated assessment.
    """
    drug_key = (drug or "").strip().lower()
    age_weight = assess_age_weight_context(age, weight)

    if drug_key == "clopidogrel":
        result = _clopidogrel_triage(concurrent_medications)
    elif drug_key == "tacrolimus":
        result = _tacrolimus_triage(concurrent_medications, egfr=egfr, alt_ast=alt_ast)
    elif drug_key == "warfarin":
        result = _warfarin_triage(concurrent_medications, platelets=platelets, pt_inr=pt_inr)
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
