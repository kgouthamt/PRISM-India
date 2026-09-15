"""Unit tests for engine.triage (Tier 3: PGx Actionability Triage)."""

import unittest

from engine.triage import TRIAGE_CONSIDER, TRIAGE_HIGH, TRIAGE_LOW, triage_pgx_actionability


class TestClopidogrelTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Clopidogrel")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_surfaces_omeprazole_ddi(self):
        result = triage_pgx_actionability("Clopidogrel", ["Omeprazole"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)
        self.assertEqual(len(result["ddi_findings"]), 1)


class TestTacrolimusTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Tacrolimus")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_surfaces_nephrotoxicity_risk(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=25)
        renal_finding = result["clinical_findings"][0]
        self.assertEqual(renal_finding["nephrotoxicity_risk"], "HIGH")

    def test_surfaces_hepatic_impairment(self):
        result = triage_pgx_actionability("Tacrolimus", alt=300, ast=280, total_bilirubin=3.0)
        hepatic_finding = result["clinical_findings"][1]
        self.assertEqual(hepatic_finding["impairment"], "SEVERE")


class TestWarfarinTriage(unittest.TestCase):
    def test_low_risk_defaults_to_consider(self):
        result = triage_pgx_actionability("Warfarin", inr=1.0, platelets=250, hemoglobin=14)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_severe_ddi_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Amiodarone"], inr=1.0, platelets=250, hemoglobin=14)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_nsaid_ddi_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Ibuprofen"], inr=1.0, platelets=250, hemoglobin=14)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_high_baseline_bleeding_risk_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", inr=1.6, platelets=250, hemoglobin=14)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_no_risk_factors_never_reaches_low_priority(self):
        # Warfarin PGx can always inform an initial dose to some degree --
        # CONSIDER is the floor, never LOW PRIORITY.
        result = triage_pgx_actionability("Warfarin")
        self.assertIn(result["triage"], (TRIAGE_CONSIDER, TRIAGE_HIGH))


class TestOutOfScopeDrug(unittest.TestCase):
    def test_unmodeled_drug_is_low_priority(self):
        result = triage_pgx_actionability("Ibuprofen")
        self.assertEqual(result["triage"], TRIAGE_LOW)
        self.assertEqual(result["ddi_findings"], [])


if __name__ == "__main__":
    unittest.main()
