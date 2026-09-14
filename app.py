import json

import streamlit as st

from abdm.fhir_builder import generate_fhir_bundle
from engine.rules import (
    EVIDENCE_SOURCE,
    GUIDELINE_VERSION,
    RISK_HIGH,
    RISK_NO_ALERT,
    RULE_VERSION,
    evaluate_prescription,
)
from storage.audit_logger import get_all_logs, log_decision

SOFTWARE_VERSION = "PRISM-India v2.0.0"

st.set_page_config(page_title="PRISM-India", page_icon="🧬", layout="centered")

st.title("PRISM-India: Bedside Pharmacogenomics Decision Support")
st.caption("Team ID: DENDRITE-PE-XD-018")

DRUG_OPTIONS = [
    "Clopidogrel",
    "Carbamazepine",
    "Allopurinol",
    "Abacavir",
    "Primaquine",
    "Rasburicase",
    "Tacrolimus",
]

VERIFICATION_STATUS_OPTIONS = [
    "Verified",
    "Preliminary / Pending Confirmation",
    "Unverified",
]

# Every (drug, test_type) combination the rule engine has a defined rule for,
# and the strictly validated widget used to capture its result -- no free text.
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
    spec = TEST_RESULT_OPTIONS.get((drug.lower(), test_type))
    if spec is None:
        st.selectbox(
            "Test Result",
            ["Not applicable for this drug / test-type combination"],
            disabled=True,
            help="No CPIC rule is defined for this combination; switch "
                 "Test Data Available above.",
        )
        return None
    if spec["type"] == "select":
        return st.selectbox("Test Result", spec["options"], help=spec.get("help"))
    value = st.number_input(
        spec["label"], min_value=spec["min"], max_value=spec["max"],
        value=spec["default"], step=spec["step"], help=spec.get("help"),
    )
    return str(value)


decision_tab, audit_tab = st.tabs(["Clinical Decision Support", "Audit & Governance Log"])

with st.sidebar:
    st.header("Patient & Prescription Details")
    patient_id = st.text_input("Patient ID", placeholder="e.g. PT-1001")
    drug = st.selectbox("Drug Requested", DRUG_OPTIONS)
    test_type_choice = st.radio(
        "Test Data Available:", ["Genotype Assay", "Phenotype / Clinical Test"]
    )
    test_type = "Genotype" if test_type_choice == "Genotype Assay" else "Phenotype"
    test_result = _render_test_result_input(drug, test_type)

    st.markdown("---")
    st.header("Clinical Encounter Metadata")
    clinician_id = st.text_input("Clinician ID", placeholder="e.g. DR-4471")
    institution = st.text_input("Institution", placeholder="e.g. AIIMS Delhi")
    encounter_id = st.text_input("Encounter ID", placeholder="e.g. ENC-20260914-001")
    assay_lab = st.text_input("Assay / Lab", placeholder="e.g. NABL-Accredited Molecular Diagnostics Lab")
    specimen_date = st.date_input("Specimen Date")
    result_verification_status = st.selectbox(
        "Result Verification Status", VERIFICATION_STATUS_OPTIONS
    )

    evaluate_clicked = st.button("Evaluate", type="primary")


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


with decision_tab:
    st.subheader("Decision Support Output")

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
        st.info(
            "Complete the sidebar (Patient ID, drug, test type, test result), "
            "then click Evaluate."
        )
    else:
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

with audit_tab:
    st.subheader("Audit & Governance Log")
    st.caption("Full history of clinician decisions on PRISM-India recommendations.")
    logs_df = get_all_logs()
    if logs_df.empty:
        st.info("No decisions have been recorded yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)
