"""Exhaustive pytest suite for the PRISM-AIIMS UI-facing state machine.

Streamlit's own widget rendering is verified separately via a live
Playwright pass (see the project's manual verification notes); this suite
instead pins down the pure state -- the module-level constants and pure
functions app.py wires its widgets to -- so that a state-routing exception
(ImportError, NameError, KeyError, or an unexpected value escaping its
declared state space) is caught by `pytest`, not discovered live.

Run with:
    pytest tests/test_ui_state.py -v
"""

import importlib

import pytest

import app
from engine.clinical import (
    ADR_RISK_HIGH,
    ADR_RISK_STANDARD,
    ISOLATED_VERDICT_BASELINE,
    ISOLATED_VERDICT_HIGH,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
    calculate_adr_risk,
)
from engine.triage import (
    CPIC_TESTING_NOT_INDICATED,
    CPIC_TESTING_RECOMMENDED,
    CPIC_TESTING_REQUIRED,
    ETHNICITY_OPTIONS,
    TRIAGE_CONSIDER,
    TRIAGE_HIGH,
    TRIAGE_LOW,
    genomeindia_population_priority,
    triage_pgx_actionability,
)


def test_app_module_imports_without_exception():
    """Regression guard: app.py must import cleanly standalone (outside a
    live `streamlit run` script context) with no ImportError, NameError,
    or other exception escaping module initialization.
    """
    importlib.reload(app)


class TestLayer1LabFlagStateSpace:
    """Every Layer 1 lab parameter is a three-valued state -- Missing Data
    (None), Normal (False), Abnormal (True) -- never a fourth value."""

    def test_lab_flag_options_are_exactly_the_three_named_states(self):
        assert app._LAB_FLAG_OPTIONS == ["Missing Data", "Normal", "Abnormal"]

    def test_lab_flag_state_maps_each_option_to_its_declared_value(self):
        assert app._LAB_FLAG_STATE["Missing Data"] is None
        assert app._LAB_FLAG_STATE["Normal"] is False
        assert app._LAB_FLAG_STATE["Abnormal"] is True

    def test_lab_flag_state_has_no_extra_or_missing_keys(self):
        assert set(app._LAB_FLAG_STATE.keys()) == set(app._LAB_FLAG_OPTIONS)

    @pytest.mark.parametrize("flag", [True, False, None])
    def test_renal_state_transition_never_raises(self, flag):
        result = assess_renal_function(flag)
        assert result["renal_function_status"] in ("REDUCED", "NORMAL", "UNKNOWN")

    @pytest.mark.parametrize("flag", [True, False, None])
    def test_hepatic_state_transition_never_raises(self, flag):
        result = assess_hepatic_function(flag)
        assert result["transaminase_status"] in ("ELEVATED", "NORMAL", "UNKNOWN")

    @pytest.mark.parametrize("platelets_flag", [True, False, None])
    @pytest.mark.parametrize("pt_inr_flag", [True, False, None])
    def test_coagulation_state_transition_never_raises_for_any_combination(self, platelets_flag, pt_inr_flag):
        result = assess_bleeding_risk_labs(platelets_flag, pt_inr_flag)
        assert result["coagulation_cbc_status"] in ("ABNORMAL", "NORMAL", "UNKNOWN")

    def test_abnormal_true_immediately_transitions_to_the_flagged_state(self):
        # "ABNORMAL -> FLAG": True must never resolve to NORMAL or UNKNOWN.
        assert assess_renal_function(True)["renal_function_status"] == "REDUCED"
        assert assess_hepatic_function(True)["transaminase_status"] == "ELEVATED"
        assert assess_bleeding_risk_labs(True, False)["coagulation_cbc_status"] == "ABNORMAL"

    def test_missing_data_never_flags_as_abnormal(self):
        assert assess_renal_function(None)["renal_function_status"] == "UNKNOWN"
        assert assess_hepatic_function(None)["transaminase_status"] == "UNKNOWN"
        assert assess_bleeding_risk_labs(None, None)["coagulation_cbc_status"] == "UNKNOWN"


