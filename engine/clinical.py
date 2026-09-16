"""Objective clinical data assessment for the PRISM-AIIMS pre-test triage pipeline.

Assesses only routine, objective inputs a clinician already has on hand
*before* ordering any pharmacogenomic test -- Age, Weight, eGFR, ALT/AST,
Platelets, and PT/INR -- against exact, published numeric thresholds. Any
lab the clinician marks "Test Not Done / Unknown" is passed through as
`None` and never raises a risk flag -- absence of data is never treated as
evidence of abnormality.

Per clinical reviewer feedback, this module deliberately separates a
*laboratory abnormality* (an out-of-range number) from a *clinical
diagnosis* (a condition a clinician has actually established). None of the
`assess_*` functions below claim to detect "nephrotoxicity," "hepatic
impairment," or "bleeding risk" outright -- a single abnormal lab value is
never, by itself, a diagnosis. Each function instead reports the lab
abnormality plainly and states that it requires clinical correlation.

Sources:
    - Renal function: KDIGO 2024 Clinical Practice Guideline for CKD
      (eGFR < 60 mL/min/1.73m^2 is the threshold this MVP uses to flag a
      reduced eGFR reading for clinical correlation).
    - Hepatic function: CDSCO / National Formulary of India (NFI), used here
      to flag an elevated-transaminase lab abnormality (ALT/AST > 40 U/L,
      the standard upper limit of normal) for clinical correlation -- not to
      assert a hepatic-impairment diagnosis.
    - Coagulation/CBC: routine thresholds (platelets < 150 x10^3/uL, PT/INR
      > 1.2) used before starting an anticoagulant, flagged as abnormal
      coagulation/CBC parameters requiring clinical correlation.
    - Age/weight dosing context: FDA guidance on pediatric and weight-based
      dosing.
    - Baseline ADR risk (calculate_adr_risk): the ADATIP 9-Predictor Model,
      an institutional acute-presentation ADR risk model (all 9 predictors
      implemented); the actual validated GerontoNet ADR Risk Score (Onder G,
      et al. "Development and validation of a score to assess risk of
      adverse drug reactions among in-hospital patients 65 years or older:
      the GerontoNet ADR risk score." Arch Intern Med. 2010) -- a weighted
      0-10 point score, "High Risk" only at a total score of 4 or more, not
      a derived binary predictor-count heuristic; and a clinician-reported
      general clinical history (allergy, family history).
"""

KDIGO_SOURCE = "KDIGO 2024"
NFI_SOURCE = "CDSCO / National Formulary of India"
FDA_DOSING_SOURCE = "FDA Guidance (Pediatric / Weight-Based Dosing)"
ADATIP_SOURCE = "ADATIP 9-Predictor Model (institutional acute-presentation ADR risk model)"
GERONTONET_SOURCE = "GerontoNet ADR Risk Score (Onder et al., Arch Intern Med 2010)"

EGFR_THRESHOLD = 60.0
ALT_AST_THRESHOLD = 40.0
PLATELETS_THRESHOLD = 150.0
PT_INR_THRESHOLD = 1.2

_PEDIATRIC_AGE_YEARS = 18
_LOW_WEIGHT_KG = 40.0

ELDERLY_AGE_THRESHOLD = 65.0

MULTI_PREDICTOR_THRESHOLD = 2

# GerontoNet ADR Risk Score point values (Onder et al., Arch Intern Med 2010).
GERONTONET_COMORBIDITY_POINTS = 1
GERONTONET_HEART_FAILURE_POINTS = 1
GERONTONET_LIVER_DISEASE_POINTS = 1
GERONTONET_RENAL_FAILURE_POINTS = 1
GERONTONET_DRUGS_5_TO_7_POINTS = 1
GERONTONET_DRUGS_8_PLUS_POINTS = 4
GERONTONET_PREVIOUS_ADR_POINTS = 2
GERONTONET_MAX_SCORE = (
    GERONTONET_COMORBIDITY_POINTS + GERONTONET_HEART_FAILURE_POINTS
    + GERONTONET_LIVER_DISEASE_POINTS + GERONTONET_RENAL_FAILURE_POINTS
    + GERONTONET_DRUGS_8_PLUS_POINTS + GERONTONET_PREVIOUS_ADR_POINTS
)
GERONTONET_HIGH_RISK_THRESHOLD = 4
GERONTONET_RISK_HIGH = "High Risk"
GERONTONET_RISK_LOW = "Low Risk"

