"""Tier 1 of the PRISM-India pre-test triage pipeline: objective clinical data.

Assesses only routine, objective inputs a clinician already has on hand
*before* ordering any pharmacogenomic test -- Age, Weight, eGFR, ALT/AST,
Platelets, and PT/INR -- against exact, published numeric thresholds.
Subjective inputs (patient-reported history, e.g. a prior ADR or a prior
treatment failure) are deliberately out of scope. Any lab the clinician
marks "Test Not Done / Unknown" is passed through as `None` and never
raises a risk flag -- absence of data is never treated as evidence of
abnormality.

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
"""

KDIGO_SOURCE = "KDIGO 2024"
NFI_SOURCE = "CDSCO / National Formulary of India"
FDA_DOSING_SOURCE = "FDA Guidance (Pediatric / Weight-Based Dosing)"

EGFR_THRESHOLD = 60.0
ALT_AST_THRESHOLD = 40.0
PLATELETS_THRESHOLD = 150.0
PT_INR_THRESHOLD = 1.2

_PEDIATRIC_AGE_YEARS = 18
_LOW_WEIGHT_KG = 40.0


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
