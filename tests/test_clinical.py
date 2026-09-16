"""Unit tests for engine.clinical (objective clinical data assessment)."""

import unittest

from engine.clinical import (
    ADR_RISK_HIGH,
    ADR_RISK_STANDARD,
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    GERONTONET_HIGH_RISK_THRESHOLD,
    GERONTONET_RISK_HIGH,
    GERONTONET_RISK_LOW,
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
    """eGFR is a lab abnormality flag, not a nephrotoxicity diagnosis."""

    def test_egfr_at_threshold_is_normal(self):
        result = assess_renal_function(EGFR_THRESHOLD)
        self.assertEqual(result["renal_function_status"], "NORMAL")

    def test_egfr_just_below_threshold_is_reduced(self):
        result = assess_renal_function(EGFR_THRESHOLD - 0.1)
        self.assertEqual(result["renal_function_status"], "REDUCED")

    def test_egfr_well_above_threshold_is_normal(self):
        result = assess_renal_function(90)
        self.assertEqual(result["renal_function_status"], "NORMAL")

    def test_egfr_none_is_unknown_and_never_flags(self):
        result = assess_renal_function(None)
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_renal_function()
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_reduced_detail_uses_the_required_wording(self):
        result = assess_renal_function(EGFR_THRESHOLD - 0.1)
        self.assertIn("Reduced eGFR; requires clinical correlation for renal dose adjustment", result["detail"])
        self.assertNotIn("nephrotoxicity risk", result["detail"].lower())

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function(90)["source"], "KDIGO 2024")


class TestHepaticFunction(unittest.TestCase):
    """ALT/AST is a lab abnormality flag, not a hepatic-impairment diagnosis."""

    def test_alt_ast_at_threshold_is_normal(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD)
        self.assertEqual(result["transaminase_status"], "NORMAL")

    def test_alt_ast_just_above_threshold_is_elevated(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD + 0.1)
        self.assertEqual(result["transaminase_status"], "ELEVATED")

    def test_alt_ast_well_above_threshold_is_elevated(self):
        result = assess_hepatic_function(150)
        self.assertEqual(result["transaminase_status"], "ELEVATED")

    def test_alt_ast_none_is_unknown_and_never_flags(self):
        result = assess_hepatic_function(None)
        self.assertEqual(result["transaminase_status"], "UNKNOWN")

    def test_elevated_detail_uses_the_required_wording(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD + 0.1)
        self.assertIn("Elevated transaminases; laboratory abnormality", result["detail"])
        self.assertNotIn("hepatic impairment", result["detail"].lower())

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function(25)["source"])


class TestBleedingRiskLabs(unittest.TestCase):
    """Platelets/PT-INR are lab abnormality flags, not a bleeding-risk diagnosis."""

    def test_normal_values_are_normal(self):
        result = assess_bleeding_risk_labs(250, 1.0)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")
        self.assertEqual(result["flags"], [])

    def test_both_none_is_unknown_and_never_flags(self):
        result = assess_bleeding_risk_labs(None, None)
        self.assertEqual(result["coagulation_cbc_status"], "UNKNOWN")
        self.assertEqual(result["flags"], [])

    def test_platelets_at_threshold_is_normal(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD, 1.0)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")

    def test_platelets_below_threshold_is_abnormal(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD - 1, 1.0)
        self.assertEqual(result["coagulation_cbc_status"], "ABNORMAL")

    def test_pt_inr_at_threshold_is_normal(self):
        result = assess_bleeding_risk_labs(250, PT_INR_THRESHOLD)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")

    def test_pt_inr_above_threshold_is_abnormal(self):
        result = assess_bleeding_risk_labs(250, PT_INR_THRESHOLD + 0.1)
        self.assertEqual(result["coagulation_cbc_status"], "ABNORMAL")

    def test_one_value_known_normal_other_unknown_is_normal(self):
        result = assess_bleeding_risk_labs(250, None)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")
        result2 = assess_bleeding_risk_labs(None, 1.0)
        self.assertEqual(result2["coagulation_cbc_status"], "NORMAL")

    def test_abnormal_detail_uses_the_required_wording(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD - 1, 1.0)
        self.assertIn("Abnormal coagulation/CBC parameters", result["detail"])
        self.assertNotIn("bleeding risk", result["detail"].lower())


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


class TestCalculateAdrRisk(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