ADR_RISK_HIGH = "HIGH BASELINE ADR RISK"
ADR_RISK_STANDARD = "STANDARD"


def assess_renal_function(egfr: float = None) -> dict:
    """Flag a reduced-eGFR lab abnormality from an exact eGFR value
    (mL/min/1.73m^2) -- this is a lab reading, not a nephrotoxicity or
    renal-impairment diagnosis; it requires clinical correlation before
    any dose adjustment.

    eGFR < 60 meets the KDIGO 2024 threshold used here. `egfr=None` (test
    not done / unknown) never raises a flag.

    Returns {"egfr", "renal_function_status", "detail", "source"}.
    `renal_function_status` is REDUCED, NORMAL, or UNKNOWN.
    """
    if egfr is None:
        return {
            "egfr": None,
            "renal_function_status": "UNKNOWN",
            "detail": "eGFR not provided (test not done / unknown)",
            "source": KDIGO_SOURCE,
        }
    if egfr < EGFR_THRESHOLD:
        return {
            "egfr": egfr,
            "renal_function_status": "REDUCED",
            "detail": "Reduced eGFR; requires clinical correlation for renal "
                      f"dose adjustment (eGFR {egfr} mL/min/1.73m² is below the "
                      f"KDIGO 2024 threshold of {EGFR_THRESHOLD})",
            "source": KDIGO_SOURCE,
        }
    return {
        "egfr": egfr,
        "renal_function_status": "NORMAL",
        "detail": f"eGFR {egfr} mL/min/1.73m² is at or above the KDIGO 2024 "
                  f"threshold of {EGFR_THRESHOLD}",
        "source": KDIGO_SOURCE,
    }


def assess_hepatic_function(alt_ast: float = None) -> dict:
    """Flag an elevated-transaminase lab abnormality from an exact ALT/AST
    value (U/L) -- this is a lab reading, not a hepatic-impairment
    diagnosis; it requires clinical correlation.

    ALT/AST > 40 U/L (the standard upper limit of normal) flags the
    abnormality. `alt_ast=None` (test not done / unknown) never raises a flag.

    Returns {"alt_ast", "transaminase_status", "detail", "source"}.
    `transaminase_status` is ELEVATED, NORMAL, or UNKNOWN.
    """
    if alt_ast is None:
        return {
            "alt_ast": None,
            "transaminase_status": "UNKNOWN",
            "detail": "ALT/AST not provided (test not done / unknown)",
            "source": NFI_SOURCE,
        }
    if alt_ast > ALT_AST_THRESHOLD:
        return {
            "alt_ast": alt_ast,
            "transaminase_status": "ELEVATED",
            "detail": "Elevated transaminases; laboratory abnormality "
                      f"(ALT/AST {alt_ast} U/L exceeds the upper limit of normal "
                      f"of {ALT_AST_THRESHOLD} U/L) -- requires clinical "
                      "correlation, not an automatic hepatic-impairment diagnosis",
            "source": NFI_SOURCE,
        }
    return {
        "alt_ast": alt_ast,
        "transaminase_status": "NORMAL",
        "detail": f"ALT/AST {alt_ast} U/L is within normal limits "
                  f"(threshold: {ALT_AST_THRESHOLD} U/L)",
        "source": NFI_SOURCE,
    }


def assess_bleeding_risk_labs(platelets: float = None, pt_inr: float = None) -> dict:
    """Flag abnormal coagulation/CBC parameters from exact Platelets
    (x10^3/uL) and PT/INR (ratio) values -- relevant before starting an
    anticoagulant such as warfarin. These are lab readings, not a bleeding-
    risk diagnosis; they require clinical correlation. Platelets < 150 or
    PT/INR > 1.2 flags the abnormality; a value of `None` (test not done /
    unknown) never does.

    Returns {"platelets", "pt_inr", "coagulation_cbc_status", "detail",
    "flags", "source"}. `coagulation_cbc_status` is ABNORMAL, NORMAL, or
    UNKNOWN; `flags` lists the specific parameter(s) out of range.
    """
    flags = []
    if platelets is not None and platelets < PLATELETS_THRESHOLD:
        flags.append(
            f"Thrombocytopenia (platelets {platelets} x10³/µL, "
            f"below {PLATELETS_THRESHOLD})"
        )
    if pt_inr is not None and pt_inr > PT_INR_THRESHOLD:
        flags.append(f"Elevated PT/INR ({pt_inr}, above {PT_INR_THRESHOLD})")

    if flags:
        status = "ABNORMAL"
        detail = "Abnormal coagulation/CBC parameters; requires clinical correlation."
    elif platelets is None and pt_inr is None:
        status = "UNKNOWN"
        detail = "Coagulation/CBC parameters not provided (test not done / unknown)"
    else:
        status = "NORMAL"
        detail = "Coagulation/CBC parameters within normal limits."

    return {
        "platelets": platelets,
        "pt_inr": pt_inr,
        "coagulation_cbc_status": status,
        "detail": detail,
        "flags": flags,
        "source": "Routine Coagulation/CBC",
    }


