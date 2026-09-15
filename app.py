import json

import streamlit as st

from abdm.fhir_builder import generate_fhir_bundle
from engine.ddi import ALL_INTERACTING_DRUGS
from engine.rules import (
    EVIDENCE_SOURCE,
    GUIDELINE_VERSION,
    RISK_HIGH,
    RISK_NO_ALERT,
    RULE_VERSION,
    evaluate_prescription,
)
from engine.triage import TRIAGE_CONSIDER, TRIAGE_HIGH, triage_pgx_actionability
from storage.audit_logger import get_all_logs, log_decision

SOFTWARE_VERSION = "PRISM-India v4.0.0"

st.set_page_config(page_title="PRISM-India", page_icon="🧬", layout="centered")

st.title("PRISM-India: Cost-Conscious Clinical + PGx Decision Support")
st.caption("Team ID: DENDRITE-PE-XD-018")

DRUG_OPTIONS = [
    "Clopidogrel",
    "Warfarin",
    "Tacrolimus",
    "Carbamazepine",
    "Allopurinol",
    "Abacavir",
    "Primaquine",
    "Rasburicase",
]

DIAGNOSTIC_DATA_OPTIONS = [
    "Genotype Data",
    "Phenotype / TDM Data",
    "None of the above (Run Triage)",
]

VERIFICATION_STATUS_OPTIONS = [
    "Verified",
    "Preliminary / Pending Confirmation",
    "Unverified",
]

CYP2C9_OPTIONS = ["*1/*1", "*1/*2", "*1/*3", "*2/*2", "*2/*3", "*3/*3"]
VKORC1_OPTIONS = ["GG", "AG", "AA"]

# Every (drug, test_type) combination the rule engine has a defined rule for,
# and the strictly validated widget used to capture its result -- no free text.
# Warfarin is handled separately (a compound CYP2C9 + VKORC1 genotype), below.
TEST_RESULT_OPTIONS = {
    ("clopidogrel", "Genotype"): {
        "type": "select",
        "options": ["*1/*1", "*1/*2", "*1/*3", "*2/*2", "*2/*3", "*3/*3", "*1/*17"],
        "help": "*1/*17 is an ultra-rapid metabolizer genotype not covered by this "
                "rule set (returns UNKNOWN).",
    },
    ("clopidogrel", "Phenotype"): {
        "type": "number", "label": "Platelet Reactivity (PRU)",
        "min": 0, "max": 500, "default": 150, "step": 1,
    },
    ("carbamazepine", "Genotype"): {"type": "select", "options": ["Positive", "Negative"]},
    ("allopurinol", "Genotype"): {"type": "select", "options": ["Positive", "Negative"]},
    ("abacavir", "Genotype"): {"type": "select", "options": ["Positive", "Negative"]},
    ("primaquine", "Genotype"): {"type": "select", "options": ["Deficient", "Normal"]},
    ("primaquine", "Phenotype"): {
        "type": "number", "label": "G6PD Enzyme Activity (%)",
        "min": 0.0, "max": 100.0, "default": 5.0, "step": 0.5,
    },
    ("rasburicase", "Genotype"): {"type": "select", "options": ["Deficient", "Normal"]},
    ("rasburicase", "Phenotype"): {
        "type": "number", "label": "G6PD Enzyme Activity (%)",
        "min": 0.0, "max": 100.0, "default": 5.0, "step": 0.5,
    },
    ("tacrolimus", "Genotype"): {
        "type": "select", "options": ["*1/*1", "*1/*3", "*3/*3"],
        "help": "CYP3A5 starting-dose PGx rule: *1/*1 and *1/*3 are expresser "
                "genotypes; *3/*3 is non-expresser.",
    },
    ("tacrolimus", "Phenotype"): {
        "type": "number", "label": "Tacrolimus Trough Level (ng/mL) -- TDM alert",
        "min": 0.0, "max": 30.0, "default": 10.0, "step": 0.5,
    },
}


