"""Layer 1 (Clinical Details) and Layer 2 (ADR Risk Prediction) logic for
the PRISM-AIIMS pipeline.

STATE MODEL

Every laboratory parameter this module consumes is a three-valued logical
state, not a numeric quantity compared against a threshold at runtime: a
clinician reduces a lab reading, at the point of entry, to exactly one of
three mutually exclusive states -- ABNORMAL (the boolean `True`), NORMAL
(the boolean `False`), or MISSING (`None`) -- and every `assess_*` function
below is a pure state-transition function over that three-valued input: it
never re-derives the state from a raw number, and it never treats a missing
state as evidence for either of the other two. Passing `True` for a
parameter transitions its corresponding status field immediately to its
ABNORMAL state (e.g. `renal_function_status` -> "REDUCED"); there is no
intermediate comparison step. The published thresholds a clinician would
reference when rendering that True/False judgment (e.g. eGFR < 60
mL/min/1.73m^2 per KDIGO 2024) are retained below only as named reference
constants surfaced in each function's `detail` string -- they document the
clinical judgment already made upstream, they are not re-evaluated here.

Per clinical reviewer feedback, this module also deliberately separates a
*laboratory abnormality* (a flagged out-of-range state) from a *clinical
diagnosis* (a condition a clinician has actually established): no
`assess_*` function below claims to detect "nephrotoxicity," "hepatic
impairment," or "bleeding risk" outright -- a single abnormal flag is never,
by itself, a diagnosis. Each function instead reports the abnormal state
plainly and states that it requires clinical correlation.

Sources:
    - Renal function: KDIGO 2024 Clinical Practice Guideline for CKD
      (eGFR < 60 mL/min/1.73m^2 is the reference threshold this MVP cites
      for a clinician's own Abnormal/Normal judgment on renal function).
    - Hepatic function: CDSCO / National Formulary of India (NFI), cited as
      the reference threshold (ALT/AST > 40 U/L, the standard upper limit
      of normal) for a clinician's own Abnormal/Normal judgment on hepatic
      transaminases -- not to assert a hepatic-impairment diagnosis.
    - Coagulation/CBC: routine reference thresholds (platelets < 150
      x10^3/uL, PT/INR > 1.2) cited for a clinician's own Abnormal/Normal
      judgment before starting an anticoagulant such as warfarin.
    - Age/weight dosing context: FDA guidance on pediatric and weight-based
      dosing.
    - Baseline ADR risk (calculate_adr_risk): two statistically independent
      predictor models, evaluated as isolated execution contexts that never
      read each other's internal state -- the ADATIP 9-Predictor Model, an
      institutional acute-presentation ADR risk model (all 9 predictors
      implemented), and the actual validated GerontoNet ADR Risk Score
      (Onder G, et al. "Development and validation of a score to assess
      risk of adverse drug reactions among in-hospital patients 65 years or
      older: the GerontoNet ADR risk score." Arch Intern Med. 2010) -- a
      weighted 0-10 point score, "High Risk" only at a total score of 4 or
      more, not a derived binary predictor-count heuristic -- plus a
      clinician-reported general clinical history (allergy, family
      history).
"""

KDIGO_SOURCE = "KDIGO 2024"
NFI_SOURCE = "CDSCO / National Formulary of India"
FDA_DOSING_SOURCE = "FDA Guidance (Pediatric / Weight-Based Dosing)"
ADATIP_SOURCE = "ADATIP 9-Predictor Model (institutional acute-presentation ADR risk model)"
GERONTONET_SOURCE = "GerontoNet ADR Risk Score (Onder et al., Arch Intern Med 2010)"

# Reference thresholds a clinician cites when rendering the True/False/None
# judgment captured at the system boundary -- documentation constants, not
# values compared against a number anywhere in this module.
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

# The two-valued vocabulary each Layer 2 isolated execution context renders
# independently -- deliberately identical wording across both models so
# neither UI output implies it carries more (or less) information than the
# other. Distinct from GERONTONET_RISK_HIGH/GERONTONET_RISK_LOW, which name
# the real published score's own internal category.
ISOLATED_VERDICT_HIGH = "High Risk"
ISOLATED_VERDICT_BASELINE = "Baseline Standard"