class TestLayer2IsolatedExecutionContexts:
    """ADATIP and GerontoNet each render an independent verdict; the
    Patient Condition selector app.py exposes is a descriptive label only
    and must never gate either computation."""

    def test_isolated_verdict_vocabulary_is_exactly_two_valued(self):
        result = calculate_adr_risk()
        assert result["adatip_isolated_verdict"] in (ISOLATED_VERDICT_HIGH, ISOLATED_VERDICT_BASELINE)
        assert result["gerontonet_isolated_verdict"] in (ISOLATED_VERDICT_HIGH, ISOLATED_VERDICT_BASELINE)

    def test_adatip_high_never_forces_gerontonet_high(self):
        result = calculate_adr_risk(chronic_lung_disease=True, diuretics=True)
        assert result["adatip_isolated_verdict"] == ISOLATED_VERDICT_HIGH
        assert result["gerontonet_isolated_verdict"] == ISOLATED_VERDICT_BASELINE

    def test_gerontonet_high_never_forces_adatip_high(self):
        result = calculate_adr_risk(
            heart_failure=True, liver_disease=True, renal_failure=True, gte4_comorbid_conditions=True,
        )
        assert result["gerontonet_isolated_verdict"] == ISOLATED_VERDICT_HIGH
        assert result["adatip_isolated_verdict"] == ISOLATED_VERDICT_BASELINE

    def test_missing_layer2_predictors_default_to_baseline_standard(self):
        result = calculate_adr_risk()
        assert result["adr_risk_flag"] == ADR_RISK_STANDARD
        assert result["adatip_isolated_verdict"] == ISOLATED_VERDICT_BASELINE
        assert result["gerontonet_isolated_verdict"] == ISOLATED_VERDICT_BASELINE


class TestLayer2WebSearchModule:
    """A single dropdown selects exactly one of three independent query
    variables; only the selected query's own boolean input is read."""

    def test_query_options_are_exactly_the_three_named_dimensions(self):
        assert app._WEB_SEARCH_QUERY_OPTIONS == ["ADR RISK", "FAMILY RISK", "ALLERGIC RISK"]

    def test_query_key_maps_every_option_to_a_mock_case_report_url(self):
        for option in app._WEB_SEARCH_QUERY_OPTIONS:
            label = app._WEB_SEARCH_QUERY_KEY[option]
            assert label in app._MOCK_CASE_REPORT_QUERIES
            assert app._MOCK_CASE_REPORT_QUERIES[label].startswith("https://")

    def test_no_orphaned_or_missing_query_mappings(self):
        mapped_labels = set(app._WEB_SEARCH_QUERY_KEY.values())
        assert mapped_labels == set(app._MOCK_CASE_REPORT_QUERIES.keys())


class TestLayer3GenotypingRoutingState:
    """Genotyping Results is a strict boolean routing variable: Available
    (Path A, CPIC allele pathway) or Not Available (Path B, Testing-
    Priority triage)."""

    def test_genotyping_availability_is_exactly_two_valued(self):
        assert app.GENOTYPING_AVAILABILITY_OPTIONS == ["Available", "Not Available"]

    @pytest.mark.parametrize("drug", ["Clopidogrel", "Tacrolimus", "Warfarin", "Carbamazepine", "Ibuprofen"])
    def test_every_drug_option_or_out_of_scope_drug_triages_without_raising(self, drug):
        result = triage_pgx_actionability(drug)
        assert result["triage"] in (TRIAGE_HIGH, TRIAGE_CONSIDER, TRIAGE_LOW)
        assert result["cpic_testing_recommendation"] in (
            CPIC_TESTING_REQUIRED, CPIC_TESTING_RECOMMENDED, CPIC_TESTING_NOT_INDICATED,
        )

    def test_drug_options_are_all_represented_in_the_mvp_drug_list(self):
        assert set(app.DRUG_OPTIONS) >= {"Clopidogrel", "Warfarin", "Tacrolimus"}