def assess_age_weight_context(age: float = None, weight: float = None) -> dict:
    """Flag pediatric-age or low-body-weight dosing considerations per FDA
    guidance on pediatric and weight-based dosing.

    Returns {"age", "weight", "flags", "source"}.
    """
    flags = []
    if age is not None and age < _PEDIATRIC_AGE_YEARS:
        flags.append(f"Pediatric patient (age {age}); confirm weight-based dosing per FDA guidance")
    if weight is not None and weight < _LOW_WEIGHT_KG:
        flags.append(f"Low body weight ({weight} kg); confirm weight-based dose calculation")
    return {"age": age, "weight": weight, "flags": flags, "source": FDA_DOSING_SOURCE}


def calculate_gerontonet_score(
    *,
    gte4_comorbid_conditions: bool = False,
    heart_failure: bool = False,
    liver_disease: bool = False,
    renal_failure: bool = False,
    num_drugs: int = 0,
    previous_adr_history: bool = False,
) -> dict:
    """The actual, validated GerontoNet ADR Risk Score (Onder et al., Arch
    Intern Med 2010) -- a weighted point total, not a derived binary
    predictor-count heuristic.

    Point values:
        >= 4 comorbid conditions       +1
        Heart failure                  +1
        Liver disease                  +1
        Renal failure                  +1
        5-7 concurrent drugs (num_drugs) +1
        >= 8 concurrent drugs (num_drugs) +4 (supersedes the 5-7 band)
        Previous history of ADR        +2

    `total_score` ranges 0-10. `risk_category` is GERONTONET_RISK_HIGH
    ("High Risk") only when total_score >= GERONTONET_HIGH_RISK_THRESHOLD
    (4); otherwise GERONTONET_RISK_LOW ("Low Risk"). A single strong
    predictor (e.g. previous ADR history alone, worth 2 points) is
    deliberately *not* enough on its own to reach High Risk -- that is the
    validated score's own behavior, not an oversight.

    Returns {"total_score", "max_score", "risk_category", "breakdown", "source"}.
    `breakdown` maps each criterion to the points it actually contributed.
    """
    num_drugs = num_drugs or 0
    if num_drugs >= 8:
        drug_points = GERONTONET_DRUGS_8_PLUS_POINTS
    elif num_drugs >= 5:
        drug_points = GERONTONET_DRUGS_5_TO_7_POINTS
    else:
        drug_points = 0

    breakdown = {
        "gte4_comorbid_conditions": GERONTONET_COMORBIDITY_POINTS if gte4_comorbid_conditions else 0,
        "heart_failure": GERONTONET_HEART_FAILURE_POINTS if heart_failure else 0,
        "liver_disease": GERONTONET_LIVER_DISEASE_POINTS if liver_disease else 0,
        "renal_failure": GERONTONET_RENAL_FAILURE_POINTS if renal_failure else 0,
        "concurrent_drugs": drug_points,
        "previous_adr_history": GERONTONET_PREVIOUS_ADR_POINTS if previous_adr_history else 0,
    }
    total_score = sum(breakdown.values())
    risk_category = GERONTONET_RISK_HIGH if total_score >= GERONTONET_HIGH_RISK_THRESHOLD else GERONTONET_RISK_LOW

    return {
        "total_score": total_score,
        "max_score": GERONTONET_MAX_SCORE,
        "risk_category": risk_category,
        "breakdown": breakdown,
        "source": GERONTONET_SOURCE,
    }


