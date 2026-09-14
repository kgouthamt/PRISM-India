"""Unit tests for engine.rules.evaluate_prescription.

Run with:
    python -m unittest tests.test_rules -v

Or discover every test module under tests/:
    python -m unittest discover -s tests -t . -v
"""

import unittest

from engine.rules import RISK_HIGH, RISK_NO_ALERT, RISK_UNKNOWN, evaluate_prescription


class TestClopidogrelCYP2C19Genotype(unittest.TestCase):
    def test_normal_metabolizer_returns_standard_dose(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*1/*1")
        self.assertEqual(result["risk"], RISK_NO_ALERT)
        self.assertEqual(result["recommendation_and_dosage"], "Standard dose: 75 mg/day")
        self.assertEqual(result["evidence_type"], "CYP2C19 Genotype")

    def test_intermediate_metabolizer_returns_alternative_agent(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*1/*2")
        self.assertEqual(result["risk"], RISK_HIGH)
        rec = result["recommendation_and_dosage"]
        self.assertIn("prasugrel", rec.lower())
        self.assertIn("ticagrelor", rec.lower())
        # Priority 1: the old blanket "225 mg/day" escalation must be gone.
        self.assertNotIn("225", rec)

    def test_poor_metabolizer_returns_avoid_and_alternative_agent(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*2/*2")
        self.assertEqual(result["risk"], RISK_HIGH)
        rec = result["recommendation_and_dosage"]
        self.assertIn("avoid clopidogrel", rec.lower())
        self.assertIn("prasugrel", rec.lower())
        self.assertNotIn("225", rec)


class TestHLAGenotypeAlerts(unittest.TestCase):
    def test_hla_positive_is_high_risk_alert(self):
        result = evaluate_prescription("Carbamazepine", "Genotype", "Positive")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("Stevens-Johnson", result["reason"])

    def test_hla_negative_is_no_actionable_alert(self):
        result = evaluate_prescription("Carbamazepine", "Genotype", "Negative")
        self.assertEqual(result["risk"], RISK_NO_ALERT)

    def test_allopurinol_positive_uses_exact_required_wording(self):
        result = evaluate_prescription("Allopurinol", "Genotype", "Positive")
        self.assertEqual(
            result["recommendation_and_dosage"],
            "Avoid allopurinol; consider alternative therapy based on clinical context.",
        )
        self.assertNotIn("febuxostat", result["recommendation_and_dosage"].lower())


class TestFallbackPaths(unittest.TestCase):
    def test_unknown_genotype_returns_unknown(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*99/*99")
        self.assertEqual(result["risk"], RISK_UNKNOWN)
        self.assertIsNone(result["recommendation_and_dosage"])

    def test_malformed_pru_returns_unknown(self):
        result = evaluate_prescription("Clopidogrel", "Phenotype", "not-a-number")
        self.assertEqual(result["risk"], RISK_UNKNOWN)

    def test_unsupported_drug_returns_unknown(self):
        result = evaluate_prescription("Ibuprofen", "Genotype", "whatever")
        self.assertEqual(result["risk"], RISK_UNKNOWN)


class TestNoActionableAlertReplacesSafe(unittest.TestCase):
    def test_risk_no_alert_constant_value(self):
        self.assertEqual(RISK_NO_ALERT, "NO ACTIONABLE ALERT")

    def test_no_result_ever_reports_the_old_safe_label(self):
        for drug, test_type, test_result in [
            ("Clopidogrel", "Genotype", "*1/*1"),
            ("Carbamazepine", "Genotype", "Negative"),
            ("Tacrolimus", "Genotype", "*3/*3"),
            ("Tacrolimus", "Phenotype", "10 ng/mL"),
        ]:
            result = evaluate_prescription(drug, test_type, test_result)
            self.assertNotEqual(result["risk"], "SAFE")


class TestTacrolimusPGxAndTDMAreSeparate(unittest.TestCase):
    def test_cyp3a5_expresser_genotype_is_a_pgx_starting_dose_alert(self):
        result = evaluate_prescription("Tacrolimus", "Genotype", "*1/*3")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("starting dose", result["recommendation_and_dosage"].lower())
        self.assertIn("PGx", result["evidence_type"])

    def test_cyp3a5_non_expresser_genotype_is_no_actionable_alert(self):
        result = evaluate_prescription("Tacrolimus", "Genotype", "*3/*3")
        self.assertEqual(result["risk"], RISK_NO_ALERT)
        self.assertIn("PGx", result["evidence_type"])

    def test_trough_level_is_a_distinct_tdm_alert(self):
        low = evaluate_prescription("Tacrolimus", "Phenotype", "3 ng/mL")
        high = evaluate_prescription("Tacrolimus", "Phenotype", "18 ng/mL")
        in_range = evaluate_prescription("Tacrolimus", "Phenotype", "10 ng/mL")
        self.assertEqual(low["risk"], RISK_HIGH)
        self.assertEqual(high["risk"], RISK_HIGH)
        self.assertEqual(in_range["risk"], RISK_NO_ALERT)
        for result in (low, high, in_range):
            self.assertIn("TDM", result["evidence_type"])
            # The TDM path must never be confused with the genotype PGx path.
            self.assertNotIn("PGx", result["evidence_type"])


if __name__ == "__main__":
    unittest.main()
