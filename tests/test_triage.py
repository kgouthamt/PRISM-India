"""Unit tests for engine.triage (PGx Testing-Priority Triage).

Covers only objective, routine inputs (drug, exact numeric labs, DDIs,
age/weight) -- there is deliberately no test exercising a "previous ADR" or
"previous treatment failure" parameter, since triage_pgx_actionability has
no such parameter to begin with (only the pre-computed high_baseline_adr_risk
boolean crosses in from engine.clinical.calculate_adr_risk).

Also asserts, per the integrated decision-matrix architecture:
    - the lab-abnormality threshold logic (renal_function_status /
      transaminase_status / coagulation_cbc_status, surfaced via
      clinical_findings) never claims a diagnosis, only a lab abnormality;
    - Testing Priority = f(PGx Actionability, Patient-Specific Clinical
      Context) resolves deterministically via the decision matrix; and
    - baseline ADR risk (Layer 2) is an orthogonal covariate that is
      reported separately (`contextual_modifier`) and never independently
      transitions the priority state for any drug -- only a
      pathway-intersecting clinical context (a severe DDI, or an extreme
      lab value tied to the drug's own mechanism) can do that.
"""

import unittest

from engine.clinical import (
    GERONTONET_RISK_HIGH,
    GERONTONET_RISK_LOW,
    calculate_adr_risk,
    calculate_gerontonet_score,
)
from engine.triage import TRIAGE_CONSIDER, TRIAGE_HIGH, TRIAGE_LOW, triage_pgx_actionability


class TestClopidogrelTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Clopidogrel")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_surfaces_omeprazole_ddi_as_a_warning(self):
        result = triage_pgx_actionability("Clopidogrel", ["Omeprazole"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)
        self.assertEqual(len(result["ddi_findings"]), 1)
        self.assertTrue(any("CYP2C19-inhibiting" in w for w in result["warnings"]))


class TestTacrolimusTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Tacrolimus")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_normal_labs_produce_no_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=90, alt_ast=25)
        self.assertEqual(result["warnings"], [])

    def test_unknown_labs_produce_no_warnings_and_no_crash(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=None, alt_ast=None)
        self.assertEqual(result["warnings"], [])

    def test_low_egfr_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("KDIGO" in w for w in result["warnings"]))

    def test_low_egfr_never_asserts_a_nephrotoxicity_diagnosis(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35)
        self.assertFalse(any("nephrotoxicity risk" in w.lower() for w in result["warnings"]))
        renal_finding = result["clinical_findings"][0]
        self.assertEqual(renal_finding["renal_function_status"], "REDUCED")

    def test_high_alt_ast_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=150)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("NFI" in w for w in result["warnings"]))

    def test_high_alt_ast_never_asserts_a_hepatic_impairment_diagnosis(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=150)
        self.assertFalse(any("hepatic impairment" in w.lower() for w in result["warnings"]))
        hepatic_finding = result["clinical_findings"][1]
        self.assertEqual(hepatic_finding["transaminase_status"], "ELEVATED")

    def test_both_abnormal_produce_two_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35, alt_ast=150)
        self.assertEqual(len(result["warnings"]), 2)