class TestLayer3GenomeIndiaDecoupling:
    """CRITICAL DECOUPLING: the mock GenomeIndia ethnicity lookup is a pure
    function of ethnicity alone, imported identically by app.py and
    engine.triage -- an ImportError here would be the exact class of bug
    previously (falsely) suspected to be a circular dependency."""

    def test_app_and_engine_triage_expose_the_identical_ethnicity_options(self):
        from engine.triage import ETHNICITY_OPTIONS as engine_options
        assert app.ETHNICITY_OPTIONS is engine_options

    @pytest.mark.parametrize("ethnicity", ETHNICITY_OPTIONS)
    def test_every_ethnicity_resolves_to_a_priority_without_keyerror(self, ethnicity):
        result = genomeindia_population_priority(ethnicity)
        assert result["genomeindia_priority"] in ("High Priority", "Medium Priority", "Low Priority")

    def test_unrecognized_ethnicity_never_raises_keyerror(self):
        result = genomeindia_population_priority("Not A Real Group")
        assert result["genomeindia_priority"] == "Low Priority"

    def test_genomeindia_priority_never_appears_in_triage_output(self):
        result = triage_pgx_actionability("Warfarin")
        assert "genomeindia_priority" not in result

    def test_ethnicity_never_changes_triage_state_for_any_drug(self):
        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin"):
            baseline = triage_pgx_actionability(drug, platelets_abnormal=False, pt_inr_abnormal=False)["triage"]
            for ethnicity in ETHNICITY_OPTIONS:
                genomeindia_population_priority(ethnicity)
                repeated = triage_pgx_actionability(drug, platelets_abnormal=False, pt_inr_abnormal=False)["triage"]
                assert repeated == baseline


class TestFullLayerPipelineMissingDataHandling:
    """A fully blank clinician submission -- every Layer 1 flag Missing
    Data, no Layer 2 predictors, Genotyping Results Not Available -- must
    resolve through all three layers without raising, landing on the safe
    routine-monitoring default."""

    def test_blank_submission_never_raises_across_every_mvp_drug(self):
        adr = calculate_adr_risk()
        assert adr["high_baseline_adr_risk"] is False
        assert adr["adr_risk_flag"] == ADR_RISK_STANDARD

        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin"):
            triage = triage_pgx_actionability(
                drug, None, age=None, weight=None,
                egfr_abnormal=None, alt_ast_abnormal=None,
                platelets_abnormal=None, pt_inr_abnormal=None,
                high_baseline_adr_risk=adr["high_baseline_adr_risk"],
            )
            assert "triage" in triage
            assert "cpic_testing_recommendation" in triage
            assert "contextual_modifier" in triage

        for ethnicity in ETHNICITY_OPTIONS:
            genomeindia = genomeindia_population_priority(ethnicity)
            assert "genomeindia_priority" in genomeindia

    def test_warfarin_blank_submission_lands_on_consider_not_high_or_low(self):
        triage = triage_pgx_actionability(
            "Warfarin", None, age=None, weight=None,
            egfr_abnormal=None, alt_ast_abnormal=None,
            platelets_abnormal=None, pt_inr_abnormal=None,
        )
        assert triage["triage"] == TRIAGE_CONSIDER
        assert triage["cpic_testing_recommendation"] == CPIC_TESTING_RECOMMENDED

    def test_fully_populated_high_risk_submission_never_raises(self):
        adr = calculate_adr_risk(
            age=85, chronic_lung_disease=True, syncope_on_admission=True,
            num_drugs=8, previous_adr_history=True, heart_failure=True,
            allergy_history=True, family_history=True,
        )
        assert adr["high_baseline_adr_risk"] is True

        triage = triage_pgx_actionability(
            "Tacrolimus", ["Fluconazole"], age=85, weight=55.0,
            egfr_abnormal=True, alt_ast_abnormal=True,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        assert triage["triage"] == TRIAGE_HIGH
        assert triage["cpic_testing_recommendation"] == CPIC_TESTING_REQUIRED
        assert len(triage["warnings"]) >= 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
