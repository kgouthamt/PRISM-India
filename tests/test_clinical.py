"""Unit tests for engine.clinical (Layer 1 lab-abnormality state machine and
Layer 2 isolated ADR risk execution contexts)."""

import unittest

from engine.clinical import (
    ADR_RISK_HIGH,
    ADR_RISK_STANDARD,
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    GERONTONET_HIGH_RISK_THRESHOLD,
    GERONTONET_RISK_HIGH,
    GERONTONET_RISK_LOW,
    ISOLATED_VERDICT_BASELINE,
    ISOLATED_VERDICT_HIGH,
    PLATELETS_THRESHOLD,
    PT_INR_THRESHOLD,
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
    calculate_adr_risk,
    calculate_gerontonet_score,
)


class TestRenalFunction(unittest.TestCase):
    """Renal function is a strict three-valued state -- True (abnormal),
    False (normal), or None (missing data) -- never a numeric comparison."""

    def test_true_flag_is_reduced(self):
        result = assess_renal_function(True)
        self.assertEqual(result["renal_function_status"], "REDUCED")

    def test_false_flag_is_normal(self):
        result = assess_renal_function(False)
        self.assertEqual(result["renal_function_status"], "NORMAL")

    def test_none_flag_is_unknown_and_never_flags(self):
        result = assess_renal_function(None)
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_renal_function()
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_true_immediately_transitions_to_abnormal_state(self):
        # Marking a lab True must produce the ABNORMAL -> FLAG transition
        # with no intermediate step.
        result = assess_renal_function(True)
        self.assertNotEqual(result["renal_function_status"], "NORMAL")
        self.assertNotEqual(result["renal_function_status"], "UNKNOWN")

    def test_reduced_detail_uses_the_required_wording(self):
        result = assess_renal_function(True)
        self.assertIn("Reduced eGFR flagged as abnormal; requires clinical correlation", result["detail"])
        self.assertNotIn("nephrotoxicity risk", result["detail"].lower())

    def test_reduced_detail_cites_kdigo_reference_threshold(self):
        result = assess_renal_function(True)
        self.assertIn("KDIGO 2024", result["detail"])
        self.assertIn(str(EGFR_THRESHOLD), result["detail"])

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function(False)["source"], "KDIGO 2024")

    def test_egfr_abnormal_field_echoes_input(self):
        self.assertTrue(assess_renal_function(True)["egfr_abnormal"])
        self.assertFalse(assess_renal_function(False)["egfr_abnormal"])
        self.assertIsNone(assess_renal_function(None)["egfr_abnormal"])


class TestHepaticFunction(unittest.TestCase):
    """Hepatic transaminase state is a strict three-valued flag, never a
    numeric comparison."""

    def test_true_flag_is_elevated(self):
        result = assess_hepatic_function(True)
        self.assertEqual(result["transaminase_status"], "ELEVATED")

    def test_false_flag_is_normal(self):
        result = assess_hepatic_function(False)
        self.assertEqual(result["transaminase_status"], "NORMAL")

    def test_none_flag_is_unknown_and_never_flags(self):
        result = assess_hepatic_function(None)
        self.assertEqual(result["transaminase_status"], "UNKNOWN")

    def test_elevated_detail_uses_the_required_wording(self):
        result = assess_hepatic_function(True)
        self.assertIn("Elevated transaminases flagged as abnormal; laboratory abnormality", result["detail"])
        self.assertNotIn("hepatic impairment", result["detail"].lower())

    def test_elevated_detail_cites_nfi_reference_threshold(self):
        result = assess_hepatic_function(True)
        self.assertIn("NFI", result["detail"])
        self.assertIn(str(ALT_AST_THRESHOLD), result["detail"])

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function(False)["source"])


