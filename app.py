import json

import streamlit as st

from abdm.fhir_builder import generate_fhir_bundle
from engine.rules import evaluate_prescription
from storage.audit_logger import get_all_logs, log_decision

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

TEST_RESULT_PLACEHOLDERS = {
    ("clopidogrel", "Genotype"): "*2/*2",
    ("clopidogrel", "Phenotype"): "> 208",
    ("carbamazepine", "Genotype"): "Positive",
    ("allopurinol", "Genotype"): "Positive",
    ("abacavir", "Genotype"): "Positive",
    ("primaquine", "Genotype"): "Deficient",
    ("primaquine", "Phenotype"): "< 10%",
    ("rasburicase", "Genotype"): "Deficient",
    ("rasburicase", "Phenotype"): "< 10%",
    ("tacrolimus", "Phenotype"): "18 ng/mL",
}


def _test_result_placeholder(drug: str, test_type: str) -> str:
    return TEST_RESULT_PLACEHOLDERS.get((drug.lower(), test_type), "Enter test result")


decision_tab, audit_tab = st.tabs(["Clinical Decision Support", "Audit & Governance Log"])

with st.sidebar:
    st.header("Patient & Prescription Details")
    patient_id = st.text_input("Patient ID", placeholder="e.g. PT-1001")
    drug = st.selectbox("Drug Requested", DRUG_OPTIONS)
    test_type_choice = st.radio(
        "Test Data Available:", ["Genotype Assay", "Phenotype / Clinical Test"]
    )
    test_type = "Genotype" if test_type_choice == "Genotype Assay" else "Phenotype"
    test_result = st.text_input(
        "Test Result", placeholder=_test_result_placeholder(drug, test_type)
    )
    evaluate_clicked = st.button("Evaluate", type="primary")

with decision_tab:
    st.subheader("Decision Support Output")

    if evaluate_clicked:
        if not patient_id.strip() or not test_result.strip():
            st.warning("Patient ID and Test Result are required before evaluating.")
        else:
            st.session_state["result"] = evaluate_prescription(drug, test_type, test_result)
            st.session_state["eval_context"] = {
                "patient_id": patient_id.strip(),
                "drug": drug,
                "test_type": test_type,
                "test_result": test_result.strip(),
            }
            st.session_state["show_override"] = False
            st.session_state["fhir_bundle"] = None

    result = st.session_state.get("result")
    context = st.session_state.get("eval_context")

    if not result:
        st.info(
            "Enter a Patient ID, select a drug, choose Genotype or Phenotype, "
            "provide the test result in the sidebar, then click Evaluate."
        )
    else:
        recommendation_given = result["recommendation_and_dosage"] or result["reason"]

        if result["risk"] == "HIGH":
            st.error(
                f"⚠️ HIGH RISK — {result['reason']}\n\n"
                f"**Recommended Action & Dosage:** {result['recommendation_and_dosage']}"
            )

            col_accept, col_override = st.columns(2)
            with col_accept:
                if st.button("Accept"):
                    log_decision(
                        context["patient_id"], context["drug"], context["test_type"],
                        context["test_result"], recommendation_given, "ACCEPTED", None,
                    )
                    st.session_state["fhir_bundle"] = generate_fhir_bundle(
                        context["patient_id"], context["drug"], context["test_type"],
                        context["test_result"], recommendation_given, "ACCEPTED", None,
                    )
                    st.success("Decision recorded to audit log")
            with col_override:
                if st.button("Override"):
                    st.session_state["show_override"] = True

            if st.session_state.get("show_override"):
                justification = st.text_area("Clinical Justification for Override")
                if st.button("Submit Override"):
                    if justification.strip():
                        log_decision(
                            context["patient_id"], context["drug"], context["test_type"],
                            context["test_result"], recommendation_given, "OVERRIDDEN",
                            justification.strip(),
                        )
                        st.session_state["fhir_bundle"] = generate_fhir_bundle(
                            context["patient_id"], context["drug"], context["test_type"],
                            context["test_result"], recommendation_given, "OVERRIDDEN",
                            justification.strip(),
                        )
                        st.success("Decision recorded to audit log")
                    else:
                        st.info("Please provide a justification before submitting the override.")

        elif result["risk"] == "SAFE":
            st.success(
                f"✅ SAFE — {result['reason']}\n\n"
                f"**Recommended Action & Dosage:** {result['recommendation_and_dosage']}"
            )
            if st.button("Accept"):
                log_decision(
                    context["patient_id"], context["drug"], context["test_type"],
                    context["test_result"], recommendation_given, "ACCEPTED", None,
                )
                st.session_state["fhir_bundle"] = generate_fhir_bundle(
                    context["patient_id"], context["drug"], context["test_type"],
                    context["test_result"], recommendation_given, "ACCEPTED", None,
                )
                st.success("Decision recorded to audit log")

        else:
            st.info(result["reason"])

        fhir_bundle = st.session_state.get("fhir_bundle")
        if fhir_bundle:
            with st.expander("ABDM / FHIR Interoperability Record"):
                st.json(fhir_bundle)
                st.download_button(
                    "Download FHIR Bundle (JSON)",
                    data=json.dumps(fhir_bundle, indent=2),
                    file_name=f"fhir_bundle_{context['patient_id']}.json",
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