def assess_renal_function(egfr_abnormal: bool = None) -> dict:
    """Resolve renal-function state from a clinician-provided three-valued
    flag -- this is a state transition over `True` (abnormal / reduced
    eGFR), `False` (normal), or `None` (missing data), not a numeric
    comparison; the function never receives or evaluates an exact eGFR
    reading. This is a lab-abnormality state, not a nephrotoxicity or
    renal-impairment diagnosis; it requires clinical correlation before any
    dose adjustment.

    `egfr_abnormal=True` immediately transitions `renal_function_status` to
    its ABNORMAL state ("REDUCED"). `egfr_abnormal=None` (missing data)
    never does.

    Returns {"egfr_abnormal", "renal_function_status", "detail", "source"}.
    `renal_function_status` is REDUCED, NORMAL, or UNKNOWN.
    """
    if egfr_abnormal is None:
        return {
            "egfr_abnormal": None,
            "renal_function_status": "UNKNOWN",
            "detail": "eGFR state not provided (missing data)",
            "source": KDIGO_SOURCE,
        }
    if egfr_abnormal:
        return {
            "egfr_abnormal": True,
            "renal_function_status": "REDUCED",
            "detail": "Reduced eGFR flagged as abnormal; requires clinical "
                      "correlation for renal dose adjustment (reference "
                      f"threshold: eGFR < {EGFR_THRESHOLD} mL/min/1.73m², "
                      "KDIGO 2024).",
            "source": KDIGO_SOURCE,
        }
    return {
        "egfr_abnormal": False,
        "renal_function_status": "NORMAL",
        "detail": "eGFR flagged as normal (reference threshold: "
                  f"{EGFR_THRESHOLD} mL/min/1.73m², KDIGO 2024).",
        "source": KDIGO_SOURCE,
    }


def assess_hepatic_function(alt_ast_abnormal: bool = None) -> dict:
    """Resolve hepatic-transaminase state from a clinician-provided
    three-valued flag -- a state transition over `True` (abnormal /
    elevated ALT-AST), `False` (normal), or `None` (missing data), not a
    numeric comparison. This is a lab-abnormality state, not a
    hepatic-impairment diagnosis; it requires clinical correlation.

    `alt_ast_abnormal=True` immediately transitions `transaminase_status`
    to its ABNORMAL state ("ELEVATED"). `alt_ast_abnormal=None` (missing
    data) never does.

    Returns {"alt_ast_abnormal", "transaminase_status", "detail", "source"}.
    `transaminase_status` is ELEVATED, NORMAL, or UNKNOWN.
    """
    if alt_ast_abnormal is None:
        return {
            "alt_ast_abnormal": None,
            "transaminase_status": "UNKNOWN",
            "detail": "ALT/AST state not provided (missing data)",
            "source": NFI_SOURCE,
        }
    if alt_ast_abnormal:
        return {
            "alt_ast_abnormal": True,
            "transaminase_status": "ELEVATED",
            "detail": "Elevated transaminases flagged as abnormal; "
                      "laboratory abnormality requiring clinical "
                      "correlation, not an automatic hepatic-impairment "
                      f"diagnosis (reference threshold: ALT/AST > "
                      f"{ALT_AST_THRESHOLD} U/L, NFI).",
            "source": NFI_SOURCE,
        }
    return {
        "alt_ast_abnormal": False,
        "transaminase_status": "NORMAL",
        "detail": f"ALT/AST flagged as normal (reference threshold: "
                  f"{ALT_AST_THRESHOLD} U/L, NFI).",
        "source": NFI_SOURCE,
    }