class TestBleedingRiskLabs(unittest.TestCase):
    """Coagulation/CBC state is resolved from two independent three-valued
    flags, never a numeric comparison."""

    def test_both_false_is_normal(self):
        result = assess_bleeding_risk_labs(False, False)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")
        self.assertEqual(result["flags"], [])

    def test_both_none_is_unknown_and_never_flags(self):
        result = assess_bleeding_risk_labs(None, None)
        self.assertEqual(result["coagulation_cbc_status"], "UNKNOWN")
        self.assertEqual(result["flags"], [])

    def test_platelets_true_is_abnormal(self):
        result = assess_bleeding_risk_labs(True, False)
        self.assertEqual(result["coagulation_cbc_status"], "ABNORMAL")

    def test_pt_inr_true_is_abnormal(self):
        result = assess_bleeding_risk_labs(False, True)
        self.assertEqual(result["coagulation_cbc_status"], "ABNORMAL")

    def test_one_flag_false_other_none_is_normal(self):
        result = assess_bleeding_risk_labs(False, None)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")
        result2 = assess_bleeding_risk_labs(None, False)
        self.assertEqual(result2["coagulation_cbc_status"], "NORMAL")

    def test_abnormal_detail_uses_the_required_wording(self):
        result = assess_bleeding_risk_labs(True, False)
        self.assertIn("Abnormal coagulation/CBC parameters", result["detail"])
        self.assertNotIn("bleeding risk", result["detail"].lower())

    def test_abnormal_flags_cite_reference_thresholds(self):
        result = assess_bleeding_risk_labs(True, True)
        combined = " ".join(result["flags"])
        self.assertIn(str(PLATELETS_THRESHOLD), combined)
        self.assertIn(str(PT_INR_THRESHOLD), combined)


class TestAgeWeightContext(unittest.TestCase):
    def test_pediatric_age_flags(self):
        result = assess_age_weight_context(age=10, weight=70)
        self.assertTrue(any("Pediatric" in f for f in result["flags"]))

    def test_adult_age_does_not_flag(self):
        result = assess_age_weight_context(age=40, weight=70)
        self.assertEqual(result["flags"], [])

    def test_low_weight_flags(self):
        result = assess_age_weight_context(age=40, weight=30)
        self.assertTrue(any("Low body weight" in f for f in result["flags"]))

    def test_no_data_produces_no_flags(self):
        result = assess_age_weight_context()
        self.assertEqual(result["flags"], [])

    def test_source_is_fda_dosing_guidance(self):
        self.assertIn("FDA", assess_age_weight_context(age=40, weight=70)["source"])


class TestGerontoNetScoreMath(unittest.TestCase):
    """The actual validated GerontoNet ADR Risk Score -- weighted points,
    not a derived binary predictor-count heuristic."""

    def test_no_predictors_is_zero_and_low_risk(self):
        result = calculate_gerontonet_score()
        self.assertEqual(result["total_score"], 0)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_LOW)

    def test_gte4_comorbid_conditions_is_one_point(self):
        result = calculate_gerontonet_score(gte4_comorbid_conditions=True)
        self.assertEqual(result["total_score"], 1)
        self.assertEqual(result["breakdown"]["gte4_comorbid_conditions"], 1)

    def test_heart_failure_is_one_point(self):
        result = calculate_gerontonet_score(heart_failure=True)
        self.assertEqual(result["total_score"], 1)

    def test_liver_disease_is_one_point(self):
        result = calculate_gerontonet_score(liver_disease=True)
        self.assertEqual(result["total_score"], 1)

    def test_renal_failure_is_one_point(self):
        result = calculate_gerontonet_score(renal_failure=True)
        self.assertEqual(result["total_score"], 1)

    def test_previous_adr_history_is_two_points(self):
        result = calculate_gerontonet_score(previous_adr_history=True)
        self.assertEqual(result["total_score"], 2)
        self.assertEqual(result["breakdown"]["previous_adr_history"], 2)

    def test_four_concurrent_drugs_is_zero_points(self):
        result = calculate_gerontonet_score(num_drugs=4)
        self.assertEqual(result["breakdown"]["concurrent_drugs"], 0)

    def test_five_concurrent_drugs_is_one_point(self):
        result = calculate_gerontonet_score(num_drugs=5)
        self.assertEqual(result["breakdown"]["concurrent_drugs"], 1)

    def test_seven_concurrent_drugs_is_one_point(self):
        result = calculate_gerontonet_score(num_drugs=7)
        self.assertEqual(result["breakdown"]["concurrent_drugs"], 1)

    def test_eight_concurrent_drugs_is_four_points(self):
        result = calculate_gerontonet_score(num_drugs=8)
        self.assertEqual(result["breakdown"]["concurrent_drugs"], 4)

    def test_twenty_concurrent_drugs_is_still_four_points(self):
        result = calculate_gerontonet_score(num_drugs=20)
        self.assertEqual(result["breakdown"]["concurrent_drugs"], 4)

    def test_previous_adr_history_alone_is_not_high_risk(self):
        # 2 points alone must NOT reach the 4-point High Risk threshold --
        # a single strong predictor is not, on its own, sufficient under the
        # actual validated score.
        result = calculate_gerontonet_score(previous_adr_history=True)
        self.assertEqual(result["total_score"], 2)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_LOW)

    def test_score_of_three_is_low_risk(self):
        result = calculate_gerontonet_score(
            heart_failure=True, liver_disease=True, renal_failure=True,
        )
        self.assertEqual(result["total_score"], 3)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_LOW)

    def test_score_of_exactly_four_is_high_risk(self):
        result = calculate_gerontonet_score(
            heart_failure=True, liver_disease=True, renal_failure=True,
            gte4_comorbid_conditions=True,
        )
        self.assertEqual(result["total_score"], GERONTONET_HIGH_RISK_THRESHOLD)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_HIGH)

    def test_previous_adr_history_plus_heart_failure_plus_liver_disease_is_high_risk(self):
        # 2 + 1 + 1 = 4
        result = calculate_gerontonet_score(
            previous_adr_history=True, heart_failure=True, liver_disease=True,
        )
        self.assertEqual(result["total_score"], 4)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_HIGH)

    def test_max_score_is_ten(self):
        result = calculate_gerontonet_score(
            gte4_comorbid_conditions=True, heart_failure=True, liver_disease=True,
            renal_failure=True, num_drugs=8, previous_adr_history=True,
        )
        self.assertEqual(result["total_score"], 10)
        self.assertEqual(result["max_score"], 10)
        self.assertEqual(result["risk_category"], GERONTONET_RISK_HIGH)

    def test_source_cites_gerontonet(self):
        self.assertIn("GerontoNet", calculate_gerontonet_score()["source"])


