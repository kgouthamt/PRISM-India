import streamlit as st

from engine.rules import evaluate_prescription

st.set_page_config(page_title="PRISM-India", page_icon="🧬", layout="centered")

st.title("PRISM-India: Bedside Pharmacogenomics Decision Support")
st.caption("Team ID: DENDRITE-PE-XD-018")

DEMO_PATIENTS = {
    "Patient A - CYP2C19 poor metabolizer": {
        "drug": "Clopidogrel",
        "genotype": "*2/*2",
    },
    "Patient B - HLA-B*15:02 carrier": {
        "drug": "Carbamazepine",
        "genotype": "Positive",
    },
    "Patient C - Normal / safe": {
        "drug": "Abacavir",
        "genotype": "*1/*1",
    },
}

st.sidebar.header("Demo Patients")
selected_patient = st.sidebar.radio("Select a patient", list(DEMO_PATIENTS.keys()))

if st.session_state.get("_last_patient") != selected_patient:
    st.session_state["_last_patient"] = selected_patient
    st.session_state["result"] = None
    st.session_state["show_override"] = False

patient = DEMO_PATIENTS[selected_patient]

st.subheader("Patient Details")
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

    if result["risk"] == "HIGH":
        st.error(
            f"⚠️ HIGH RISK — {result['reason']}\n\n"
            f"**Recommendation:** {result['recommendation']}"
        )

        if st.button("Override"):
            st.session_state["show_override"] = True

        if st.session_state.get("show_override"):
            justification = st.text_area("Clinical Justification for Override")
            if st.button("Submit Override"):
                if justification.strip():
                    st.warning(
                        f"Override recorded for **{drug.title()}** with justification: "
                        f"\"{justification.strip()}\""
                    )
                else:
                    st.info("Please provide a justification before submitting the override.")

    elif result["risk"] == "SAFE":
        st.success(f"✅ SAFE — {result['reason']}")

    else:
        st.info(result["reason"])
