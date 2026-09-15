"""Unit tests for engine.clinical (Tier 1: objective routine clinical data)."""

import unittest

from engine.clinical import (
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
)


class TestRenalFunction(unittest.TestCase):
    def test_normal_rft_egfr_is_low_risk(self):
        result = assess_renal_function("Normal")
        self.assertEqual(result["nephrotoxicity_risk"], "LOW")

    def test_abnormal_rft_egfr_is_high_risk(self):
        result = assess_renal_function("Abnormal")
        self.assertEqual(result["nephrotoxicity_risk"], "HIGH")

    def test_unknown_rft_egfr_is_unknown_risk(self):
        result = assess_renal_function("Unknown")
        self.assertEqual(result["nephrotoxicity_risk"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_renal_function()
        self.assertEqual(result["nephrotoxicity_risk"], "UNKNOWN")

    def test_garbage_input_normalizes_to_unknown(self):
        result = assess_renal_function("not a category")
        self.assertEqual(result["rft_egfr"], "Unknown")

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function("Normal")["source"], "KDIGO 2024")


class TestHepaticFunction(unittest.TestCase):
    def test_normal_lft_is_low_risk(self):
        result = assess_hepatic_function("Normal")
        self.assertEqual(result["impairment_risk"], "LOW")

    def test_abnormal_lft_is_high_risk(self):
        result = assess_hepatic_function("Abnormal")
        self.assertEqual(result["impairment_risk"], "HIGH")

    def test_unknown_lft_is_unknown_risk(self):
        result = assess_hepatic_function("Unknown")
        self.assertEqual(result["impairment_risk"], "UNKNOWN")

    def test_default_is_unknown(self):
        result = assess_hepatic_function()
        self.assertEqual(result["impairment_risk"], "UNKNOWN")

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function("Normal")["source"])


class TestBleedingRiskLabs(unittest.TestCase):
    def test_normal_categories_are_low_risk(self):
        result = assess_bleeding_risk_labs("Normal", "Normal")
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")
        self.assertEqual(result["flags"], [])

    def test_unknown_categories_do_not_escalate(self):
        result = assess_bleeding_risk_labs("Unknown", "Unknown")
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")

    def test_abnormal_cbc_platelets_is_high_risk(self):
        result = assess_bleeding_risk_labs("Abnormal", "Normal")
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_abnormal_pt_inr_aptt_category_is_high_risk(self):
        result = assess_bleeding_risk_labs("Normal", "Abnormal")
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_numeric_pt_inr_aptt_above_threshold_is_high_risk(self):
        result = assess_bleeding_risk_labs("Normal", 1.6)
        self.assertEqual(result["pt_inr_aptt"], "Abnormal")
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_numeric_pt_inr_aptt_below_threshold_is_normal(self):
        result = assess_bleeding_risk_labs("Normal", 1.0)
        self.assertEqual(result["pt_inr_aptt"], "Normal")
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")

    def test_non_numeric_pt_inr_aptt_falls_back_to_unknown(self):
        result = assess_bleeding_risk_labs("Normal", "not-a-number")
        self.assertEqual(result["pt_inr_aptt"], "Unknown")

    def test_default_pt_inr_aptt_is_unknown(self):
        result = assess_bleeding_risk_labs("Normal")
        self.assertEqual(result["pt_inr_aptt"], "Unknown")


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