class TestCalculateAdrRiskComposite(unittest.TestCase):
    """Baseline ADR risk from the ADATIP 9-Predictor Model, the actual
    GerontoNet ADR Risk Score, and clinician-reported general clinical
    history."""

    def test_no_predictors_is_standard_risk(self):
        result = calculate_adr_risk()
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_STANDARD)
        self.assertFalse(result["high_baseline_adr_risk"])
        self.assertEqual(result["reasons"], [])

    def test_previous_adr_history_alone_is_not_high_risk(self):
        # Corrected per the actual GerontoNet math: 2 points alone is Low Risk.
        result = calculate_adr_risk(previous_adr_history=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_STANDARD)
        self.assertEqual(result["gerontonet_score"]["total_score"], 2)

    def test_gerontonet_high_risk_score_drives_composite_high_risk(self):
        result = calculate_adr_risk(
            previous_adr_history=True, heart_failure=True, liver_disease=True,
        )
        self.assertEqual(result["gerontonet_score"]["total_score"], 4)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_HIGH)
        self.assertTrue(any("GerontoNet" in r for r in result["reasons"]))

    def test_single_adatip_predictor_is_not_high_risk(self):
        result = calculate_adr_risk(chronic_lung_disease=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_STANDARD)

    def test_two_adatip_predictors_is_high_risk(self):
        result = calculate_adr_risk(chronic_lung_disease=True, diuretics=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_HIGH)
        self.assertEqual(result["adatip_trigger_count"], 2)

    def test_elderly_age_counts_as_an_adatip_predictor(self):
        result = calculate_adr_risk(age=70, chronic_lung_disease=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_HIGH)
        self.assertEqual(result["adatip_trigger_count"], 2)

    def test_non_elderly_age_does_not_count_as_a_predictor(self):
        result = calculate_adr_risk(age=40, chronic_lung_disease=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_STANDARD)
        self.assertEqual(result["adatip_trigger_count"], 1)

    def test_allergy_history_alone_is_not_high_risk(self):
        result = calculate_adr_risk(allergy_history=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_STANDARD)

    def test_allergy_and_family_history_together_is_high_risk(self):
        result = calculate_adr_risk(allergy_history=True, family_history=True)
        self.assertEqual(result["adr_risk_flag"], ADR_RISK_HIGH)
        self.assertEqual(result["general_history_trigger_count"], 2)

    def test_reasons_list_is_populated_when_high_risk(self):
        result = calculate_adr_risk(chronic_lung_disease=True, diuretics=True)
        self.assertTrue(len(result["reasons"]) >= 1)

    def test_source_cites_both_models(self):
        source = calculate_adr_risk()["source"]
        self.assertIn("ADATIP", source)
        self.assertIn("GerontoNet", source)

    def test_gerontonet_score_subdict_is_always_present(self):
        result = calculate_adr_risk()
        self.assertIn("total_score", result["gerontonet_score"])
        self.assertIn("risk_category", result["gerontonet_score"])
        self.assertIn("breakdown", result["gerontonet_score"])

    def test_no_missing_keyword_raises_type_error(self):
        # Every parameter is optional -- calling with none of them must not
        # raise a TypeError or KeyError.
        result = calculate_adr_risk()
        self.assertIn("high_baseline_adr_risk", result)


