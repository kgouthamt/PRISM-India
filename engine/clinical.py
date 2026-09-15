"""Tier 1 of the PRISM-India pre-test triage pipeline: objective clinical data.

Assesses only routine, objective inputs a clinician already has on hand
*before* ordering any pharmacogenomic test -- Age, Weight, LFT, RFT/eGFR,
CBC/platelets, and PT/INR/aPTT -- against published reference thresholds.
Subjective inputs (patient-reported history, e.g. a prior ADR or a prior
treatment failure) are deliberately out of scope: this tier answers "does
objective, routine clinical data already explain the risk, or point to a
dose adjustment, without needing genetic testing?"

LFT, RFT/eGFR, and CBC/platelets are collected as coarse Normal / Abnormal /
Unknown categories (not raw lab values), so this tier deliberately does not
synthesize a precise severity grade (e.g. a specific KDIGO G-stage) it has no
numeric data to support -- an "Abnormal" flag names the guideline that
governs further work-up instead.

Sources:
    - Renal function: KDIGO 2024 Clinical Practice Guideline for CKD.
    - Hepatic function: CDSCO / National Formulary of India (NFI), used here
      for empirical dose-caution framing rather than a formal Child-Pugh
      score (which needs albumin/ascites/encephalopathy data this prototype
      does not collect).
    - Age/weight dosing context: FDA guidance on pediatric and weight-based
      dosing.
"""

KDIGO_SOURCE = "KDIGO 2024"
NFI_SOURCE = "CDSCO / National Formulary of India"
FDA_DOSING_SOURCE = "FDA Guidance (Pediatric / Weight-Based Dosing)"

_VALID_CATEGORIES = {"Normal", "Abnormal", "Unknown"}

_PEDIATRIC_AGE_YEARS = 18
_LOW_WEIGHT_KG = 40.0
_ABNORMAL_PT_INR_APTT_THRESHOLD = 1.3


def _normalize_category(value: str) -> str:
    """Coerce free-form input to exactly 'Normal', 'Abnormal', or 'Unknown'."""
    candidate = (value or "Unknown").strip().capitalize()
    return candidate if candidate in _VALID_CATEGORIES else "Unknown"


def assess_renal_function(rft_egfr: str = "Unknown") -> dict:
    """Classify renal risk from a coarse RFT/eGFR category.

    Returns {"rft_egfr", "nephrotoxicity_risk", "detail", "source"}.
    """
    category = _normalize_category(rft_egfr)
    detail = {
        "Normal": "RFT/eGFR within normal limits",
        "Abnormal": "Abnormal RFT/eGFR; obtain a precise eGFR for KDIGO 2024 "
                    "staging and adjust nephrotoxic drug dosing accordingly",
        "Unknown": "RFT/eGFR not provided",
    }[category]
    risk = {"Normal": "LOW", "Abnormal": "HIGH", "Unknown": "UNKNOWN"}[category]
    return {"rft_egfr": category, "nephrotoxicity_risk": risk, "detail": detail, "source": KDIGO_SOURCE}


def assess_hepatic_function(lft: str = "Unknown") -> dict:
    """Classify hepatic-impairment risk from a coarse LFT category, for
    empirical dosing caution per the National Formulary of India.

    Returns {"lft", "impairment_risk", "detail", "source"}.
    """
    category = _normalize_category(lft)
    detail = {
        "Normal": "LFT within normal limits",
        "Abnormal": "Abnormal LFT; empirical dose caution and closer "
                    "monitoring required per NFI, independent of genotype",
        "Unknown": "LFT not provided",
    }[category]
    risk = {"Normal": "LOW", "Abnormal": "HIGH", "Unknown": "UNKNOWN"}[category]
    return {"lft": category, "impairment_risk": risk, "detail": detail, "source": NFI_SOURCE}


def _normalize_pt_inr_aptt(pt_inr_aptt) -> str:
    """Accept either a Normal/Abnormal/Unknown category or a numeric INR-like
    value and resolve both to a single 'Normal' | 'Abnormal' | 'Unknown'.
    """
    if isinstance(pt_inr_aptt, str):
        candidate = pt_inr_aptt.strip().capitalize()
        if candidate in _VALID_CATEGORIES:
            return candidate
    try:
        value = float(pt_inr_aptt)
    except (TypeError, ValueError):
        return "Unknown"
    return "Abnormal" if value > _ABNORMAL_PT_INR_APTT_THRESHOLD else "Normal"


def assess_bleeding_risk_labs(cbc_platelets: str = "Unknown", pt_inr_aptt=None) -> dict:
    """Baseline bleeding-risk signal from CBC/platelets (Normal/Abnormal/
    Unknown) and PT/INR/aPTT (Normal/Abnormal/Unknown, or a raw numeric
    INR-like value) -- relevant before starting an anticoagulant such as
    warfarin. Only an explicit "Abnormal" result raises risk; "Unknown"
    never does, since there is nothing to flag.

    Returns {"cbc_platelets", "pt_inr_aptt", "baseline_bleeding_risk", "flags", "source"}.
    """
    cbc_category = _normalize_category(cbc_platelets)
    pt_category = _normalize_pt_inr_aptt(pt_inr_aptt)

    flags = []
    if cbc_category == "Abnormal":
        flags.append("Abnormal CBC/platelets (possible thrombocytopenia or hematologic abnormality)")
    if pt_category == "Abnormal":
        flags.append("Abnormal PT/INR/aPTT (elevated baseline bleeding/coagulation risk)")

    risk = "HIGH" if flags else "LOW"
    return {
        "cbc_platelets": cbc_category,
        "pt_inr_aptt": pt_category,
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
