"""End-to-end integration tests for the PRISM-AIIMS 3-layer pipeline.

This is PRISM-AIIMS's stability suite: it exercises
engine.clinical.calculate_adr_risk() (Layer 2: Clinical Risk Assessment) and
engine.triage.triage_pgx_actionability() (Layer 3: PGx Testing-Priority
Triage) together, exactly the way app.py wires them, across a set of
extreme / edge-case patient profiles -- looking for TypeError, KeyError, or
state-routing bugs, and asserting the integrated decision-matrix
architecture: Testing Priority = f(PGx Actionability, Patient-Specific
Clinical Context). Baseline ADR risk (Layer 2) is an orthogonal covariate
that must never, by itself, transition the priority state -- only a
pathway-intersecting clinical context (a severe DDI, or an extreme lab
value tied to the drug's own mechanism) may do that.

Run with:
    pytest tests/test_final_integration.py -v
"""

from engine.clinical import (
    ADR_RISK_HIGH,
    ADR_RISK_STANDARD,
    GERONTONET_RISK_HIGH,
    GERONTONET_RISK_LOW,
    calculate_adr_risk,
)
from engine.triage import TRIAGE_CONSIDER, TRIAGE_HIGH, TRIAGE_LOW, triage_pgx_actionability


def test_case_1_healthy_baseline_defaults_to_consider():
    """A healthy 25-year-old, normal labs, no meds, prescribed Warfarin.

    Nothing here should trip any risk model -- Layer 2 must report Standard
    risk with a GerontoNet score of exactly 0, and Layer 3 must land on the
    routine-monitoring default, CONSIDER, not HIGH PRIORITY or LOW PRIORITY.
    """
    adr = calculate_adr_risk(age=25)
    assert adr["high_baseline_adr_risk"] is False
    assert adr["adr_risk_flag"] == ADR_RISK_STANDARD
    assert adr["gerontonet_score"]["total_score"] == 0
    assert adr["gerontonet_score"]["risk_category"] == GERONTONET_RISK_LOW

    triage = triage_pgx_actionability(
        "Warfarin", [], age=25, weight=70.0,
        platelets=250.0, pt_inr=1.0,
        high_baseline_adr_risk=adr["high_baseline_adr_risk"],
    )
    assert triage["triage"] == TRIAGE_CONSIDER


def test_case_2_gerontonet_high_score_does_not_independently_escalate_warfarin():
    """An 85-year-old on 8 concurrent medications (+4 points) with a
    previous ADR (+2 points) prescribed Warfarin, with entirely normal
    labs and no drug-drug interaction.

    8 concurrent drugs and a previous ADR together score exactly 6/10 on
    the real GerontoNet math (>=8 drugs is +4, not a per-drug increment;
    previous ADR is flat +2) -- comfortably over the High Risk threshold of
    4. Per the integrated decision-matrix architecture, this Layer 2
    covariate is orthogonal to Warfarin's own CYP2C9/VKORC1 pathway: with
    no pathway-intersecting clinical context present (normal coagulation,
    no severe DDI), the priority state must remain CONSIDER, accompanied
    by a strong clinical warning surfacing the elevated baseline risk --
    not an automatic HIGH PRIORITY escalation.
    """
    adr = calculate_adr_risk(age=85, num_drugs=8, previous_adr_history=True)
    assert adr["gerontonet_score"]["total_score"] == 6
    assert adr["gerontonet_score"]["risk_category"] == GERONTONET_RISK_HIGH
    assert adr["high_baseline_adr_risk"] is True
    assert adr["adr_risk_flag"] == ADR_RISK_HIGH

    triage = triage_pgx_actionability(
        "Warfarin", [], age=85, weight=65.0,
        platelets=250.0, pt_inr=1.0,
        high_baseline_adr_risk=adr["high_baseline_adr_risk"],
    )
    assert triage["triage"] == TRIAGE_CONSIDER
    assert triage["contextual_modifier"]["high_baseline_adr_risk"] is True
    assert triage["contextual_modifier"]["state_transition_applied"] is False
    assert any("Baseline ADR risk is elevated" in w for w in triage["warnings"])


