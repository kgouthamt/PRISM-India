"""Tier 3 of the PRISM-India pre-test triage pipeline: PGx Actionability Triage.

Combines the Clinical Engine (engine.clinical) and DDI Engine (engine.ddi)
outputs into a single pre-test recommendation: is a pharmacogenomic test for
this drug actually likely to change management, *before* any genetic result
exists? This is deliberately independent of engine.rules, which handles the
downstream genotype/phenotype -> dosing decision *after* a PGx test result is
already available -- triage answers "should we test at all," rules.py
answers "given the test result, what do we do."

Output triage states:
    HIGH PRIORITY   -- testing strongly indicated
    CONSIDER        -- genetic info may influence treatment
    LOW PRIORITY    -- testing unlikely to change management
"""

from engine.clinical import assess_bleeding_risk_labs, assess_hepatic_function, assess_renal_function
from engine.ddi import check_drug_interactions

TRIAGE_HIGH = "HIGH PRIORITY"
TRIAGE_CONSIDER = "CONSIDER"
TRIAGE_LOW = "LOW PRIORITY"


def _clopidogrel_triage(concurrent_medications):
    ddi_findings = check_drug_interactions("clopidogrel", concurrent_medications)
    rationale = [
        "CYP2C19 poor/intermediate metabolizer status changes first-line "
        "antiplatelet selection and carries an FDA boxed warning for reduced "
        "effectiveness.",
    ]
    if ddi_findings:
        rationale.append(
            "Concurrent CYP2C19-inhibiting medication further reduces expected "
            "clopidogrel activation, compounding any poor/intermediate "
            "metabolizer risk."
        )
    return {
        "triage": TRIAGE_HIGH,
        "rationale": rationale,
        "ddi_findings": ddi_findings,
        "clinical_findings": [],
    }


def _tacrolimus_triage(concurrent_medications, egfr=None, alt=None, ast=None, total_bilirubin=None):
    ddi_findings = check_drug_interactions("tacrolimus", concurrent_medications)
    renal = assess_renal_function(egfr)
    hepatic = assess_hepatic_function(alt, ast, total_bilirubin)

    rationale = [
        "CYP3A5 expresser status changes the tacrolimus starting dose by "
        "~1.5-2x per CPIC; the drug's narrow therapeutic index makes this "
        "clinically actionable.",
    ]
    if renal["nephrotoxicity_risk"] in ("MODERATE", "HIGH"):
        rationale.append(
            f"Baseline renal function ({renal['stage']}: {renal['category']}) "
            "raises nephrotoxicity risk independent of genotype; monitor "
            "trough levels closely."
        )
    if hepatic["impairment"] not in ("NONE", "UNKNOWN"):
        rationale.append(f"Hepatic impairment ({hepatic['impairment'].title()}): {hepatic['detail']}")
    if ddi_findings:
        rationale.append(
            "Concurrent CYP3A4 modulator identified; expect altered tacrolimus "
            "exposure regardless of genotype."
        )

    return {
        "triage": TRIAGE_HIGH,
        "rationale": rationale,
        "ddi_findings": ddi_findings,
        "clinical_findings": [renal, hepatic],
    }


def _warfarin_triage(concurrent_medications, inr=None, platelets=None, hemoglobin=None):
    ddi_findings = check_drug_interactions("warfarin", concurrent_medications)
    bleeding_risk = assess_bleeding_risk_labs(inr, platelets, hemoglobin)

    severe_ddi = any(finding["severity"] == "MAJOR" for finding in ddi_findings)
    high_baseline_risk = bleeding_risk["baseline_bleeding_risk"] == "HIGH"

    rationale = [
        "Routine INR monitoring and dose titration is often sufficient for "
        "warfarin management without upfront genetic testing.",
    ]
    if high_baseline_risk:
        rationale.append(
            "Elevated baseline bleeding risk (" + "; ".join(bleeding_risk["flags"]) +
            ") makes genotype-guided starting-dose selection more valuable."
        )
    if severe_ddi:
        rationale.append(
            "A severe drug-drug interaction is present; this independently "
            "elevates bleeding risk and warrants closer management regardless "
            "of genotype."
        )

    triage = TRIAGE_HIGH if (high_baseline_risk or severe_ddi) else TRIAGE_CONSIDER

    return {
        "triage": triage,
        "rationale": rationale,
        "ddi_findings": ddi_findings,
        "clinical_findings": [bleeding_risk],
    }


_TRIAGE_DISPATCH = {"clopidogrel", "tacrolimus", "warfarin"}


def triage_pgx_actionability(drug: str, concurrent_medications: list = None, **clinical_context) -> dict:
    """Pre-test triage: should a PGx test even be ordered for this drug?

    `clinical_context` keys used, all optional: egfr, alt, ast,
    total_bilirubin (Tacrolimus); inr, platelets, hemoglobin (Warfarin).

    Returns {"triage", "rationale", "ddi_findings", "clinical_findings"}.
    A drug outside this triage layer's MVP scope (Clopidogrel, Tacrolimus,
    Warfarin) returns LOW PRIORITY with an explanatory rationale, rather than
    a fabricated assessment.
    """
    drug_key = (drug or "").strip().lower()

    if drug_key == "clopidogrel":
        return _clopidogrel_triage(concurrent_medications)
    if drug_key == "tacrolimus":
        return _tacrolimus_triage(
            concurrent_medications,
            egfr=clinical_context.get("egfr"),
            alt=clinical_context.get("alt"),
            ast=clinical_context.get("ast"),
            total_bilirubin=clinical_context.get("total_bilirubin"),
        )
    if drug_key == "warfarin":
        return _warfarin_triage(
            concurrent_medications,
            inr=clinical_context.get("inr"),
            platelets=clinical_context.get("platelets"),
            hemoglobin=clinical_context.get("hemoglobin"),
        )

    return {
        "triage": TRIAGE_LOW,
        "rationale": ["No pre-test triage model is defined for this drug in the current MVP scope."],
        "ddi_findings": [],
        "clinical_findings": [],
    }
