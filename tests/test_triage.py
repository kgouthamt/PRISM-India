"""Unit tests for engine.triage (Layer 3, Path B: PGx Testing-Priority
Triage).

Covers objective inputs (drug, raw numeric lab readings type-cast and
evaluated against a conditional threshold in engine.clinical, DDIs,
age/weight) -- there is deliberately no test exercising a "previous ADR" or
"previous treatment failure" parameter, since triage_pgx_actionability has
no such parameter to begin with (only the pre-computed high_baseline_adr_risk
boolean crosses in from engine.clinical.calculate_adr_risk).

Also asserts, per the integrated decision-matrix architecture:
    - the lab-abnormality state machine (renal_function_status /
      transaminase_status / coagulation_cbc_status, surfaced via
      clinical_findings) never claims a diagnosis, only a lab abnormality,
      and is driven entirely by a numeric reading (or None) evaluated
      against a conditional threshold, never a pre-computed boolean;
    - Testing Priority = f(PGx Actionability, Patient-Specific Clinical
      Context) resolves deterministically via the decision matrix;
    - baseline ADR risk (Layer 2) is an orthogonal covariate that is
      reported separately (`contextual_modifier`) and never independently
      transitions the priority state for any drug -- only a
      pathway-intersecting clinical context (a severe DDI, or a numeric
      lab reading crossing its own threshold) can do that;
    - the CPIC Required/Recommended/Not Indicated projection
      (`resolve_cpic_testing_recommendation` /
      `cpic_testing_recommendation`) is a deterministic function of the
      resolved triage state alone; and
    - the mock GenomeIndia ethnicity lookup (`genomeindia_population_priority`)
      is fully decoupled: it is absent from every triage_pgx_actionability
      return value and never influences the resolved triage state for any
      ethnicity.
"""

import unittest

from engine.clinical import (
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    GERONTONET_RISK_HIGH,
    GERONTONET_RISK_LOW,
    PLATELETS_THRESHOLD,
    PT_INR_THRESHOLD,
    calculate_adr_risk,
    calculate_gerontonet_score,
)
from engine.triage import (
    CPIC_TESTING_NOT_INDICATED,
    CPIC_TESTING_RECOMMENDED,
    CPIC_TESTING_REQUIRED,
    ETHNICITY_OPTIONS,
    TRIAGE_CONSIDER,
    TRIAGE_HIGH,
    TRIAGE_LOW,
    genomeindia_population_priority,
    resolve_cpic_testing_recommendation,
    triage_pgx_actionability,
)


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
        result = triage_pgx_actionability("Tacrolimus", egfr=90.0, alt_ast=25.0)
        self.assertEqual(result["warnings"], [])

    def test_missing_labs_produce_no_warnings_and_no_crash(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=None, alt_ast=None)
        self.assertEqual(result["warnings"], [])

    def test_low_egfr_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35.0)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("KDIGO" in w for w in result["warnings"]))

    def test_low_egfr_never_asserts_a_nephrotoxicity_diagnosis(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35.0)
        self.assertFalse(any("nephrotoxicity risk" in w.lower() for w in result["warnings"]))
        renal_finding = result["clinical_findings"][0]
        self.assertEqual(renal_finding["renal_function_status"], "REDUCED")

    def test_high_alt_ast_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=150.0)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("NFI" in w for w in result["warnings"]))

    def test_high_alt_ast_never_asserts_a_hepatic_impairment_diagnosis(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=150.0)
        self.assertFalse(any("hepatic impairment" in w.lower() for w in result["warnings"]))
        hepatic_finding = result["clinical_findings"][1]
        self.assertEqual(hepatic_finding["transaminase_status"], "ELEVATED")

    def test_both_abnormal_produce_two_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35.0, alt_ast=150.0)
        self.assertEqual(len(result["warnings"]), 2)

    def test_egfr_exactly_at_threshold_is_not_abnormal(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=EGFR_THRESHOLD)
        self.assertEqual(result["warnings"], [])

    def test_alt_ast_exactly_at_threshold_is_not_abnormal(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=ALT_AST_THRESHOLD)
        self.assertEqual(result["warnings"], [])