def calculate_adr_risk(
    *,
    age: float = None,
    chronic_lung_disease: bool = False,
    presenting_respiratory_disorder: bool = False,
    presenting_bleeding_disorder: bool = False,
    presenting_gi_disorder: bool = False,
    syncope_on_admission: bool = False,
    antithrombotics: bool = False,
    diuretics: bool = False,
    raas_drugs: bool = False,
    num_drugs: int = 0,
    heart_failure: bool = False,
    liver_disease: bool = False,
    gte4_comorbid_conditions: bool = False,
    renal_failure: bool = False,
    previous_adr_history: bool = False,
    allergy_history: bool = False,
    family_history: bool = False,
) -> dict:
    """Baseline Adverse Drug Reaction (ADR) risk, from two predictor models
    plus a clinician-reported general clinical history -- entirely
    independent of any drug being requested or any genotype/phenotype result.

    ADATIP 9-Predictor Model (institutional, acute presentation; all 9
    predictors implemented):
        age (elderly at or above ELDERLY_AGE_THRESHOLD), chronic_lung_disease,
        presenting_respiratory_disorder, presenting_bleeding_disorder,
        presenting_gi_disorder, syncope_on_admission, antithrombotics,
        diuretics, raas_drugs. High if 2 or more predictors are present
        (an institutional heuristic -- no published point-weighted formula
        for this model was supplied).

    GerontoNet ADR Risk Score (chronic fragility and polypharmacy): the
    actual validated point total from calculate_gerontonet_score() --
    gte4_comorbid_conditions, heart_failure, liver_disease, renal_failure,
    num_drugs, previous_adr_history. High only at a total score
    of 4 or more (see calculate_gerontonet_score for the point values).

    General clinical history (clinician-reported): allergy_history and
    family_history, which together count as a secondary two-predictor group
    analogous to the ADATIP group above (no published weighting exists for
    these, so they use the same 2-of-2 heuristic as ADATIP).

    Returns "High Baseline ADR Risk" if ANY of the following hold:
        - the GerontoNet ADR Risk Score is High Risk (total score >= 4), or
        - 2 or more ADATIP predictors are present, or
        - both allergy_history and family_history are present.

    Returns {"high_baseline_adr_risk", "adr_risk_flag", "adatip_trigger_count",
    "gerontonet_score", "general_history_trigger_count", "reasons", "source"}.
    `adr_risk_flag` is the exact string persisted by storage.audit_logger and
    rendered in the UI -- ADR_RISK_HIGH or ADR_RISK_STANDARD. `gerontonet_score`
    is the full dict returned by calculate_gerontonet_score().
    """
    adatip_predictors = [
        age is not None and age >= ELDERLY_AGE_THRESHOLD,
        chronic_lung_disease, presenting_respiratory_disorder,
        presenting_bleeding_disorder, presenting_gi_disorder,
        syncope_on_admission, antithrombotics, diuretics, raas_drugs,
    ]
    adatip_count = sum(1 for p in adatip_predictors if p)

    gerontonet_score = calculate_gerontonet_score(
        gte4_comorbid_conditions=gte4_comorbid_conditions,
        heart_failure=heart_failure,
        liver_disease=liver_disease,
        renal_failure=renal_failure,
        num_drugs=num_drugs,
        previous_adr_history=previous_adr_history,
    )

    general_history_secondary_predictors = [allergy_history, family_history]
    general_history_secondary_count = sum(1 for p in general_history_secondary_predictors if p)

    reasons = []
    if gerontonet_score["risk_category"] == GERONTONET_RISK_HIGH:
        reasons.append(
            f"GerontoNet ADR Risk Score {gerontonet_score['total_score']}/"
            f"{gerontonet_score['max_score']} (High Risk; threshold "
            f"{GERONTONET_HIGH_RISK_THRESHOLD})"
        )
    if adatip_count >= MULTI_PREDICTOR_THRESHOLD:
        reasons.append(f"{adatip_count} ADATIP predictors present (threshold: {MULTI_PREDICTOR_THRESHOLD})")
    if general_history_secondary_count >= MULTI_PREDICTOR_THRESHOLD:
        reasons.append(
            f"{general_history_secondary_count} General Clinical History predictors "
            f"present (allergy and family history; threshold: {MULTI_PREDICTOR_THRESHOLD})"
        )

    high_risk = bool(reasons)

    return {
        "high_baseline_adr_risk": high_risk,
        "adr_risk_flag": ADR_RISK_HIGH if high_risk else ADR_RISK_STANDARD,
        "adatip_trigger_count": adatip_count,
        "gerontonet_score": gerontonet_score,
        "general_history_trigger_count": general_history_secondary_count,
        "reasons": reasons,
        "source": f"{ADATIP_SOURCE}; {GERONTONET_SOURCE}",
    }