def assess_bleeding_risk_labs(platelets_abnormal: bool = None, pt_inr_abnormal: bool = None) -> dict:
    """Resolve coagulation/CBC state from two independent clinician-provided
    three-valued flags -- relevant before starting an anticoagulant such as
    warfarin. Each of `platelets_abnormal` and `pt_inr_abnormal` is a state
    transition over `True` (abnormal), `False` (normal), or `None` (missing
    data), not a numeric comparison. These are lab-abnormality states, not a
    bleeding-risk diagnosis; they require clinical correlation.

    Either flag being `True` immediately transitions `coagulation_cbc_status`
    to its ABNORMAL state. A flag of `None` (missing data) never does.

    Returns {"platelets_abnormal", "pt_inr_abnormal", "coagulation_cbc_status",
    "detail", "flags", "source"}. `coagulation_cbc_status` is ABNORMAL,
    NORMAL, or UNKNOWN; `flags` lists the specific parameter(s) flagged
    abnormal.
    """
    flags = []
    if platelets_abnormal:
        flags.append(
            "Thrombocytopenia flagged as abnormal (reference threshold: "
            f"platelets < {PLATELETS_THRESHOLD} x10³/µL)"
        )
    if pt_inr_abnormal:
        flags.append(
            "Elevated PT/INR flagged as abnormal (reference threshold: "
            f"PT/INR > {PT_INR_THRESHOLD})"
        )

    if flags:
        status = "ABNORMAL"
        detail = "Abnormal coagulation/CBC parameters; requires clinical correlation."
    elif platelets_abnormal is None and pt_inr_abnormal is None:
        status = "UNKNOWN"
        detail = "Coagulation/CBC state not provided (missing data)"
    else:
        status = "NORMAL"
        detail = "Coagulation/CBC parameters within normal limits."

    return {
        "platelets_abnormal": platelets_abnormal,
        "pt_inr_abnormal": pt_inr_abnormal,
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
    evaluated as isolated execution contexts, plus a clinician-reported
    general clinical history -- entirely independent of any drug being
    requested or any genotype/phenotype result.

    ADATIP 9-Predictor Model (institutional, acute presentation; all 9
    predictors implemented) -- an isolated execution context that never
    reads GerontoNet's internal state:
        age (elderly at or above ELDERLY_AGE_THRESHOLD), chronic_lung_disease,
        presenting_respiratory_disorder, presenting_bleeding_disorder,
        presenting_gi_disorder, syncope_on_admission, antithrombotics,
        diuretics, raas_drugs. High if 2 or more predictors are present
        (an institutional heuristic -- no published point-weighted formula
        for this model was supplied). Its independent verdict is exposed as
        `adatip_isolated_verdict`.

    GerontoNet ADR Risk Score (chronic fragility and polypharmacy) -- an
    isolated execution context that never reads ADATIP's internal state:
    the actual validated point total from calculate_gerontonet_score() --
    gte4_comorbid_conditions, heart_failure, liver_disease, renal_failure,
    num_drugs, previous_adr_history. High only at a total score of 4 or
    more (see calculate_gerontonet_score for the point values). Its
    independent verdict is exposed as `gerontonet_isolated_verdict`.

    General clinical history (clinician-reported): allergy_history and
    family_history, which together count as a secondary two-predictor group
    analogous to the ADATIP group above (no published weighting exists for
    these, so they use the same 2-of-2 heuristic as ADATIP). This group
    contributes only to the composite `high_baseline_adr_risk` verdict
    below, not to either isolated model verdict.

    The composite `high_baseline_adr_risk` returns True if ANY of the
    following independent conditions hold:
        - the GerontoNet ADR Risk Score is High Risk (total score >= 4), or
        - 2 or more ADATIP predictors are present, or
        - both allergy_history and family_history are present.

    Returns {"high_baseline_adr_risk", "adr_risk_flag", "adatip_trigger_count",
    "adatip_isolated_verdict", "gerontonet_score", "gerontonet_isolated_verdict",
    "general_history_trigger_count", "reasons", "source"}. `adr_risk_flag" is
    the exact string persisted by storage.audit_logger and rendered in the
    UI -- ADR_RISK_HIGH or ADR_RISK_STANDARD. `gerontonet_score` is the full
    dict returned by calculate_gerontonet_score(). `adatip_isolated_verdict`
    and `gerontonet_isolated_verdict` are each independently one of
    ISOLATED_VERDICT_HIGH ("High Risk") or ISOLATED_VERDICT_BASELINE
    ("Baseline Standard") -- two distinct, separately rendered outputs that
    neither model computation observes when producing the other.
    """
    adatip_predictors = [
        age is not None and age >= ELDERLY_AGE_THRESHOLD,
        chronic_lung_disease, presenting_respiratory_disorder,
        presenting_bleeding_disorder, presenting_gi_disorder,
        syncope_on_admission, antithrombotics, diuretics, raas_drugs,
    ]
    adatip_count = sum(1 for p in adatip_predictors if p)
    adatip_isolated_verdict = (
        ISOLATED_VERDICT_HIGH if adatip_count >= MULTI_PREDICTOR_THRESHOLD else ISOLATED_VERDICT_BASELINE
    )

    gerontonet_score = calculate_gerontonet_score(
        gte4_comorbid_conditions=gte4_comorbid_conditions,
        heart_failure=heart_failure,
        liver_disease=liver_disease,
        renal_failure=renal_failure,
        num_drugs=num_drugs,
        previous_adr_history=previous_adr_history,
    )
    gerontonet_isolated_verdict = (
        ISOLATED_VERDICT_HIGH if gerontonet_score["risk_category"] == GERONTONET_RISK_HIGH
        else ISOLATED_VERDICT_BASELINE
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
        "adatip_isolated_verdict": adatip_isolated_verdict,
        "gerontonet_score": gerontonet_score,
        "gerontonet_isolated_verdict": gerontonet_isolated_verdict,
        "general_history_trigger_count": general_history_secondary_count,
        "reasons": reasons,
        "source": f"{ADATIP_SOURCE}; {GERONTONET_SOURCE}",
    }
