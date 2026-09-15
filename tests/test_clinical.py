"""Unit tests for engine.clinical (Tier 1: exact numeric routine labs)."""

import unittest

from engine.clinical import (
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    PLATELETS_THRESHOLD,
    PT_INR_THRESHOLD,
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
)


class TestRenalFunction(unittest.TestCase):
    def test_egfr_at_threshold_is_low_risk(self):
        result = assess_renal_function(EGFR_THRESHOLD)
        self.assertEqual(result["nephrotoxicity_risk"], "LOW")

    def test_egfr_just_below_threshold_is_high_risk(self):
        result = assess_renal_function(EGFR_THRESHOLD - 0.1)
        self.assertEqual(result["nephrotoxicity_risk"], "HIGH")

    def test_egfr_well_above_threshold_is_low_risk(self):
        result = assess_renal_function(90)
        self.assertEqual(result["nephrotoxicity_risk"], "LOW")

    def test_egfr_none_is_unknown_and_never_flags(self):
        result = assess_renal_function(None)
        self.assertEqual(result["nephrotoxicity_risk"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_renal_function()
        self.assertEqual(result["nephrotoxicity_risk"], "UNKNOWN")

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function(90)["source"], "KDIGO 2024")


class TestHepaticFunction(unittest.TestCase):
    def test_alt_ast_at_threshold_is_low_risk(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD)
        self.assertEqual(result["impairment_risk"], "LOW")

    def test_alt_ast_just_above_threshold_is_high_risk(self):
        result = assess_hepatic_function(ALT_AST_THRESHOLD + 0.1)
        self.assertEqual(result["impairment_risk"], "HIGH")

    def test_alt_ast_well_above_threshold_is_high_risk(self):
        result = assess_hepatic_function(150)
        self.assertEqual(result["impairment_risk"], "HIGH")

    def test_alt_ast_none_is_unknown_and_never_flags(self):
        result = assess_hepatic_function(None)
        self.assertEqual(result["impairment_risk"], "UNKNOWN")

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function(25)["source"])


class TestBleedingRiskLabs(unittest.TestCase):
    def test_normal_values_are_low_risk(self):
        result = assess_bleeding_risk_labs(250, 1.0)
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")
        self.assertEqual(result["flags"], [])

    def test_both_none_is_unknown_and_never_flags(self):
        result = assess_bleeding_risk_labs(None, None)
        self.assertEqual(result["baseline_bleeding_risk"], "UNKNOWN")
        self.assertEqual(result["flags"], [])

    def test_platelets_at_threshold_is_low_risk(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD, 1.0)
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")

    def test_platelets_below_threshold_is_high_risk(self):
        result = assess_bleeding_risk_labs(PLATELETS_THRESHOLD - 1, 1.0)
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_pt_inr_at_threshold_is_low_risk(self):
        result = assess_bleeding_risk_labs(250, PT_INR_THRESHOLD)
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")

    def test_pt_inr_above_threshold_is_high_risk(self):
        result = assess_bleeding_risk_labs(250, PT_INR_THRESHOLD + 0.1)
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_one_value_known_normal_other_unknown_is_low_risk(self):
        result = assess_bleeding_risk_labs(250, None)
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")
        result2 = assess_bleeding_risk_labs(None, 1.0)
        self.assertEqual(result2["baseline_bleeding_risk"], "LOW")


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


if __name__ == "__main__":
    unittest.main()