def _render_test_result_input(drug: str, test_type: str):
    """Render a strictly validated selectbox/number_input for this (drug, test_type).

    Returns the result as a string, or None if this combination has no defined
    rule (evaluate_prescription resolves that to an UNKNOWN verdict).
    """
    drug_key = drug.lower()

    if drug_key == "warfarin":
        if test_type != "Genotype":
            st.selectbox(
                "Test Result",
                ["Not applicable -- Warfarin genetic dosing uses Genotype only"],
                disabled=True,
                help="Routine PT/INR monitoring, not a phenotype rule, governs "
                     "warfarin's day-to-day titration in this MVP; select "
                     "'None of the above (Run Triage)' above instead.",
            )
            return None
        col_a, col_b = st.columns(2)
        with col_a:
            cyp2c9 = st.selectbox("CYP2C9 Diplotype", CYP2C9_OPTIONS)
        with col_b:
            vkorc1 = st.selectbox("VKORC1 Genotype", VKORC1_OPTIONS)
        return f"CYP2C9={cyp2c9};VKORC1={vkorc1}"

    spec = TEST_RESULT_OPTIONS.get((drug_key, test_type))
    if spec is None:
        st.selectbox(
            "Test Result",
            ["Not applicable for this drug / test-type combination"],
            disabled=True,
            help="No CPIC rule is defined for this combination; switch "
                 "Diagnostic Data Available above.",
        )
        return None
    if spec["type"] == "select":
        return st.selectbox("Test Result", spec["options"], help=spec.get("help"))
    value = st.number_input(
        spec["label"], min_value=spec["min"], max_value=spec["max"],
        value=spec["default"], step=spec["step"], help=spec.get("help"),
    )
    return str(value)


def _lab_value_with_unknown_checkbox(label, min_value, max_value, default_value, step, key):
    """Render a number_input paired with a 'Test Not Done / Unknown' checkbox.

    Returns the numeric value, or None if the checkbox is checked -- the
    None is what actually reaches the Clinical Engine (the `disabled`
    number_input keeps its last value internally, but that value is
    discarded here rather than passed through).
    """
    unknown = st.checkbox(f"Test Not Done / Unknown", key=f"{key}_unknown")
    value = st.number_input(
        label, min_value=min_value, max_value=max_value, value=default_value,
        step=step, disabled=unknown, key=f"{key}_value",
    )
    return None if unknown else value


def _similar_cases_expander(age, drug, extra_context: str = "") -> None:
    with st.expander("🔍 Web Search: Similar Clinical Cases (Prototype)"):
        st.info(
            "**Mockup / Coming Soon** -- this panel does not perform a real "
            "web or literature search. No external request is made."
        )
        st.markdown(
            f"In a future version, PRISM-India would search medical "
            f"literature and de-identified case repositories for patient "
            f"profiles similar to this one -- **age {age}, drug: {drug}**"
            + (f", {extra_context}" if extra_context else "")
            + " -- to surface comparable published cases, the pharmacogenomic "
            "or clinical decisions made, and their reported outcomes."
        )


main_tab, audit_tab = st.tabs(["Clinical Assessment", "Audit & Governance Log"])

with st.sidebar:
    st.header("Clinical Encounter Metadata")
    st.caption("Required to log a decision from the Clinical Assessment tab.")
    clinician_id = st.text_input("Clinician ID", placeholder="e.g. DR-4471")
    institution = st.text_input("Institution", placeholder="e.g. AIIMS Delhi")
    encounter_id = st.text_input("Encounter ID", placeholder="e.g. ENC-20260914-001")
    assay_lab = st.text_input("Assay / Lab", placeholder="e.g. NABL-Accredited Molecular Diagnostics Lab")
    specimen_date = st.date_input("Specimen Date")
    result_verification_status = st.selectbox(
        "Result Verification Status", VERIFICATION_STATUS_OPTIONS
    )


def _metadata_complete() -> bool:
    return all([clinician_id.strip(), institution.strip(), encounter_id.strip(), assay_lab.strip()])


