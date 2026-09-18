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
    is_alt_ast_abnormal,
    is_egfr_abnormal,
    is_platelets_abnormal,
    is_pt_inr_abnormal,
    parse_lab_value,
)


class TestParseLabValue(unittest.TestCase):
    """parse_lab_value is the sole text-to-float type-casting boundary for
    every Layer 1 numeric lab field. It must never raise ValueError or
    TypeError, regardless of input."""

    def test_valid_integer_literal_casts_cleanly(self):
        value, error = parse_lab_value("45")
        self.assertEqual(value, 45.0)
        self.assertIsNone(error)

    def test_valid_float_literal_casts_cleanly(self):
        value, error = parse_lab_value("59.9")
        self.assertEqual(value, 59.9)
        self.assertIsNone(error)

    def test_empty_string_is_missing_data_not_an_error(self):
        value, error = parse_lab_value("")
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_whitespace_only_string_is_missing_data(self):
        value, error = parse_lab_value("   ")
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_none_token_is_case_insensitive_missing_data(self):
        for token in ("none", "None", "NONE", "NoNe"):
            value, error = parse_lab_value(token)
            self.assertIsNone(value)
            self.assertIsNone(error)

    def test_n_slash_a_token_is_case_insensitive_missing_data(self):
        for token in ("n/a", "N/A", "n/A"):
            value, error = parse_lab_value(token)
            self.assertIsNone(value)
            self.assertIsNone(error)

    def test_na_token_is_case_insensitive_missing_data(self):
        for token in ("na", "NA", "Na"):
            value, error = parse_lab_value(token)
            self.assertIsNone(value)
            self.assertIsNone(error)

    def test_surrounding_whitespace_is_stripped_before_matching(self):
        value, error = parse_lab_value("  none  ")
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_python_none_input_never_raises_type_error(self):
        value, error = parse_lab_value(None)
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_unparseable_garbage_never_raises_value_error(self):
        value, error = parse_lab_value("abc")
        self.assertIsNone(value)
        self.assertIsNotNone(error)
        self.assertIn("abc", error)

    def test_unparseable_mixed_alphanumeric_never_raises(self):
        value, error = parse_lab_value("45mg/dL")
        self.assertIsNone(value)
        self.assertIsNotNone(error)

    def test_negative_number_casts_cleanly(self):
        value, error = parse_lab_value("-1.5")
        self.assertEqual(value, -1.5)
        self.assertIsNone(error)

    def test_zero_casts_cleanly_and_is_not_missing_data(self):
        value, error = parse_lab_value("0")
        self.assertEqual(value, 0.0)
        self.assertIsNone(error)


class TestRenalFunction(unittest.TestCase):
    """Renal function is resolved from a raw numeric eGFR reading (or
    None) evaluated against a conditional threshold, never a pre-computed
    boolean flag."""

    def test_below_threshold_is_reduced(self):
        result = assess_renal_function(EGFR_THRESHOLD - 0.1)
        self.assertEqual(result["renal_function_status"], "REDUCED")

    def test_at_threshold_is_normal(self):
        # The conditional is strict-less-than: exactly at threshold is NOT abnormal.
        result = assess_renal_function(EGFR_THRESHOLD)
        self.assertEqual(result["renal_function_status"], "NORMAL")

    def test_above_threshold_is_normal(self):
        result = assess_renal_function(90.0)
        self.assertEqual(result["renal_function_status"], "NORMAL")

    def test_none_is_unknown_and_never_flags(self):
        result = assess_renal_function(None)
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_renal_function()
        self.assertEqual(result["renal_function_status"], "UNKNOWN")

    def test_reduced_detail_uses_the_required_wording(self):
        result = assess_renal_function(30.0)
        self.assertIn("Reduced eGFR", result["detail"])
        self.assertIn("requires clinical correlation for renal dose adjustment", result["detail"])
        self.assertNotIn("nephrotoxicity risk", result["detail"].lower())

    def test_reduced_detail_cites_kdigo_reference_threshold(self):
        result = assess_renal_function(30.0)
        self.assertIn("KDIGO 2024", result["detail"])
        self.assertIn(str(EGFR_THRESHOLD), result["detail"])

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function(90.0)["source"], "KDIGO 2024")

    def test_egfr_field_echoes_parsed_value(self):
        self.assertEqual(assess_renal_function(30.0)["egfr"], 30.0)
        self.assertEqual(assess_renal_function(90.0)["egfr"], 90.0)
        self.assertIsNone(assess_renal_function(None)["egfr"])


