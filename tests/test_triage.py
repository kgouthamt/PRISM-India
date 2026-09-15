"""Unit tests for engine.triage (Tier 3: PGx Actionability Triage).

Covers only objective, routine inputs (drug, exact numeric labs, DDIs,
age/weight) -- there is deliberately no test exercising a "previous ADR" or
"previous treatment failure" parameter, since triage_pgx_actionability has
no such parameter to begin with.
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
        result = triage_pgx_actionability("Tacrolimus", egfr=90, alt_ast=25)
        self.assertEqual(result["warnings"], [])

    def test_unknown_labs_produce_no_warnings_and_no_crash(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=None, alt_ast=None)
        self.assertEqual(result["warnings"], [])

    def test_low_egfr_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("KDIGO" in w for w in result["warnings"]))

    def test_high_alt_ast_triggers_mandatory_tdm_warning(self):
        result = triage_pgx_actionability("Tacrolimus", alt_ast=150)
        self.assertTrue(any("mandatory" in w.lower() for w in result["warnings"]))
        self.assertTrue(any("NFI" in w for w in result["warnings"]))

    def test_both_abnormal_produce_two_warnings(self):
        result = triage_pgx_actionability("Tacrolimus", egfr=35, alt_ast=150)
        self.assertEqual(len(result["warnings"]), 2)


class TestWarfarinTriage(unittest.TestCase):
    def test_low_risk_defaults_to_consider(self):
        result = triage_pgx_actionability("Warfarin", platelets=250, pt_inr=1.0)
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_unknown_labs_do_not_escalate(self):
        result = triage_pgx_actionability("Warfarin")
        self.assertEqual(result["triage"], TRIAGE_CONSIDER)

    def test_low_platelets_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", platelets=100)
        self.assertEqual(result["triage"], TRIAGE_HIGH)

    def test_high_pt_inr_escalates_to_high_priority(self):
        result = triage_pgx_actionability("Warfarin", pt_inr=1.5)
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


class TestNoneValuesNeverCrash(unittest.TestCase):
    def test_all_none_across_every_drug(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin", "Ibuprofen"):
            result = triage_pgx_actionability(
                drug, None, age=None, weight=None, egfr=None,
                alt_ast=None, platelets=None, pt_inr=None,
            )
            self.assertIn("triage", result)


class TestOutOfScopeDrug(unittest.TestCase):
    def test_unmodeled_drug_is_low_priority(self):
        result = triage_pgx_actionability("Ibuprofen")
        self.assertEqual(result["triage"], TRIAGE_LOW)
        self.assertEqual(result["ddi_findings"], [])


if __name__ == "__main__":
    unittest.main()
