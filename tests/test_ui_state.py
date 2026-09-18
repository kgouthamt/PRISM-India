"""Exhaustive pytest suite for the PRISM-AIIMS UI-facing state machine.

Streamlit's own widget rendering is verified separately via a live
Playwright pass (see the project's manual verification notes); this suite
instead pins down the pure state -- the module-level constants and pure
functions app.py wires its widgets to -- so that a type-casting exception
(ValueError, TypeError) or a state-routing exception (ImportError,
NameError, KeyError) is caught by `pytest`, not discovered live.

Run with:
    pytest tests/test_ui_state.py -v
"""

import importlib

import pytest

import app
from engine.clinical import (
    ADR_RISK_HIGH,
    ADR_RISK_STANDARD,
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    ISOLATED_VERDICT_BASELINE,
    ISOLATED_VERDICT_HIGH,
    PLATELETS_THRESHOLD,
    PT_INR_THRESHOLD,
    calculate_adr_risk,
    is_alt_ast_abnormal,
    is_egfr_abnormal,
    is_platelets_abnormal,
    is_pt_inr_abnormal,
    parse_lab_value,
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


class TestLayer1NumericLabInputTypeCasting:
    """Every Layer 1 lab parameter is ingested as raw text and type-cast
    to a float via parse_lab_value() -- string-to-float conversion with
    explicit exception handling, never a ValueError/TypeError escaping to
    the caller."""

    @pytest.mark.parametrize("token", ["", "   ", "none", "None", "NONE", "n/a", "N/A", "na", "NA"])
    def test_missing_data_tokens_cast_to_none_without_raising(self, token):
        value, error = parse_lab_value(token)
        assert value is None
        assert error is None

    def test_python_none_input_never_raises_type_error(self):
        value, error = parse_lab_value(None)
        assert value is None
        assert error is None

    @pytest.mark.parametrize("token", ["abc", "45mg/dL", "--", "1.2.3"])
    def test_unparseable_garbage_never_raises_value_error(self, token):
        value, error = parse_lab_value(token)
        assert value is None
        assert error is not None

    @pytest.mark.parametrize("token,expected", [("45", 45.0), ("59.9", 59.9), ("-1.5", -1.5), ("0", 0.0)])
    def test_valid_numeric_literals_cast_cleanly(self, token, expected):
        value, error = parse_lab_value(token)
        assert value == expected
        assert error is None

    def test_egfr_exactly_at_threshold_is_not_abnormal(self):
        # Boundary value: the conditional is strict less-than.
        assert is_egfr_abnormal(EGFR_THRESHOLD) is False
        assert is_egfr_abnormal(EGFR_THRESHOLD - 0.01) is True

    def test_alt_ast_exactly_at_threshold_is_not_abnormal(self):
        # Boundary value: the conditional is strict greater-than.
        assert is_alt_ast_abnormal(ALT_AST_THRESHOLD) is False
        assert is_alt_ast_abnormal(ALT_AST_THRESHOLD + 0.01) is True

    def test_platelets_exactly_at_threshold_is_not_abnormal(self):
        assert is_platelets_abnormal(PLATELETS_THRESHOLD) is False
        assert is_platelets_abnormal(PLATELETS_THRESHOLD - 0.01) is True

    def test_pt_inr_exactly_at_threshold_is_not_abnormal(self):
        assert is_pt_inr_abnormal(PT_INR_THRESHOLD) is False
        assert is_pt_inr_abnormal(PT_INR_THRESHOLD + 0.01) is True

    @pytest.mark.parametrize("predicate", [is_egfr_abnormal, is_alt_ast_abnormal, is_platelets_abnormal, is_pt_inr_abnormal])
    def test_none_never_satisfies_any_conditional_threshold(self, predicate):
        assert predicate(None) is False

    def test_app_exposes_the_numeric_input_helper_not_the_old_flag_helper(self):
        assert hasattr(app, "_lab_numeric_input")
        assert not hasattr(app, "_lab_flag_input")
        assert not hasattr(app, "_LAB_FLAG_OPTIONS")
        assert not hasattr(app, "_LAB_FLAG_STATE")


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


class TestLayer2FreeTextSearchModule:
    """The Web Search module ingests an opaque free-text query -- no
    predefined dropdown vocabulary -- and never parses the submitted text
    against a fixed token set."""

    def test_web_search_mockup_takes_a_single_context_flag(self):
        import inspect
        sig = inspect.signature(app._web_search_mockup)
        assert list(sig.parameters) == ["high_risk_context"]

    def test_dropdown_constants_no_longer_exist(self):
        assert not hasattr(app, "_WEB_SEARCH_QUERY_OPTIONS")
        assert not hasattr(app, "_WEB_SEARCH_QUERY_KEY")
        assert not hasattr(app, "_MOCK_CASE_REPORT_QUERIES")

    def test_urllib_parse_is_imported_for_query_encoding(self):
        assert hasattr(app, "urllib")


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
            baseline = triage_pgx_actionability(drug, platelets=250.0, pt_inr=1.0)["triage"]
            for ethnicity in ETHNICITY_OPTIONS:
                genomeindia_population_priority(ethnicity)
                repeated = triage_pgx_actionability(drug, platelets=250.0, pt_inr=1.0)["triage"]
                assert repeated == baseline


class TestFullLayerPipelineMissingDataHandling:
    """A fully blank clinician submission -- every Layer 1 field empty
    (parsing to None), no Layer 2 predictors, Genotyping Results Not
    Available -- must resolve through all three layers without raising,
    landing on the safe routine-monitoring default."""

    def test_blank_submission_never_raises_across_every_mvp_drug(self):
        adr = calculate_adr_risk()
        assert adr["high_baseline_adr_risk"] is False
        assert adr["adr_risk_flag"] == ADR_RISK_STANDARD

        for drug in ("Clopidogrel", "Tacrolimus", "Warfarin"):
            triage = triage_pgx_actionability(
                drug, None, age=None, weight=None,
                egfr=None, alt_ast=None,
                platelets=None, pt_inr=None,
                high_baseline_adr_risk=adr["high_baseline_adr_risk"],
            )
            assert "triage" in triage
            assert "cpic_testing_recommendation" in triage
            assert "contextual_modifier" in triage

        for ethnicity in ETHNICITY_OPTIONS:
            genomeindia = genomeindia_population_priority(ethnicity)
            assert "genomeindia_priority" in genomeindia

    def test_blank_text_fields_end_to_end_through_parse_lab_value(self):
        # Exercises the exact ingestion path app.py's _lab_numeric_input
        # uses: raw text -> parse_lab_value -> triage_pgx_actionability.
        egfr, egfr_error = parse_lab_value("")
        alt_ast, alt_ast_error = parse_lab_value("N/A")
        platelets, platelets_error = parse_lab_value("none")
        pt_inr, pt_inr_error = parse_lab_value("  ")
        assert (egfr, alt_ast, platelets, pt_inr) == (None, None, None, None)
        assert (egfr_error, alt_ast_error, platelets_error, pt_inr_error) == (None, None, None, None)

        triage = triage_pgx_actionability(
            "Warfarin", None, age=None, weight=None,
            egfr=egfr, alt_ast=alt_ast, platelets=platelets, pt_inr=pt_inr,
        )
        assert triage["triage"] == TRIAGE_CONSIDER
        assert triage["cpic_testing_recommendation"] == CPIC_TESTING_RECOMMENDED

    def test_warfarin_blank_submission_lands_on_consider_not_high_or_low(self):
        triage = triage_pgx_actionability(
            "Warfarin", None, age=None, weight=None,
            egfr=None, alt_ast=None,
            platelets=None, pt_inr=None,
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

        # Raw numeric readings entered as text and type-cast by
        # parse_lab_value(), exactly as app.py's Layer 1 inputs would.
        egfr, _ = parse_lab_value("30")
        alt_ast, _ = parse_lab_value("60")
        triage = triage_pgx_actionability(
            "Tacrolimus", ["Fluconazole"], age=85, weight=55.0,
            egfr=egfr, alt_ast=alt_ast,
            high_baseline_adr_risk=adr["high_baseline_adr_risk"],
        )
        assert triage["triage"] == TRIAGE_HIGH
        assert triage["cpic_testing_recommendation"] == CPIC_TESTING_REQUIRED
        assert len(triage["warnings"]) >= 2

    def test_garbage_text_input_degrades_to_missing_data_not_a_crash(self):
        # A clinician typing garbage into a numeric field must never crash
        # the triage pipeline -- parse_lab_value degrades it to None (an
        # error message is surfaced separately by the UI layer).
        value, error = parse_lab_value("not a number")
        assert value is None
        assert error is not None

        triage = triage_pgx_actionability("Warfarin", None, egfr=value, alt_ast=value)
        assert triage["triage"] == TRIAGE_CONSIDER


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
