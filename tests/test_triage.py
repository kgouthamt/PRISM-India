"""Unit tests for engine.triage (Tier 3: PGx Actionability Triage).

Covers only objective, routine inputs (drug, labs, DDIs, age/weight) --
there is deliberately no test exercising a "previous ADR" or "previous
treatment failure" parameter, since triage_pgx_actionability has no such
parameter to begin with.
"""

import unittest

from engine.triage import TRIAGE_CONSIDER, TRIAGE_HIGH, TRIAGE_LOW, triage_pgx_actionability


class TestClopidogrelTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Clopidogrel")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_surfaces_omeprazole_ddi_as_a_warning(self):
        result = triage_pgx_actionability("Clopidogrel", ["Omeprazole"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)
        self.assertEqual(len(result["ddi_findings"]), 1)
        self.assertTrue(any("CYP2C19-inhibiting" in w for w in result["warnings"]))


class TestTacrolimusTriage(unittest.TestCase):
    def test_always_high_priority(self):
        result = triage_pgx_actionability("Tacrolimus")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_normal_labs_produce_no_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", lft="Normal", rft_egfr="Normal")
        self.assertEqual(result["warnings"], [])

    def test_abnormal_rft_egfr_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", rft_egfr="Abnormal")
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("KDIGO" in w for w in result["warnings"]))

    def test_abnormal_lft_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", lft="Abnormal")
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("NFI" in w for w in result["warnings"]))

    def test_both_abnormal_produce_two_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", lft="Abnormal", rft_egfr="Abnormal")
        self.assertEqual(len(result["warnings"]), 2)


class TestWarfarinTriage(unittest.TestCase):
    def test_low_risk_defaults_to_consider(self):
        result = triage_pgx_actionability("Warfarin", cbc_platelets="Normal", pt_inr_aptt="Normal")
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_unknown_labs_do_not_escalate(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_abnormal_pt_inr_aptt_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", pt_inr_aptt="Abnormal")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_numeric_pt_inr_aptt_above_threshold_escalates(self):
        result = triage_pgx_actionability("Warfarin", pt_inr_aptt=1.6)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_abnormal_cbc_platelets_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", cbc_platelets="Abnormal")
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_severe_ddi_amiodarone_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Amiodarone"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_severe_ddi_nsaid_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", ["Ibuprofen"])
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_no_risk_factors_never_reaches_low_priority(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertIn(result["triage"], (TRIAGE_CONSIDER, TRIAGE_HIGH))


class TestAgeWeightContextSurfacesAcrossDrugs(unittest.TestCase):
    def test_pediatric_and_low_weight_flags_appear_in_rationale(self):
        result = triage_pgx_actionability("Clopidogrel", age=10, weight=25)
        self.assertTrue(any("Pediatric" in line for line in result["rationale"]))
        self.assertTrue(any("Low body weight" in line for line in result["rationale"]))

    def test_age_weight_finding_is_always_present(self):
        result = triage_pgx_actionability("Clopidogrel")
        sources = [f.get("source") for f in result["clinical_findings"]]
        self.assertTrue(any("FDA" in (s or "") for s in sources))


class TestOutOfScopeDrug(unittest.TestCase):
    def test_unmodeled_drug_is_low_priority(self):
        result = triage_pgx_actionability("Ibuprofen")
        self.assertEqual(result["triage"], TRIAGE_LOW)
        self.assertEqual(result["ddi_findings"], [])


if __name__ == "__main__":
    unittest.main()
