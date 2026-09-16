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


class TestWarfarinCombinedGenotype(unittest.TestCase):
    def test_normal_cyp2c9_and_vkorc1_is_no_actionable_alert(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*1;VKORC1=GG")
        self.assertEqual(result["risk"], RISK_NO_ALERT)
        self.assertEqual(
            result["recommendation_and_dosage"],
            "Standard initial dosing with routine INR-guided titration",
        )

    def test_intermediate_cyp2c9_increases_sensitivity(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*2;VKORC1=GG")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("30-50%", result["recommendation_and_dosage"])

    def test_vkorc1_heterozygous_alone_increases_sensitivity(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*1;VKORC1=AG")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("30-50%", result["recommendation_and_dosage"])

    def test_poor_cyp2c9_is_highly_increased_sensitivity(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*2/*2;VKORC1=GG")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("50-80%", result["recommendation_and_dosage"])

    def test_vkorc1_homozygous_variant_is_highly_increased_sensitivity(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*1;VKORC1=AA")
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("50-80%", result["recommendation_and_dosage"])

    def test_unrecognized_diplotype_is_unknown(self):
        result = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*9/*9;VKORC1=GG")
        self.assertEqual(result["risk"], RISK_UNKNOWN)

    def test_malformed_genotype_string_is_unknown(self):
        result = evaluate_prescription("Warfarin", "Genotype", "garbage")
        self.assertEqual(result["risk"], RISK_UNKNOWN)

    def test_phenotype_is_not_modeled_for_warfarin(self):
        result = evaluate_prescription("Warfarin", "Phenotype", "2.5")
        self.assertEqual(result["risk"], RISK_UNKNOWN)


class TestRuleProvenance(unittest.TestCase):
    """Every matched rule carries its own granular provenance -- no single
    blanket 'CPIC' label describing the whole engine."""

    def test_matched_rule_has_guideline_url_evidence_date_and_hash(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*1/*1")
        self.assertTrue(result["guideline_url"].startswith("http"))
        self.assertRegex(result["evidence_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIsInstance(result["rule_hash"], str)
        self.assertTrue(len(result["rule_hash"]) > 0)

    def test_unknown_result_has_no_provenance(self):
        result = evaluate_prescription("Clopidogrel", "Genotype", "*99/*99")
        self.assertIsNone(result["guideline_url"])
        self.assertIsNone(result["evidence_date"])
        self.assertIsNone(result["rule_hash"])

    def test_different_rules_have_different_hashes(self):
        normal = evaluate_prescription("Clopidogrel", "Genotype", "*1/*1")
        poor = evaluate_prescription("Clopidogrel", "Genotype", "*2/*2")
        self.assertNotEqual(normal["rule_hash"], poor["rule_hash"])

    def test_same_rule_is_deterministic(self):
        first = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*1;VKORC1=GG")
        second = evaluate_prescription("Warfarin", "Genotype", "CYP2C9=*1/*1;VKORC1=GG")
        self.assertEqual(first["rule_hash"], second["rule_hash"])

    def test_no_bare_cpic_label_on_the_engine_constants(self):
        from engine.rules import EVIDENCE_SOURCE, GUIDELINE_VERSION
        self.assertNotEqual(GUIDELINE_VERSION.strip(), "CPIC")
        self.assertNotEqual(EVIDENCE_SOURCE.strip(), "CPIC")


class TestTacrolimusIndicationAwareTdm(unittest.TestCase):
    """The TDM target range is indication-dependent, not a single universal cutoff."""

    def test_kidney_transplant_target_matches_original_default(self):
        result = evaluate_prescription(
            "Tacrolimus", "Phenotype", "10 ng/mL", indication="Kidney Transplant",
        )
        self.assertEqual(result["risk"], RISK_NO_ALERT)

    def test_kidney_transplant_18_is_supratherapeutic(self):
        result = evaluate_prescription(
            "Tacrolimus", "Phenotype", "18 ng/mL", indication="Kidney Transplant",
        )
        self.assertEqual(result["risk"], RISK_HIGH)
        self.assertIn("Kidney Transplant", result["reason"])

    def test_liver_transplant_18_is_within_the_wider_target_range(self):
        result = evaluate_prescription(
            "Tacrolimus", "Phenotype", "18 ng/mL", indication="Liver Transplant",
        )
        self.assertEqual(result["risk"], RISK_NO_ALERT)
        self.assertIn("Liver Transplant", result["reason"])

    def test_liver_transplant_22_is_supratherapeutic(self):
        result = evaluate_prescription(
            "Tacrolimus", "Phenotype", "22 ng/mL", indication="Liver Transplant",
        )
        self.assertEqual(result["risk"], RISK_HIGH)

    def test_missing_indication_falls_back_to_kidney_transplant_default(self):
        with_none = evaluate_prescription("Tacrolimus", "Phenotype", "18 ng/mL")
        with_kidney = evaluate_prescription(
            "Tacrolimus", "Phenotype", "18 ng/mL", indication="Kidney Transplant",
        )
        self.assertEqual(with_none["risk"], with_kidney["risk"])
        self.assertEqual(with_none["risk"], RISK_HIGH)

    def test_unrecognized_indication_falls_back_to_default_without_crashing(self):
        result = evaluate_prescription(
            "Tacrolimus", "Phenotype", "10 ng/mL", indication="Some Other Organ",
        )
        self.assertEqual(result["risk"], RISK_NO_ALERT)


class TestG6pdReferenceRangeAware(unittest.TestCase):
    """G6PD phenotype interpretation uses the ordering lab's own reference
    range when supplied, rather than a single fixed cutoff for every lab."""

    def test_default_threshold_matches_original_behavior(self):
        result = evaluate_prescription("Primaquine", "Phenotype", "8%")
        self.assertEqual(result["risk"], RISK_HIGH)
        result2 = evaluate_prescription("Primaquine", "Phenotype", "15%")
        self.assertEqual(result2["risk"], RISK_NO_ALERT)

    def test_custom_reference_range_raises_the_deficiency_cutoff(self):
        # 12% is above the MVP default of 10% but below a lab whose own
        # lower limit of normal is 15%.
        result = evaluate_prescription(
            "Primaquine", "Phenotype", "12%", reference_range_low=15.0,
        )
        self.assertEqual(result["risk"], RISK_HIGH)

    def test_custom_reference_range_can_lower_the_deficiency_cutoff(self):
        result = evaluate_prescription(
            "Rasburicase", "Phenotype", "8%", reference_range_low=5.0,
        )
        self.assertEqual(result["risk"], RISK_NO_ALERT)

    def test_reference_range_ignored_for_genotype(self):
        result = evaluate_prescription(
            "Primaquine", "Genotype", "Normal", reference_range_low=50.0,
        )
        self.assertEqual(result["risk"], RISK_NO_ALERT)


if __name__ == "__main__":
    unittest.main()
