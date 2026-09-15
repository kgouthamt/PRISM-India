"""Unit tests for engine.clinical (Tier 1: routine lab assessment)."""

import unittest

from engine.clinical import assess_bleeding_risk_labs, assess_hepatic_function, assess_renal_function


class TestRenalFunction(unittest.TestCase):
    def test_normal_egfr_is_low_risk(self):
        result = assess_renal_function(95)
        self.assertEqual(result["stage"], "G1")
        self.assertEqual(result["nephrotoxicity_risk"], "LOW")

    def test_moderately_decreased_egfr_is_high_risk(self):
        result = assess_renal_function(35)
        self.assertEqual(result["stage"], "G3b")
        self.assertEqual(result["nephrotoxicity_risk"], "HIGH")

    def test_kidney_failure_egfr_is_high_risk(self):
        result = assess_renal_function(8)
        self.assertEqual(result["stage"], "G5")
        self.assertEqual(result["nephrotoxicity_risk"], "HIGH")

    def test_missing_egfr_is_unknown(self):
        result = assess_renal_function(None)
        self.assertEqual(result["nephrotoxicity_risk"], "UNKNOWN")

    def test_source_is_kdigo_2024(self):
        self.assertEqual(assess_renal_function(90)["source"], "KDIGO 2024")


class TestHepaticFunction(unittest.TestCase):
    def test_normal_lfts_are_no_impairment(self):
        result = assess_hepatic_function(20, 20, 0.8)
        self.assertEqual(result["impairment"], "NONE")

    def test_markedly_elevated_lfts_are_severe_impairment(self):
        result = assess_hepatic_function(300, 280, 3.0)
        self.assertEqual(result["impairment"], "SEVERE")

    def test_moderately_elevated_lfts_are_moderate_impairment(self):
        result = assess_hepatic_function(150, 140, 2.0)
        self.assertEqual(result["impairment"], "MODERATE")

    def test_incomplete_panel_is_unknown(self):
        result = assess_hepatic_function(None, None, None)
        self.assertEqual(result["impairment"], "UNKNOWN")

    def test_source_is_cdsco_nfi(self):
        self.assertIn("CDSCO", assess_hepatic_function(20, 20, 0.8)["source"])


class TestBleedingRiskLabs(unittest.TestCase):
    def test_normal_labs_are_low_risk(self):
        result = assess_bleeding_risk_labs(1.0, 250, 14)
        self.assertEqual(result["baseline_bleeding_risk"], "LOW")
        self.assertEqual(result["flags"], [])

    def test_elevated_inr_is_high_risk(self):
        result = assess_bleeding_risk_labs(1.6, 250, 14)
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_thrombocytopenia_is_high_risk(self):
        result = assess_bleeding_risk_labs(1.0, 80, 14)
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")

    def test_anemia_is_high_risk(self):
        result = assess_bleeding_risk_labs(1.0, 250, 8)
        self.assertEqual(result["baseline_bleeding_risk"], "HIGH")


if __name__ == "__main__":
    unittest.main()