class TestWarfarinTriage(unittest.TestCase):
    def test_low_risk_defaults_to_consider(self):
        result = triage_pgx_actionability("Warfarin", platelets=250, pt_inr=1.0)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_unknown_labs_do_not_escalate(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_low_platelets_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", platelets=100)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_high_pt_inr_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", pt_inr=1.5)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_abnormal_coagulation_never_asserts_a_bleeding_risk_diagnosis(self):
        result = triage_pgx_actionability("Warfarin", platelets=100)
        self.assertFalse(any("bleeding risk" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("Abnormal coagulation/CBC parameters" in w for w in result["warnings"]))
        coagulation_finding = result["clinical_findings"][0]
        self.assertEqual(coagulation_finding["coagulation_cbc_status"], "ABNORMAL")

    def test_severe_ddi_amiodarone_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Amiodarone"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_severe_ddi_nsaid_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Ibuprofen"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_no_risk_factors_never_reaches_low_priority(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertIn(result["triage"], (TRIAGE_CONSIDER, TRIAGE_HIGH))


class TestAgeWeightContextSurfacesAcrossDrugs(unittest.TestCase):
    def test_pediatric_and_low_weight_flags_appear_in_rationale(self):
        result = triage_pgx_actionability("Clopidogrel", age=10, weight=25)
        self.assertTrue(any("Pediatric" in line for line in result["rationale"]))
        self.assertTrue(any("Low body weight" in line for line in result["rationale"]))

    def test_age_weight_finding_is_always_present(self):
        result = triage_pgx_actionability("Clopidogrel")
        sources = [f.get("source") for f in result["clinical_findings"]]
        self.assertTrue(any("FDA" in (s or "") for s in sources))


class TestNoneValuesNeverCrash(unittest.TestCase):
    def test_all_none_across_every_drug(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin", "Ibuprofen"):
            result = triage_pgx_actionability(
                drug, None, age=None, weight=None, egfr=None,
                alt_ast=None, platelets=None, pt_inr=None,
            )
            self.assertIn("triage", result)

    def test_all_none_with_adr_risk_flag_across_every_drug(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin", "Ibuprofen"):
            for adr_flag in (True, False):
                result = triage_pgx_actionability(
                    drug, None, age=None, weight=None, egfr=None,
                    alt_ast=None, platelets=None, pt_inr=None,
                    high_baseline_adr_risk=adr_flag,
                )
                self.assertIn("triage", result)
                self.assertIn("contextual_modifier", result)


class TestBaselineAdrRiskIsAnOrthogonalCovariate(unittest.TestCase):
    """Baseline ADR risk (patient fragility) and PGx actionability (this
    drug's genetic testing priority) are two distinct conceptual outputs.
    Per the integrated decision-matrix architecture, baseline ADR risk is
    an orthogonal covariate that never independently transitions the
    priority state for any drug -- only a pathway-intersecting clinical
    context can do that."""

    def test_standard_adr_risk_note_and_no_state_transition(self):
        result = triage_pgx_actionability("Warfarin", age=70, high_baseline_adr_risk=False)
        modifier = result["contextual_modifier"]
        self.assertFalse(modifier["high_baseline_adr_risk"])
        self.assertFalse(modifier["state_transition_applied"])

    def test_warfarin_high_adr_risk_never_escalates_even_when_elderly(self):
        # This is the corrected behavior: a high baseline ADR risk score
        # must NOT independently force Warfarin to HIGH PRIORITY, even for
        # an elderly patient -- only a pathway-intersecting condition
        # (severe DDI, abnormal coagulation) may do that.
        result = triage_pgx_actionability(
            "Warfarin", [], age=70, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=True,
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        modifier = result["contextual_modifier"]
        self.assertTrue(modifier["high_baseline_adr_risk"])
        self.assertFalse(modifier["state_transition_applied"])
        # Strong clinical warnings must still accompany the CONSIDER output.
        self.assertTrue(any("Baseline ADR risk is elevated" in w for w in result["warnings"]))

    def test_warfarin_high_adr_risk_non_elderly_also_never_escalates(self):
        result = triage_pgx_actionability(
            "Warfarin", [], age=40, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=True,
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertFalse(result["contextual_modifier"]["state_transition_applied"])

    def test_warfarin_high_adr_risk_with_missing_age_never_crashes_or_escalates(self):
        result = triage_pgx_actionability(
            "Warfarin", [], age=None, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=True,
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertFalse(result["contextual_modifier"]["state_transition_applied"])

    def test_warfarin_pathway_intersecting_context_still_escalates_regardless_of_adr_risk(self):
        # A pathway-intersecting context (abnormal coagulation) must still
        # escalate to HIGH PRIORITY, independent of the ADR risk covariate.
        for adr_flag in (True, False):
            result = triage_pgx_actionability(
                "Warfarin", [], platelets=100, pt_inr=1.0,
                high_baseline_adr_risk=adr_flag,
            )
            self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_clopidogrel_high_adr_risk_never_transitions_state_but_is_reported(self):
        result = triage_pgx_actionability("Clopidogrel", high_baseline_adr_risk=True)
        self.assertEqual(result["triage"], TRIAGE_HIGH)
        modifier = result["contextual_modifier"]
        self.assertTrue(modifier["high_baseline_adr_risk"])
        self.assertFalse(modifier["state_transition_applied"])
        self.assertIn("priority state is unaffected", modifier["note"])

    def test_tacrolimus_high_adr_risk_never_transitions_state_but_is_reported(self):
        result = triage_pgx_actionability("Tacrolimus", high_baseline_adr_risk=True)
        self.assertEqual(result["triage"], TRIAGE_HIGH)
        modifier = result["contextual_modifier"]
        self.assertTrue(modifier["high_baseline_adr_risk"])
        self.assertFalse(modifier["state_transition_applied"])

    def test_out_of_scope_drug_still_reports_contextual_modifier(self):
        result = triage_pgx_actionability("Ibuprofen", high_baseline_adr_risk=True)
        self.assertIn("contextual_modifier", result)
        self.assertFalse(result["contextual_modifier"]["state_transition_applied"])


class TestGerontoNetScoreNeverEscalatesWarfarinAlone(unittest.TestCase):
    """End-to-end: even a maximal, real GerontoNet/ADATIP-driven baseline
    ADR risk verdict (via calculate_adr_risk) must not, by itself, force
    Warfarin's priority state to HIGH -- it is an orthogonal covariate, not
    a value of Patient-Specific Clinical Context."""

    def test_high_gerontonet_score_appended_to_warfarin_yields_consider_with_warnings(self):
        adr = calculate_adr_risk(
            previous_adr_history=True, heart_failure=True, liver_disease=True,
        )
        self.assertEqual(adr["gerontonet_score"]["total_score"], 4)
        self.assertEqual(adr["gerontonet_score"]["risk_category"], GERONTONET_RISK_HIGH)
        self.assertTrue(adr["high_baseline_adr_risk"])

        result = triage_pgx_actionability(
            "Warfarin", [], age=70, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertTrue(len(result["warnings"]) >= 1)

    def test_high_adatip_score_appended_to_warfarin_yields_consider_with_warnings(self):
        adr = calculate_adr_risk(
            age=70, syncope_on_admission=True, raas_drugs=True,
        )
        self.assertGreaterEqual(adr["adatip_trigger_count"], 2)
        self.assertTrue(adr["high_baseline_adr_risk"])

        result = triage_pgx_actionability(
            "Warfarin", [], age=70, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertTrue(len(result["warnings"]) >= 1)

    def test_previous_adr_history_alone_is_low_risk_and_does_not_escalate_warfarin(self):
        adr = calculate_adr_risk(previous_adr_history=True)
        self.assertEqual(adr["gerontonet_score"]["risk_category"], GERONTONET_RISK_LOW)
        self.assertFalse(adr["high_baseline_adr_risk"])

        result = triage_pgx_actionability(
            "Warfarin", [], age=70, platelets=250, pt_inr=1.0,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_gerontonet_score_boundary_three_vs_four(self):
        low = calculate_gerontonet_score(heart_failure=True, liver_disease=True, renal_failure=True)
        high = calculate_gerontonet_score(
            heart_failure=True, liver_disease=True, renal_failure=True,
            gte4_comorbid_conditions=True,
        )
        self.assertEqual(low["total_score"], 3)
        self.assertEqual(low["risk_category"], GERONTONET_RISK_LOW)
        self.assertEqual(high["total_score"], 4)
        self.assertEqual(high["risk_category"], GERONTONET_RISK_HIGH)


class TestOutOfScopeDrug(unittest.TestCase):
    def test_unmodeled_drug_is_low_priority(self):
        result = triage_pgx_actionability("Ibuprofen")
        self.assertEqual(result["triage"], TRIAGE_LOW)
        self.assertEqual(result["ddi_findings"], [])


if __name__ == "__main__":
    unittest.main()
