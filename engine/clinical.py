"""Objective clinical data assessment for the PRISM-AIIMS pre-test triage pipeline.

Assesses only routine, objective inputs a clinician already has on hand
*before* ordering any pharmacogenomic test -- Age, Weight, eGFR, ALT/AST,
Platelets, and PT/INR -- against exact, published numeric thresholds. Any
lab the clinician marks "Test Not Done / Unknown" is passed through as
`None` and never raises a risk flag -- absence of data is never treated as
evidence of abnormality.

Sources:
    - Renal function: KDIGO 2024 Clinical Practice Guideline for CKD
      (eGFR < 60 mL/min/1.73m^2 is the threshold for reduced renal function).
    - Hepatic function: CDSCO / National Formulary of India (NFI), used here
      for empirical dose-caution framing (ALT/AST > 40 U/L, the standard
      upper limit of normal, flags possible hepatic impairment).
    - Bleeding risk: routine Coagulation/CBC thresholds (platelets < 150
      x10^3/uL, PT/INR > 1.2) used before starting an anticoagulant.
    - Age/weight dosing context: FDA guidance on pediatric and weight-based
      dosing.
    - Baseline ADR risk (calculate_adr_risk): the ADATIP 9-Predictor Model,
      an institutional acute-presentation ADR risk model (all 9 predictors
      implemented), the published GerontoNet ADR risk score (Onder G, et al.
      "Development and validation of a score to assess risk of adverse drug
      reactions among in-hospital patients 65 years or older: the GerontoNet
      ADR risk score." Arch Intern Med. 2010), and a clinician-reported
      general clinical history (prior ADR, allergy, family history).
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

POLYPHARMACY_DRUG_THRESHOLD = 4
MULTI_PREDICTOR_THRESHOLD = 2

ADR_RISK_HIGH = "HIGH BASELINE ADR RISK"
ADR_RISK_STANDARD = "STANDARD"


def assess_renal_function(egfr: float = None) -> dict:
    """Classify renal risk from an exact eGFR value (mL/min/1.73m^2).

    eGFR < 60 meets the KDIGO 2024 threshold for reduced renal function.
    `egfr=None` (test not done / unknown) never raises risk.

    Returns {"egfr", "nephrotoxicity_risk", "detail", "source"}.
    """
    if egfr is None:
        return {
            "egfr": None,
            "nephrotoxicity_risk": "UNKNOWN",
            "detail": "eGFR not provided (test not done / unknown)",
            "source": KDIGO_SOURCE,
        }
    if egfr < EGFR_THRESHOLD:
        return {
            "egfr": egfr,
            "nephrotoxicity_risk": "HIGH",
            "detail": f"eGFR {egfr} mL/min/1.73m² is below the KDIGO 2024 "
                      f"threshold of {EGFR_THRESHOLD}; reduced renal function raises "
                      "nephrotoxicity risk independent of genotype",
            "source": KDIGO_SOURCE,
        }
    return {
        "egfr": egfr,
        "nephrotoxicity_risk": "LOW",
        "detail": f"eGFR {egfr} mL/min/1.73m² is at or above the KDIGO 2024 "
                  f"threshold of {EGFR_THRESHOLD}",
        "source": KDIGO_SOURCE,
    }


def assess_hepatic_function(alt_ast: float = None) -> dict:
    """Classify hepatic-impairment risk from an exact ALT/AST value (U/L),
    for empirical dosing caution per the National Formulary of India.

    ALT/AST > 40 U/L (the standard upper limit of normal) flags possible
    impairment. `alt_ast=None` (test not done / unknown) never raises risk.

    Returns {"alt_ast", "impairment_risk", "detail", "source"}.
    """
    if alt_ast is None:
        return {
            "alt_ast": None,
            "impairment_risk": "UNKNOWN",
            "detail": "ALT/AST not provided (test not done / unknown)",
            "source": NFI_SOURCE,
        }
    if alt_ast > ALT_AST_THRESHOLD:
        return {
            "alt_ast": alt_ast,
            "impairment_risk": "HIGH",
            "detail": f"ALT/AST {alt_ast} U/L exceeds the upper limit of normal "
                      f"({ALT_AST_THRESHOLD} U/L); empirical dose caution and closer "
                      "monitoring required per NFI, independent of genotype",
            "source": NFI_SOURCE,
        }
    return {
        "alt_ast": alt_ast,
        "impairment_risk": "LOW",
        "detail": f"ALT/AST {alt_ast} U/L is within normal limits "
                  f"(threshold: {ALT_AST_THRESHOLD} U/L)",
        "source": NFI_SOURCE,
    }


def assess_bleeding_risk_labs(platelets: float = None, pt_inr: float = None) -> dict:
    """Baseline bleeding-risk signal from exact Platelets (x10^3/uL) and
    PT/INR (ratio) values -- relevant before starting an anticoagulant such
    as warfarin. Platelets < 150 or PT/INR > 1.2 raises risk; a value of
    `None` (test not done / unknown) never does.

    Returns {"platelets", "pt_inr", "baseline_bleeding_risk", "flags", "source"}.
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
        risk = "HIGH"
    elif platelets is None and pt_inr is None:
        risk = "UNKNOWN"
    else:
        risk = "LOW"

    return {
        "platelets": platelets,
        "pt_inr": pt_inr,
        "baseline_bleeding_risk": risk,
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
    num_concurrent_drugs: int = 0,
    heart_failure: bool = False,
    liver_disease: bool = False,
    gt4_medical_conditions: bool = False,
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
        diuretics, raas_drugs.

    GerontoNet ADR risk score (chronic fragility and polypharmacy):
        num_concurrent_drugs, heart_failure, liver_disease,
        gt4_medical_conditions, renal_failure.

    General clinical history (clinician-reported):
        previous_adr_history (the strongest single predictor across either
        model), plus allergy_history and family_history, which together
        count as a secondary two-predictor group analogous to the ADATIP
        and GerontoNet groups below.

    Returns "High Baseline ADR Risk" if ANY of the following hold:
        - previous_adr_history is True (the strongest single predictor), or
        - num_concurrent_drugs > 4 (polypharmacy), or
        - 2 or more ADATIP predictors are present, or
        - 2 or more of the GerontoNet comorbidity predictors (heart_failure,
          liver_disease, gt4_medical_conditions, renal_failure) are present, or
        - both allergy_history and family_history are present.

    Returns {"high_baseline_adr_risk", "adr_risk_flag", "adatip_trigger_count",
    "gerontonet_trigger_count", "general_history_trigger_count", "reasons",
    "source"}. `adr_risk_flag` is the exact string persisted by
    storage.audit_logger and rendered in the UI -- ADR_RISK_HIGH or
    ADR_RISK_STANDARD.
    """
    adatip_predictors = [
        age is not None and age >= ELDERLY_AGE_THRESHOLD,
        chronic_lung_disease, presenting_respiratory_disorder,
        presenting_bleeding_disorder, presenting_gi_disorder,
        syncope_on_admission, antithrombotics, diuretics, raas_drugs,
    ]
    adatip_count = sum(1 for p in adatip_predictors if p)

    gerontonet_secondary_predictors = [heart_failure, liver_disease, gt4_medical_conditions, renal_failure]
    gerontonet_secondary_count = sum(1 for p in gerontonet_secondary_predictors if p)

    general_history_secondary_predictors = [allergy_history, family_history]
    general_history_secondary_count = sum(1 for p in general_history_secondary_predictors if p)

    num_concurrent_drugs = num_concurrent_drugs or 0
    polypharmacy = num_concurrent_drugs > POLYPHARMACY_DRUG_THRESHOLD

    reasons = []
    if previous_adr_history:
        reasons.append("Previous ADR history (strongest single predictor)")
    if polypharmacy:
        reasons.append(
            f"Polypharmacy: {num_concurrent_drugs} concurrent drugs "
            f"(> {POLYPHARMACY_DRUG_THRESHOLD})"
        )
    if adatip_count >= MULTI_PREDICTOR_THRESHOLD:
        reasons.append(f"{adatip_count} ADATIP predictors present (threshold: {MULTI_PREDICTOR_THRESHOLD})")
    if gerontonet_secondary_count >= MULTI_PREDICTOR_THRESHOLD:
        reasons.append(
            f"{gerontonet_secondary_count} GerontoNet predictors present "
            f"(threshold: {MULTI_PREDICTOR_THRESHOLD})"
        )
    if general_history_secondary_count >= MULTI_PREDICTOR_THRESHOLD:
        reasons.append(
            f"{general_history_secondary_count} General Clinical History predictors "
            f"present (allergy and family history; threshold: {MULTI_PREDICTOR_THRESHOLD})"
        )

    high_risk = bool(reasons)
    gerontonet_trigger_count = gerontonet_secondary_count + int(previous_adr_history) + int(polypharmacy)

    return {
        "high_baseline_adr_risk": high_risk,
        "adr_risk_flag": ADR_RISK_HIGH if high_risk else ADR_RISK_STANDARD,
        "adatip_trigger_count": adatip_count,
        "gerontonet_trigger_count": gerontonet_trigger_count,
        "general_history_trigger_count": general_history_secondary_count,
        "reasons": reasons,
        "source": f"{ADATIP_SOURCE}; {GERONTONET_SOURCE}",
    }