def test_case_3_adatip_high_score_does_not_independently_escalate_warfarin():
    """A 70-year-old presenting with syncope on admission while taking RAAS
    drugs, prescribed Warfarin, with entirely normal labs and no
    drug-drug interaction.

    Age >= 65 is itself one of the ADATIP 9-Predictor Model's own
    predictors, so this profile trips three of them at once (age, syncope,
    RAAS drugs) -- well past the >=2 threshold that flags High Baseline ADR
    Risk. Per the integrated decision-matrix architecture, an
    ADATIP-driven baseline ADR risk verdict is just as orthogonal to
    Warfarin's own pathway as a GerontoNet-driven one: with no
    pathway-intersecting context present, the priority state must remain
    CONSIDER, accompanied by a strong clinical warning.
    """
    adr = calculate_adr_risk(age=70, syncope_on_admission=True, raas_drugs=True)
    assert adr["adatip_trigger_count"] >= 2
    assert adr["high_baseline_adr_risk"] is True
    assert adr["adr_risk_flag"] == ADR_RISK_HIGH

    triage = triage_pgx_actionability(
        "Warfarin", [], age=70, weight=68.0,
        platelets=250.0, pt_inr=1.0,
        high_baseline_adr_risk=adr["high_baseline_adr_risk"],
    )
    assert triage["triage"] == TRIAGE_CONSIDER
    assert triage["contextual_modifier"]["state_transition_applied"] is False
    assert any("Baseline ADR risk is elevated" in w for w in triage["warnings"])


def test_case_4_ddi_collision_clopidogrel_omeprazole():
    """Clopidogrel prescribed while the patient is taking Omeprazole -- a
    known, curated CYP2C19 drug-drug interaction.

    Clopidogrel's actionability prior already saturates the decision
    matrix on genetic grounds alone (HIGH PRIORITY regardless of context);
    this case specifically checks that the drug-drug interaction check
    still independently fires and surfaces the interaction as its own
    finding and warning, rather than silently no-opping once the priority
    state is already at its ceiling.
    """
    triage = triage_pgx_actionability("Clopidogrel", ["Omeprazole"])
    assert triage["triage"] == TRIAGE_HIGH
    assert len(triage["ddi_findings"]) == 1
    assert any("CYP2C19" in w for w in triage["warnings"])


def test_case_5_tacrolimus_renal_and_hepatic_warnings():
    """Tacrolimus prescribed with eGFR = 30 (reduced) and ALT/AST = 60
    (elevated) -- both pathway-intersecting lab abnormalities.

    Both labs cross their respective thresholds (eGFR < 60, ALT/AST > 40),
    so Tacrolimus's triage output must carry both lab-abnormality warnings
    -- worded as abnormalities requiring clinical correlation, never as a
    bare diagnosis.
    """
    triage = triage_pgx_actionability("Tacrolimus", [], egfr=30.0, alt_ast=60.0)
    assert triage["triage"] == TRIAGE_HIGH

    combined_text = " ".join(triage["warnings"])
    combined_text += " " + " ".join(f.get("detail", "") for f in triage["clinical_findings"])
    assert "Reduced eGFR" in combined_text
    assert "Elevated transaminases" in combined_text


def test_case_6_null_and_blank_inputs_never_crash():
    """A doctor leaves the entire form blank: every numeric lab and the
    medications field arrive as None (an empty text field parses to an
    empty list in app.py, so both are exercised here), for Warfarin.

    Nothing may raise, and with no risk factors present anywhere, the
    system must fall back to the safe routine-monitoring default,
    CONSIDER -- never HIGH PRIORITY (which would over-alert on missing
    data) and never a crash.
    """
    adr = calculate_adr_risk()  # every kwarg defaults to None / False / 0
    assert adr["high_baseline_adr_risk"] is False
    assert adr["adr_risk_flag"] == ADR_RISK_STANDARD

    for blank_medications in (None, []):
        triage = triage_pgx_actionability(
            "Warfarin", blank_medications,
            age=None, weight=None, egfr=None, alt_ast=None,
            platelets=None, pt_inr=None,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        assert triage["triage"] == TRIAGE_CONSIDER

    # Every MVP drug must tolerate a fully blank submission without raising.
    for drug in ("Clopidogrel", "Tacrolimus", "Warfarin"):
        result = triage_pgx_actionability(
            drug, None, age=None, weight=None, egfr=None,
            alt_ast=None, platelets=None, pt_inr=None,
            high_baseline_adr_risk=False,
        )
        assert "triage" in result
        assert "contextual_modifier" in result


def test_case_7_out_of_scope_drug_defaults_to_low_priority():
    """Prescribing an unmodeled drug (e.g. Ibuprofen).

    The triage layer must never fabricate an assessment for a drug it has
    no validated PGx relationship for -- it must default to LOW PRIORITY
    with an explicit "not in MVP scope" rationale.
    """
    triage = triage_pgx_actionability("Ibuprofen")
    assert triage["triage"] == TRIAGE_LOW
    assert any("MVP scope" in line for line in triage["rationale"])
    assert triage["ddi_findings"] == []