def _log_and_export(clinician_decision: str, override_reason: str = None) -> None:
    if not _metadata_complete():
        st.warning(
            "Please complete Clinician ID, Institution, Encounter ID, and "
            "Assay/Lab in the sidebar before logging this decision."
        )
        return

    ctx = st.session_state["eval_context"]
    common_kwargs = dict(
        clinician_id=clinician_id.strip(),
        institution=institution.strip(),
        encounter_id=encounter_id.strip(),
        assay_lab=assay_lab.strip(),
        specimen_date=str(specimen_date),
        result_verification_status=result_verification_status,
        guideline_version=GUIDELINE_VERSION,
        rule_version=RULE_VERSION,
        evidence_source=EVIDENCE_SOURCE,
        software_version=SOFTWARE_VERSION,
    )

    log_decision(
        ctx["patient_id"], ctx["drug"], ctx["test_type"], ctx["test_result"],
        ctx["recommendation_given"], clinician_decision, override_reason,
        **common_kwargs,
    )
    st.session_state["fhir_bundle"] = generate_fhir_bundle(
        ctx["patient_id"], ctx["drug"], ctx["test_type"], ctx["test_result"],
        ctx["recommendation_given"], clinician_decision, override_reason,
        **common_kwargs,
    )
    st.success("Decision recorded to audit log")


