import streamlit as st

from engine.rules import evaluate_prescription
from storage.audit_logger import get_all_logs, log_decision

st.set_page_config(page_title="PRISM-India", page_icon="🧬", layout="centered")

st.title("PRISM-India: Bedside Pharmacogenomics Decision Support")
st.caption("Team ID: DENDRITE-PE-XD-018")

DEMO_PATIENTS = {
    "Patient A - CYP2C19 poor metabolizer": {
        "patient_id": "DEMO-A-001",
        "drug": "Clopidogrel",
        "genotype": "*2/*2",
    },
    "Patient B - HLA-B*15:02 carrier": {
        "patient_id": "DEMO-B-002",
        "drug": "Carbamazepine",
        "genotype": "Positive",
    },
    "Patient C - Normal / safe": {
        "patient_id": "DEMO-C-003",
        "drug": "Abacavir",
        "genotype": "*1/*1",
    },
}

decision_tab, audit_tab = st.tabs(["Clinical Decision Support", "Audit & Governance Log"])

with decision_tab:
    st.sidebar.header("Demo Patients")
    selected_patient = st.sidebar.radio("Select a patient", list(DEMO_PATIENTS.keys()))

    if st.session_state.get("_last_patient") != selected_patient:
        st.session_state["_last_patient"] = selected_patient
        st.session_state["result"] = None
        st.session_state["show_override"] = False

    patient = DEMO_PATIENTS[selected_patient]

    st.subheader("Patient Details")
    patient_id = st.text_input("Patient ID", value=patient["patient_id"])
    col1, col2 = st.columns(2)
    with col1:
        drug = st.text_input("Requested Drug", value=patient["drug"])
    with col2:
        genotype = st.text_input("Genotype / Allele Status", value=patient["genotype"])

    if st.button("Evaluate", type="primary"):
        st.session_state["result"] = evaluate_prescription(drug, genotype)
        st.session_state["show_override"] = False

    result = st.session_state.get("result")

    if result:
        st.subheader("Decision Support Output")
        recommendation_given = result["recommendation"] or result["reason"]

        if result["risk"] == "HIGH":
            st.error(
                f"⚠️ HIGH RISK — {result['reason']}\n\n"
                f"**Recommendation:** {result['recommendation']}"
            )

            col_accept, col_override = st.columns(2)
            with col_accept:
                if st.button("Accept"):
                    log_decision(
                        patient_id, drug, genotype, recommendation_given,
                        "ACCEPTED", None,
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
                            patient_id, drug, genotype, recommendation_given,
                            "OVERRIDDEN", justification.strip(),
                        )
                        st.success("Decision recorded to audit log")
                    else:
                        st.info("Please provide a justification before submitting the override.")

        elif result["risk"] == "SAFE":
            st.success(f"✅ SAFE — {result['reason']}")
            if st.button("Accept"):
                log_decision(
                    patient_id, drug, genotype, recommendation_given,
                    "ACCEPTED", None,
                )
                st.success("Decision recorded to audit log")

        else:
            st.info(result["reason"])

with audit_tab:
    st.subheader("Audit & Governance Log")
    st.caption("Full history of clinician decisions on PRISM-India recommendations.")
    logs_df = get_all_logs()
    if logs_df.empty:
        st.info("No decisions have been recorded yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)