class TestWarfarinTriage(unittest.TestCase):
    def test_low_risk_defaults_to_consider(self):
        result = triage_pgx_actionability("Warfarin", platelets=250.0, pt_inr=1.0)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_unknown_labs_do_not_escalate(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_low_platelets_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", platelets=100.0)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_high_pt_inr_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", pt_inr=1.5)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_platelets_exactly_at_threshold_does_not_escalate(self):
        result = triage_pgx_actionability("Warfarin", platelets=PLATELETS_THRESHOLD, pt_inr=1.0)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_pt_inr_exactly_at_threshold_does_not_escalate(self):
        result = triage_pgx_actionability("Warfarin", platelets=250.0, pt_inr=PT_INR_THRESHOLD)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_abnormal_coagulation_never_asserts_a_bleeding_risk_diagnosis(self):
        result = triage_pgx_actionability("Warfarin", platelets=100.0)
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
            "Warfarin", [], age=70, platelets=250.0, pt_inr=1.0,
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
            "Warfarin", [], age=40, platelets=250.0, pt_inr=1.0,
            high_baseline_adr_risk=True,
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertFalse(result["contextual_modifier"]["state_transition_applied"])

    def test_warfarin_high_adr_risk_with_missing_age_never_crashes_or_escalates(self):
        result = triage_pgx_actionability(
            "Warfarin", [], age=None, platelets=250.0, pt_inr=1.0,
            high_baseline_adr_risk=True,
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertFalse(result["contextual_modifier"]["state_transition_applied"])

    def test_warfarin_pathway_intersecting_context_still_escalates_regardless_of_adr_risk(self):
        # A pathway-intersecting context (abnormal coagulation) must still
        # escalate to HIGH PRIORITY, independent of the ADR risk covariate.
        for adr_flag in (True, False):
            result = triage_pgx_actionability(
                "Warfarin", [], platelets=100.0, pt_inr=1.0,
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
            "Warfarin", [], age=70, platelets=250.0, pt_inr=1.0,
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
            "Warfarin", [], age=70, platelets=250.0, pt_inr=1.0,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)
        self.assertTrue(len(result["warnings"]) >= 1)

    def test_previous_adr_history_alone_is_low_risk_and_does_not_escalate_warfarin(self):
        adr = calculate_adr_risk(previous_adr_history=True)
        self.assertEqual(adr["gerontonet_score"]["risk_category"], GERONTONET_RISK_LOW)
        self.assertFalse(adr["high_baseline_adr_risk"])

        result = triage_pgx_actionability(
            "Warfarin", [], age=70, platelets=250.0, pt_inr=1.0,
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


class TestCpicTestingRecommendation(unittest.TestCase):
    """The Required/Recommended/Not Indicated output is a deterministic
    projection of the resolved triage state alone."""

    def test_high_priority_maps_to_required(self):
        self.assertEqual(resolve_cpic_testing_recommendation(TRIAGE_HIGH), CPIC_TESTING_REQUIRED)

    def test_consider_maps_to_recommended(self):
        self.assertEqual(resolve_cpic_testing_recommendation(TRIAGE_CONSIDER), CPIC_TESTING_RECOMMENDED)

    def test_low_priority_maps_to_not_indicated(self):
        self.assertEqual(resolve_cpic_testing_recommendation(TRIAGE_LOW), CPIC_TESTING_NOT_INDICATED)

    def test_unrecognized_state_defaults_to_not_indicated(self):
        self.assertEqual(resolve_cpic_testing_recommendation("SOMETHING_ELSE"), CPIC_TESTING_NOT_INDICATED)

    def test_triage_pgx_actionability_always_carries_the_projection(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin", "Ibuprofen"):
            result = triage_pgx_actionability(drug)
            self.assertEqual(
                result["cpic_testing_recommendation"],
                resolve_cpic_testing_recommendation(result["triage"]),
            )

    def test_clopidogrel_is_always_required(self):
        result = triage_pgx_actionability("Clopidogrel")
        self.assertEqual(result["cpic_testing_recommendation"], CPIC_TESTING_REQUIRED)

    def test_warfarin_defaults_to_recommended(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertEqual(result["cpic_testing_recommendation"], CPIC_TESTING_RECOMMENDED)

    def test_out_of_scope_drug_is_not_indicated(self):
        result = triage_pgx_actionability("Ibuprofen")
        self.assertEqual(result["cpic_testing_recommendation"], CPIC_TESTING_NOT_INDICATED)


class TestGenomeIndiaPopulationPriorityIsDecoupled(unittest.TestCase):
    """CRITICAL DECOUPLING: the mock GenomeIndia ethnicity lookup is a pure
    function of ethnicity alone. It must never appear inside
    triage_pgx_actionability's return value, and no ethnicity value may
    change the resolved triage state for any drug."""

    def test_every_ethnicity_option_resolves_to_a_priority(self):
        for ethnicity in ETHNICITY_OPTIONS:
            result = genomeindia_population_priority(ethnicity)
            self.assertIn(result["genomeindia_priority"], ("High Priority", "Medium Priority", "Low Priority"))
            self.assertEqual(result["ethnicity"], ethnicity)

    def test_unrecognized_ethnicity_defaults_to_low_priority(self):
        result = genomeindia_population_priority("Unrecognized Group")
        self.assertEqual(result["genomeindia_priority"], "Low Priority")

    def test_genomeindia_output_never_appears_in_triage_result(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertNotIn("genomeindia_priority", result)
        self.assertNotIn("ethnicity", result)
        self.assertNotIn("genomeindia_result", result)

    def test_ethnicity_never_changes_the_resolved_triage_state_for_any_drug(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin", "Ibuprofen"):
            baseline = triage_pgx_actionability(drug, platelets=250.0, pt_inr=1.0)
            for ethnicity in ETHNICITY_OPTIONS:
                # genomeindia_population_priority is computed, but its
                # result is never fed back into triage_pgx_actionability --
                # the two calls below are entirely independent.
                genomeindia_population_priority(ethnicity)
                repeated = triage_pgx_actionability(drug, platelets=250.0, pt_inr=1.0)
                self.assertEqual(baseline["triage"], repeated["triage"])


if __name__ == "__main__":
    unittest.main()
