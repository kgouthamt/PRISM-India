"""Tier 1 of the PRISM-India pre-test triage pipeline: routine clinical labs.

Assesses standard Liver Function Tests (LFT), Renal Function Tests (RFT), and
Complete Blood Count / Coagulation values -- labs a clinician already has on
hand *before* ordering any pharmacogenomic test -- against published
reference thresholds. This tier answers "does routine clinical data already
explain the risk, or point to a dose adjustment, without needing genetic
testing?"

Sources:
    - Renal function staging: KDIGO 2024 Clinical Practice Guideline for CKD.
    - Hepatic impairment framing: CDSCO / National Formulary of India (NFI),
      used here for empirical dose-caution guidance rather than a formal
      Child-Pugh score (which needs albumin/ascites/encephalopathy data this
      prototype does not collect).
"""

KDIGO_SOURCE = "KDIGO 2024"
NFI_SOURCE = "CDSCO / National Formulary of India"

# (eGFR lower bound, stage, category, nephrotoxicity_risk) per KDIGO 2024.
_KDIGO_EGFR_STAGES = [
    (90, "G1", "Normal or high", "LOW"),
    (60, "G2", "Mildly decreased", "LOW"),
    (45, "G3a", "Mildly to moderately decreased", "MODERATE"),
    (30, "G3b", "Moderately to severely decreased", "HIGH"),
    (15, "G4", "Severely decreased", "HIGH"),
    (0, "G5", "Kidney failure", "HIGH"),
]

_ALT_ULN = 40.0
_AST_ULN = 40.0
_BILIRUBIN_ULN = 1.2


def assess_renal_function(egfr: float = None) -> dict:
    """Classify renal function per KDIGO 2024 eGFR staging (mL/min/1.73m^2).

    Returns {"stage", "category", "nephrotoxicity_risk", "source"}.
    """
    if egfr is None:
        return {
            "stage": None,
            "category": "Not provided",
            "nephrotoxicity_risk": "UNKNOWN",
            "source": KDIGO_SOURCE,
        }
    for threshold, stage, category, risk in _KDIGO_EGFR_STAGES:
        if egfr >= threshold:
            return {"stage": stage, "category": category, "nephrotoxicity_risk": risk, "source": KDIGO_SOURCE}
    return {"stage": "G5", "category": "Kidney failure", "nephrotoxicity_risk": "HIGH", "source": KDIGO_SOURCE}


def assess_hepatic_function(alt: float = None, ast: float = None, total_bilirubin: float = None) -> dict:
    """Flag hepatic impairment severity from routine LFTs (ALT/AST in U/L,
    bilirubin in mg/dL), for empirical dosing caution per the National
    Formulary of India.

    Returns {"impairment", "detail", "source"}.
    """
    if alt is None or ast is None or total_bilirubin is None:
        return {"impairment": "UNKNOWN", "detail": "Incomplete LFT panel", "source": NFI_SOURCE}

    transaminase_ratio = max(alt / _ALT_ULN, ast / _AST_ULN)
    bilirubin_ratio = total_bilirubin / _BILIRUBIN_ULN

    if bilirubin_ratio >= 2 or transaminase_ratio >= 5:
        impairment = "SEVERE"
    elif bilirubin_ratio >= 1.5 or transaminase_ratio >= 3:
        impairment = "MODERATE"
    elif bilirubin_ratio > 1 or transaminase_ratio > 1:
        impairment = "MILD"
    else:
        impairment = "NONE"

    detail = {
        "NONE": "LFTs within normal limits",
        "MILD": "Mild transaminase/bilirubin elevation; empirical dose caution per NFI",
        "MODERATE": "Moderate hepatic impairment; consider empirical dose reduction per NFI",
        "SEVERE": "Severe hepatic impairment; avoid or substantially reduce dose per NFI",
    }[impairment]

    return {"impairment": impairment, "detail": detail, "source": NFI_SOURCE}


def assess_bleeding_risk_labs(inr: float = None, platelets: float = None, hemoglobin: float = None) -> dict:
    """Baseline bleeding-risk signal from coagulation/CBC (INR unitless,
    platelets in x10^3/uL, hemoglobin in g/dL) -- relevant before starting an
    anticoagulant such as warfarin.

    Returns {"baseline_bleeding_risk", "flags", "source"}.
    """
    flags = []
    if inr is not None and inr > 1.3:
        flags.append(f"Elevated baseline INR ({inr})")
    if platelets is not None and platelets < 100:
        flags.append(f"Thrombocytopenia (platelets {platelets} x10^3/uL)")
    if hemoglobin is not None and hemoglobin < 10:
        flags.append(f"Anemia (hemoglobin {hemoglobin} g/dL)")

    risk = "HIGH" if flags else "LOW"
    return {"baseline_bleeding_risk": risk, "flags": flags, "source": "Routine Coagulation/CBC"}