class TestIsolatedExecutionContexts(unittest.TestCase):
    """ADATIP and GerontoNet are isolated execution contexts: each produces
    its own independent verdict, and neither model's verdict is derived
    from, or influenced by, the other's internal state."""

    def test_both_verdicts_default_to_baseline_standard(self):
        result = calculate_adr_risk()
        self.assertEqual(result["adatip_isolated_verdict"], ISOLATED_VERDICT_BASELINE)
        self.assertEqual(result["gerontonet_isolated_verdict"], ISOLATED_VERDICT_BASELINE)

    def test_adatip_verdict_is_high_risk_independent_of_gerontonet(self):
        # Two ADATIP predictors trip the ADATIP verdict alone, with every
        # GerontoNet-only predictor left at its default (False/0).
        result = calculate_adr_risk(chronic_lung_disease=True, diuretics=True)
        self.assertEqual(result["adatip_isolated_verdict"], ISOLATED_VERDICT_HIGH)
        self.assertEqual(result["gerontonet_isolated_verdict"], ISOLATED_VERDICT_BASELINE)

    def test_gerontonet_verdict_is_high_risk_independent_of_adatip(self):
        # A GerontoNet score of 4 trips the GerontoNet verdict alone, with
        # every ADATIP-only predictor left at its default (False/None).
        result = calculate_adr_risk(
            heart_failure=True, liver_disease=True, renal_failure=True,
            gte4_comorbid_conditions=True,
        )
        self.assertEqual(result["gerontonet_isolated_verdict"], ISOLATED_VERDICT_HIGH)
        self.assertEqual(result["adatip_isolated_verdict"], ISOLATED_VERDICT_BASELINE)

    def test_both_verdicts_can_independently_be_high_risk_simultaneously(self):
        result = calculate_adr_risk(
            chronic_lung_disease=True, diuretics=True,
            heart_failure=True, liver_disease=True, renal_failure=True,
            gte4_comorbid_conditions=True,
        )
        self.assertEqual(result["adatip_isolated_verdict"], ISOLATED_VERDICT_HIGH)
        self.assertEqual(result["gerontonet_isolated_verdict"], ISOLATED_VERDICT_HIGH)

    def test_general_history_never_moves_either_isolated_verdict(self):
        # Allergy + family history drives the composite high_baseline_adr_risk
        # True, but must never move either model's own isolated verdict --
        # that group is not part of either model.
        result = calculate_adr_risk(allergy_history=True, family_history=True)
        self.assertTrue(result["high_baseline_adr_risk"])
        self.assertEqual(result["adatip_isolated_verdict"], ISOLATED_VERDICT_BASELINE)
        self.assertEqual(result["gerontonet_isolated_verdict"], ISOLATED_VERDICT_BASELINE)

    def test_isolated_verdicts_use_the_exact_ui_vocabulary(self):
        result = calculate_adr_risk()
        self.assertIn(result["adatip_isolated_verdict"], ("High Risk", "Baseline Standard"))
        self.assertIn(result["gerontonet_isolated_verdict"], ("High Risk", "Baseline Standard"))


if __name__ == "__main__":
    unittest.main()