class TestIsEgfrAbnormal(unittest.TestCase):
    def test_below_threshold_is_abnormal(self):
        self.assertTrue(is_egfr_abnormal(EGFR_THRESHOLD - 0.1))

    def test_at_threshold_is_not_abnormal(self):
        self.assertFalse(is_egfr_abnormal(EGFR_THRESHOLD))

    def test_none_is_not_abnormal(self):
        self.assertFalse(is_egfr_abnormal(None))


class TestHepaticFunction(unittest.TestCase):
    """Hepatic transaminase state is resolved from a raw numeric ALT/AST
    reading (or None) evaluated against a conditional threshold."""

    def test_above_threshold_is_elevated(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD + 0.1)
        self.assertEqual(result["transaminase_status"], "ELEVATED")

    def test_at_threshold_is_normal(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD)
        self.assertEqual(result["transaminase_status"], "NORMAL")

    def test_below_threshold_is_normal(self):
        result = assess_hepatic_function(25.0)
        self.assertEqual(result["transaminase_status"], "NORMAL")

    def test_none_is_unknown_and_never_flags(self):
        result = assess_hepatic_function(None)
        self.assertEqual(result["transaminase_status"], "UNKNOWN")

    def test_elevated_detail_uses_the_required_wording(self):
        result = assess_hepatic_function(150.0)
        self.assertIn("Elevated transaminases", result["detail"])
        self.assertNotIn("hepatic impairment", result["detail"].lower())

    def test_elevated_detail_cites_nfi_reference_threshold(self):
        result = assess_hepatic_function(150.0)
        self.assertIn("NFI", result["detail"])
        self.assertIn(str(ALT_AST_THRESHOLD), result["detail"])

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function(25.0)["source"])

    def test_alt_ast_field_echoes_parsed_value(self):
        self.assertEqual(assess_hepatic_function(150.0)["alt_ast"], 150.0)
        self.assertIsNone(assess_hepatic_function(None)["alt_ast"])


class TestIsAltAstAbnormal(unittest.TestCase):
    def test_above_threshold_is_abnormal(self):
        self.assertTrue(is_alt_ast_abnormal(ALT_AST_THRESHOLD + 0.1))

    def test_at_threshold_is_not_abnormal(self):
        self.assertFalse(is_alt_ast_abnormal(ALT_AST_THRESHOLD))

    def test_none_is_not_abnormal(self):
        self.assertFalse(is_alt_ast_abnormal(None))


class TestBleedingRiskLabs(unittest.TestCase):
    """Coagulation/CBC state is resolved from two independent raw numeric
    readings (or None), each evaluated against its own conditional
    threshold."""

    def test_normal_values_are_normal(self):
        result = assess_bleeding_risk_labs(250.0, 1.0)
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
        result = assess_bleeding_risk_labs(250.0, PT_INR_THRESHOLD)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")

    def test_pt_inr_above_threshold_is_abnormal(self):
        result = assess_bleeding_risk_labs(250.0, PT_INR_THRESHOLD + 0.1)
        self.assertEqual(result["coagulation_cbc_status"], "ABNORMAL")

    def test_one_value_known_normal_other_none_is_normal(self):
        result = assess_bleeding_risk_labs(250.0, None)
        self.assertEqual(result["coagulation_cbc_status"], "NORMAL")
        result2 = assess_bleeding_risk_labs(None, 1.0)
        self.assertEqual(result2["coagulation_cbc_status"], "NORMAL")

    def test_abnormal_detail_uses_the_required_wording(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD - 1, 1.0)
        self.assertIn("Abnormal coagulation/CBC parameters", result["detail"])
        self.assertNotIn("bleeding risk", result["detail"].lower())

    def test_platelets_and_pt_inr_fields_echo_parsed_values(self):
        result = assess_bleeding_risk_labs(100.0, 1.5)
        self.assertEqual(result["platelets"], 100.0)
        self.assertEqual(result["pt_inr"], 1.5)


class TestCoagulationThresholdPredicates(unittest.TestCase):
    def test_platelets_below_threshold_is_abnormal(self):
        self.assertTrue(is_platelets_abnormal(PLATELETS_THRESHOLD - 1))

    def test_platelets_at_threshold_is_not_abnormal(self):
        self.assertFalse(is_platelets_abnormal(PLATELETS_THRESHOLD))

    def test_platelets_none_is_not_abnormal(self):
        self.assertFalse(is_platelets_abnormal(None))

    def test_pt_inr_above_threshold_is_abnormal(self):
        self.assertTrue(is_pt_inr_abnormal(PT_INR_THRESHOLD + 0.1))

    def test_pt_inr_at_threshold_is_not_abnormal(self):
        self.assertFalse(is_pt_inr_abnormal(PT_INR_THRESHOLD))

    def test_pt_inr_none_is_not_abnormal(self):
        self.assertFalse(is_pt_inr_abnormal(None))


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
