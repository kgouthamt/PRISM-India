"""Layer 1 (Clinical Details) and Layer 2 (ADR Risk Prediction) logic for
the PRISM-AIIMS pipeline.

STATE MODEL

Every laboratory parameter this module consumes is ingested as raw text,
type-cast to a floating-point value, and then reduced to one of three
mutually exclusive states -- ABNORMAL (`True`), NORMAL (`False`), or
MISSING (`None`) -- by evaluating that value against a named conditional
threshold. This is a two-stage pipeline, and the two stages are
deliberately kept as separate functions:

    1. Text parsing (`parse_lab_value`): a string-to-float type cast with
       explicit exception handling. The canonical missing-data tokens --
       an empty string, "none", "n/a", or "na" (all case-insensitive,
       leading/trailing whitespace stripped) -- type-cast to the `None`
       sentinel by definition, not by a failed cast. Any other token that
       fails `float(...)` (raises `ValueError`) is treated as unparseable:
       the function returns `None` for the value and a human-readable
       message for the caller to surface, rather than letting the
       exception propagate up through the component tree.
    2. Threshold evaluation (`assess_renal_function`, `assess_hepatic_
       function`, `assess_bleeding_risk_labs`, and the `is_*_abnormal`
       predicates they are built from): a pure conditional comparison of
       an already-parsed float (or `None`) against a named numeric
       threshold. `None` never satisfies any conditional threshold, so a
       missing reading can never be evaluated as abnormal.

Passing a value that satisfies a parameter's own conditional threshold
transitions its corresponding status field immediately to its ABNORMAL
state (e.g. `renal_function_status` -> "REDUCED"); there is no additional
indirection between the threshold comparison and the returned state.

Per clinical reviewer feedback, this module also deliberately separates a
*laboratory abnormality* (a flagged out-of-range value) from a *clinical
diagnosis* (a condition a clinician has actually established): no
`assess_*` function below claims to detect "nephrotoxicity," "hepatic
impairment," or "bleeding risk" outright -- a single abnormal flag is never,
by itself, a diagnosis. Each function instead reports the abnormal state
plainly and states that it requires clinical correlation.

Sources:
    - Renal function: KDIGO 2024 Clinical Practice Guideline for CKD
      (eGFR < 60 mL/min/1.73m^2 is this MVP's conditional threshold for
      flagging renal function abnormal).
    - Hepatic function: CDSCO / National Formulary of India (NFI): ALT/AST
      > 40 U/L (the standard upper limit of normal) is this MVP's
      conditional threshold for flagging hepatic transaminases abnormal --
      not for asserting a hepatic-impairment diagnosis.
    - Coagulation/CBC: routine conditional thresholds (platelets < 150
      x10^9/L, PT/INR > 1.2) evaluated before starting an anticoagulant
      such as warfarin.
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

# Conditional thresholds evaluated directly against a parsed numeric lab
# value -- the sole source of truth for each parameter's Abnormal/Normal
# state (see the module docstring's two-stage state model).
EGFR_THRESHOLD = 60.0
ALT_AST_THRESHOLD = 40.0
PLATELETS_THRESHOLD = 150.0
PT_INR_THRESHOLD = 1.2

# Text tokens that type-cast to the None sentinel (missing data) by
# definition, rather than by a failed float() cast. Matched case-
# insensitively after stripping leading/trailing whitespace.
_MISSING_DATA_TOKENS = frozenset({"", "none", "n/a", "na"})

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


def parse_lab_value(raw_text) -> tuple:
    """Type-cast a raw text-entry field into a float, with explicit
    exception handling around the string-to-float conversion -- the sole
    ingestion point every Layer 1 numeric lab field passes through before
    any conditional threshold is evaluated.

    The canonical missing-data tokens -- an empty string, "none", "n/a",
    or "na" (case-insensitive, surrounding whitespace stripped) -- type-
    cast to the `None` sentinel directly; this is a definitional mapping,
    not a caught exception. Any other token is passed to `float(...)`
    inside a `try`/`except ValueError` block: on success the parsed float
    is returned; on failure -- the token is not a valid float literal --
    the function returns `None` for the value (a parameter this module
    cannot safely evaluate against a numeric threshold is treated as
    missing, never guessed at) plus a human-readable message the caller
    may surface, rather than letting `ValueError` propagate. `raw_text`
    being `None` itself (not a string at all) is handled the same way,
    with no `TypeError` raised.

    Returns (value, error): `value` is a `float` or `None`; `error` is
    `None` on a clean parse (including a clean missing-data-token parse)
    or a message string when the input was neither a missing-data token
    nor a valid float literal.
    """
    if raw_text is None:
        return None, None
    normalized = str(raw_text).strip()
    if normalized.lower() in _MISSING_DATA_TOKENS:
        return None, None
    try:
        return float(normalized), None
    except ValueError:
        return None, f"'{raw_text}' is not a recognized numeric value; treated as missing data."


def is_egfr_abnormal(egfr: float = None) -> bool:
    """Conditional threshold: eGFR < EGFR_THRESHOLD (KDIGO 2024). `None`
    never satisfies this condition."""
    return egfr is not None and egfr < EGFR_THRESHOLD


def is_alt_ast_abnormal(alt_ast: float = None) -> bool:
    """Conditional threshold: ALT/AST > ALT_AST_THRESHOLD (NFI). `None`
    never satisfies this condition."""
    return alt_ast is not None and alt_ast > ALT_AST_THRESHOLD


def is_platelets_abnormal(platelets: float = None) -> bool:
    """Conditional threshold: platelets < PLATELETS_THRESHOLD. `None`
    never satisfies this condition."""
    return platelets is not None and platelets < PLATELETS_THRESHOLD


def is_pt_inr_abnormal(pt_inr: float = None) -> bool:
    """Conditional threshold: PT/INR > PT_INR_THRESHOLD. `None` never
    satisfies this condition."""
    return pt_inr is not None and pt_inr > PT_INR_THRESHOLD


def assess_renal_function(egfr: float = None) -> dict:
    """Resolve renal-function state from an already-parsed eGFR value (see
    `parse_lab_value` for the text-to-float ingestion stage) by evaluating
    `is_egfr_abnormal`. This is a lab-abnormality state, not a
    nephrotoxicity or renal-impairment diagnosis; it requires clinical
    correlation before any dose adjustment.

    `egfr` satisfying its conditional threshold immediately transitions
    `renal_function_status` to its ABNORMAL state ("REDUCED"). `egfr=None`
    (missing data) never does.

    Returns {"egfr", "renal_function_status", "detail", "source"}.
    `renal_function_status` is REDUCED, NORMAL, or UNKNOWN.
    """
    if egfr is None:
        return {
            "egfr": None,
            "renal_function_status": "UNKNOWN",
            "detail": "eGFR not provided (missing data)",
            "source": KDIGO_SOURCE,
        }
    if is_egfr_abnormal(egfr):
        return {
            "egfr": egfr,
            "renal_function_status": "REDUCED",
            "detail": f"Reduced eGFR ({egfr} mL/min/1.73m²); requires "
                      "clinical correlation for renal dose adjustment "
                      f"(KDIGO 2024 conditional threshold: eGFR < "
                      f"{EGFR_THRESHOLD}).",
            "source": KDIGO_SOURCE,
        }
    return {
        "egfr": egfr,
        "renal_function_status": "NORMAL",
        "detail": f"eGFR ({egfr} mL/min/1.73m²) is at or above the KDIGO "
                  f"2024 conditional threshold of {EGFR_THRESHOLD}.",
        "source": KDIGO_SOURCE,
    }


def assess_hepatic_function(alt_ast: float = None) -> dict:
    """Resolve hepatic-transaminase state from an already-parsed ALT/AST
    value (see `parse_lab_value` for the text-to-float ingestion stage) by
    evaluating `is_alt_ast_abnormal`. This is a lab-abnormality state, not
    a hepatic-impairment diagnosis; it requires clinical correlation.

    `alt_ast` satisfying its conditional threshold immediately transitions
    `transaminase_status` to its ABNORMAL state ("ELEVATED"). `alt_ast=
    None` (missing data) never does.

    Returns {"alt_ast", "transaminase_status", "detail", "source"}.
    `transaminase_status` is ELEVATED, NORMAL, or UNKNOWN.
    """
    if alt_ast is None:
        return {
            "alt_ast": None,
            "transaminase_status": "UNKNOWN",
            "detail": "ALT/AST not provided (missing data)",
            "source": NFI_SOURCE,
        }
    if is_alt_ast_abnormal(alt_ast):
        return {
            "alt_ast": alt_ast,
            "transaminase_status": "ELEVATED",
            "detail": f"Elevated transaminases (ALT/AST {alt_ast} U/L); "
                      "laboratory abnormality requiring clinical "
                      "correlation, not an automatic hepatic-impairment "
                      f"diagnosis (NFI conditional threshold: ALT/AST > "
                      f"{ALT_AST_THRESHOLD} U/L).",
            "source": NFI_SOURCE,
        }
    return {
        "alt_ast": alt_ast,
        "transaminase_status": "NORMAL",
        "detail": f"ALT/AST ({alt_ast} U/L) is within the NFI conditional "
                  f"threshold of {ALT_AST_THRESHOLD} U/L.",
        "source": NFI_SOURCE,
    }


def assess_bleeding_risk_labs(platelets: float = None, pt_inr: float = None) -> dict:
    """Resolve coagulation/CBC state from two independent already-parsed
    values (see `parse_lab_value` for the text-to-float ingestion stage)
    by evaluating `is_platelets_abnormal` and `is_pt_inr_abnormal` --
    relevant before starting an anticoagulant such as warfarin. These are
    lab-abnormality states, not a bleeding-risk diagnosis; they require
    clinical correlation.

    Either value satisfying its own conditional threshold immediately
    transitions `coagulation_cbc_status` to its ABNORMAL state. A value of
    `None` (missing data) never does.

    Returns {"platelets", "pt_inr", "coagulation_cbc_status", "detail",
    "flags", "source"}. `coagulation_cbc_status` is ABNORMAL, NORMAL, or
    UNKNOWN; `flags` lists the specific parameter(s) that satisfied their
    conditional threshold.
    """
    flags = []
    if is_platelets_abnormal(platelets):
        flags.append(
            f"Thrombocytopenia (platelets {platelets} x10⁹/L, below the "
            f"conditional threshold of {PLATELETS_THRESHOLD})"
        )
    if is_pt_inr_abnormal(pt_inr):
        flags.append(
            f"Elevated PT/INR ({pt_inr}, above the conditional threshold "
            f"of {PT_INR_THRESHOLD})"
        )

    if flags:
        status = "ABNORMAL"
        detail = "Abnormal coagulation/CBC parameters; requires clinical correlation."
    elif platelets is None and pt_inr is None:
        status = "UNKNOWN"
        detail = "Coagulation/CBC parameters not provided (missing data)"
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
