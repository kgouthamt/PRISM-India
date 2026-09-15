"""Unit tests for engine.ddi (Tier 2: drug-drug interactions)."""

import json
import unittest

from engine.ddi import check_drug_interactions


class TestDrugInteractions(unittest.TestCase):
    def test_clopidogrel_omeprazole_is_a_major_finding(self):
        findings = check_drug_interactions("Clopidogrel", ["Omeprazole"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MAJOR")
        self.assertIn("omeprazole", findings[0]["matched_medications"])

    def test_warfarin_amiodarone_is_a_major_finding(self):
        findings = check_drug_interactions("Warfarin", ["Amiodarone"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MAJOR")

    def test_warfarin_nsaid_is_a_major_finding(self):
        findings = check_drug_interactions("Warfarin", ["Ibuprofen"])
        self.assertEqual(len(findings), 1)
        self.assertIn("ibuprofen", findings[0]["matched_medications"])

    def test_no_matching_medication_returns_empty(self):
        findings = check_drug_interactions("Clopidogrel", ["Metformin"])
        self.assertEqual(findings, [])

    def test_no_concurrent_medications_returns_empty(self):
        findings = check_drug_interactions("Clopidogrel", [])
        self.assertEqual(findings, [])

    def test_drug_outside_ddi_table_returns_empty(self):
        findings = check_drug_interactions("Ibuprofen", ["Omeprazole"])
        self.assertEqual(findings, [])

    def test_case_insensitive_matching(self):
        findings = check_drug_interactions("clopidogrel", ["OMEPRAZOLE"])
        self.assertEqual(len(findings), 1)

    def test_findings_are_json_serializable(self):
        findings = check_drug_interactions("Warfarin", ["Amiodarone", "Ibuprofen"])
        json.dumps(findings)  # must not raise
        self.assertEqual(len(findings), 2)


if __name__ == "__main__":
    unittest.main()