with main_tab:
    st.subheader("Patient Baseline")
    col1, col2 = st.columns(2)
    with col1:
        patient_id = st.text_input("Patient ID", placeholder="e.g. PT-1001")
        weight = st.number_input("Weight (kg)", min_value=0.0, max_value=250.0, value=70.0, step=0.5)
    with col2:
        age = st.number_input("Age (years)", min_value=0, max_value=120, value=40, step=1)
        drug = st.selectbox("Drug Requested", DRUG_OPTIONS)

    concomitant_drugs_text = st.text_input(
        "Current Medications",
        placeholder="e.g. Omeprazole, Amiodarone",
        help="Comma-separated. Checked against known severe interactions. "
             f"Interactions are modeled for: {', '.join(d.title() for d in ALL_INTERACTING_DRUGS)}.",
    )
    concurrent_medications = [d.strip() for d in concomitant_drugs_text.split(",") if d.strip()]

    st.markdown("---")
    diagnostic_data_choice = st.radio("Diagnostic Data Available:", DIAGNOSTIC_DATA_OPTIONS)
    st.markdown("---")

    if diagnostic_data_choice in ("Genotype Data", "Phenotype / TDM Data"):
        # Path A: a PGx test result already exists -- go straight to interpretation.
        test_type = "Genotype" if diagnostic_data_choice == "Genotype Data" else "Phenotype"

        st.subheader("Genotype / Phenotype Evaluation")
        test_result = _render_test_result_input(drug, test_type)
        evaluate_clicked = st.button("Evaluate", type="primary")

        if evaluate_clicked:
            if not patient_id.strip():
                st.warning("Patient ID is required before evaluating.")
            else:
                result = evaluate_prescription(drug, test_type, test_result)
                st.session_state["result"] = result
                st.session_state["eval_context"] = {
                    "patient_id": patient_id.strip(),
                    "drug": drug,
                    "test_type": test_type,
                    "test_result": test_result,
                    "recommendation_given": result["recommendation_and_dosage"] or result["reason"],
                }
                st.session_state["show_override"] = False
                st.session_state["fhir_bundle"] = None

        result = st.session_state.get("result")

        if not result:
            st.info("Select a test result above, then click Evaluate.")
        else:
            st.subheader("Decision Support Output")
            if result["risk"] == RISK_HIGH:
                st.error(
                    f"⚠️ HIGH RISK — {result['reason']}\n\n"
                    f"**Recommended Action & Dosage:** {result['recommendation_and_dosage']}"
                )

                col_accept, col_override = st.columns(2)
                with col_accept:
                    if st.button("Accept"):
                        _log_and_export("ACCEPTED")
                with col_override:
                    if st.button("Override"):
                        st.session_state["show_override"] = True

                if st.session_state.get("show_override"):
                    justification = st.text_area("Clinical Justification for Override")
                    if st.button("Submit Override"):
                        if justification.strip():
                            _log_and_export("OVERRIDDEN", justification.strip())
                        else:
                            st.info("Please provide a justification before submitting the override.")

            elif result["risk"] == RISK_NO_ALERT:
                st.success(
                    f"✅ NO ACTIONABLE ALERT — {result['reason']}\n\n"
                    f"**Recommended Action & Dosage:** {result['recommendation_and_dosage']}"
                )
                if st.button("Accept"):
                    _log_and_export("ACCEPTED")

            else:
                st.info(result["reason"])

            fhir_bundle = st.session_state.get("fhir_bundle")
            if fhir_bundle:
                with st.expander("FHIR R4 / ABDM-aligned Interoperability Record"):
                    st.json(fhir_bundle)
                    st.download_button(
                        "Download FHIR Bundle (JSON)",
                        data=json.dumps(fhir_bundle, indent=2),
                        file_name=f"fhir_bundle_{st.session_state['eval_context']['patient_id']}.json",
                        mime="application/json",
                    )

            _similar_cases_expander(age, drug, extra_context=f"result: {result['risk']}")

    else:
        # Path B: no PGx result yet -- run the Pre-Test Triage Engine instead.
        st.subheader("Pre-Test PGx Actionability Triage")
        st.caption(
            "No genotype or phenotype data available. Tier 1 (Clinical Engine: "
            "exact numeric labs) and Tier 2 (DDI Engine) combine here to answer "
            "one question before any genetic test is ordered: is PGx testing "
            "for this drug actually likely to change this patient's management?"
        )

        col1, col2 = st.columns(2)
        with col1:
            egfr = _lab_value_with_unknown_checkbox(
                "eGFR (mL/min/1.73m²)", 0.0, 200.0, 90.0, 1.0, key="egfr"
            )
            alt_ast = _lab_value_with_unknown_checkbox(
                "ALT / AST (U/L)", 0.0, 1000.0, 25.0, 1.0, key="alt_ast"
            )
        with col2:
            platelets = _lab_value_with_unknown_checkbox(
                "Platelets (x10³/µL)", 0.0, 800.0, 250.0, 5.0, key="platelets"
            )
            pt_inr = _lab_value_with_unknown_checkbox(
                "PT / INR (Ratio)", 0.5, 8.0, 1.0, 0.1, key="pt_inr"
            )

        triage_clicked = st.button("Run Pre-Test Triage", type="primary")

        if triage_clicked:
            st.session_state["triage_result"] = triage_pgx_actionability(
                drug, concurrent_medications,
                age=age, weight=weight, egfr=egfr, alt_ast=alt_ast,
                platelets=platelets, pt_inr=pt_inr,
            )
            st.session_state["triage_drug"] = drug

        triage_result = st.session_state.get("triage_result")

        if not triage_result:
            st.info("Enter the available labs above, then click Run Pre-Test Triage.")
        else:
            triage_drug = st.session_state.get("triage_drug", drug)
            triage_state = triage_result["triage"]

            if triage_state == TRIAGE_HIGH:
                st.error(f"🔴 HIGH PRIORITY — PGx testing for {triage_drug} is strongly indicated")
            elif triage_state == TRIAGE_CONSIDER:
                st.warning(f"🟡 CONSIDER — genetic information for {triage_drug} may influence treatment")
            else:
                st.success(f"🟢 LOW PRIORITY — PGx testing for {triage_drug} is unlikely to change management")

            st.markdown("**Rationale:**")
            for line in triage_result["rationale"]:
                st.markdown(f"- {line}")

            if triage_result.get("warnings"):
                st.markdown("**Lab-Driven Safety Warnings:**")
                for warning_text in triage_result["warnings"]:
                    st.error(warning_text)

            if triage_result["ddi_findings"]:
                st.markdown("**Drug-Drug Interaction (DDI Engine) Findings:**")
                for finding in triage_result["ddi_findings"]:
                    st.warning(
                        f"**{finding['severity']}** — "
                        f"{', '.join(m.title() for m in finding['matched_medications'])}: "
                        f"{finding['mechanism']}\n\n"
                        f"**Recommendation:** {finding['recommendation']}\n\n"
                        f"*Source: {finding['source']}*"
                    )

            if triage_result["clinical_findings"]:
                st.markdown("**Clinical Engine (Routine Labs) Findings:**")
                st.json(triage_result["clinical_findings"])

            _similar_cases_expander(age, triage_drug, extra_context=f"triage: {triage_state}")

with audit_tab:
    st.subheader("Audit & Governance Log")
    st.caption("Full history of clinician decisions on PRISM-India recommendations.")
    logs_df = get_all_logs()
    if logs_df.empty:
        st.info("No decisions have been recorded yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)
