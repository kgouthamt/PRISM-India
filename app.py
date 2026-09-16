import html
import json

import streamlit as st

from abdm.fhir_builder import generate_fhir_bundle
from engine.clinical import calculate_adr_risk
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

SOFTWARE_VERSION = "PRISM-AIIMS v5.0.0"

st.set_page_config(page_title="PRISM-AIIMS", page_icon="🧬", layout="wide")

CUSTOM_CSS = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {visibility: hidden;}

.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.07);
}

div[data-testid="stMetric"] {
    background-color: rgba(127, 127, 127, 0.06);
    border: 1px solid rgba(127, 127, 127, 0.18);
    border-radius: 12px;
    padding: 14px 10px 8px 10px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

section[data-testid="stSidebar"] {
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.05);
}

.pgx-card {
    border-radius: 14px;
    padding: 18px 22px;
    margin: 10px 0 16px 0;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
    font-size: 1.02rem;
    line-height: 1.5;
}
.pgx-card h3 {margin-top: 0; margin-bottom: 6px;}
.pgx-card-high {background: #fdecea; border-left: 8px solid #d32f2f; color: #7a1010;}
.pgx-card-consider {background: #fff8e1; border-left: 8px solid #f9a825; color: #6b5200;}
.pgx-card-low {background: #e8f5e9; border-left: 8px solid #2e7d32; color: #1b4d20;}
.pgx-card-info {background: #e8f0fe; border-left: 8px solid #1a73e8; color: #0b3d91;}

.adr-banner {
    border-radius: 12px;
    padding: 14px 18px;
    font-weight: 700;
    margin-top: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.10);
}
.adr-banner-high {background: #fdecea; border: 2px solid #d32f2f; color: #7a1010;}
.adr-banner-standard {background: #e8f5e9; border: 2px solid #2e7d32; color: #1b4d20;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("PRISM-AIIMS: 3-Layer Clinical + PGx Decision Support")
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


def _alert_card(level: str, title: str, body_html: str) -> None:
    """Render a large, colored alert card (level: 'high'/'consider'/'low'/'info')."""
    st.markdown(
        f"<div class='pgx-card pgx-card-{level}'><h3>{title}</h3>{body_html}</div>",
        unsafe_allow_html=True,
    )


def _similar_cases_sidebar_panel() -> None:
    with st.sidebar:
        st.markdown("---")
        with st.expander("🔍 Web Search: Similar Clinical Cases (Prototype)"):
            st.info(
                "**Mockup / Coming Soon** -- this panel does not perform a real "
                "web or literature search. No external request is made."
            )
            age_val = st.session_state.get("layer1_age")
            drug_val = st.session_state.get("layer3_drug")
            if age_val is None or drug_val is None:
                st.caption("Complete Layer 1 and Layer 3 above to preview context here.")
                return

            extra_context = ""
            triage_result = st.session_state.get("triage_result")
            eval_result = st.session_state.get("result")
            if triage_result:
                extra_context += f", triage: {triage_result['triage']}"
            elif eval_result:
                extra_context += f", result: {eval_result['risk']}"
            adr_flag = st.session_state.get("adr_risk_flag")
            if adr_flag:
                extra_context += f", ADR: {adr_flag}"

            st.markdown(
                f"In a future version, PRISM-AIIMS would search medical "
                f"literature and de-identified case repositories for patient "
                f"profiles similar to this one -- **age {age_val}, drug: "
                f"{drug_val}{extra_context}** -- to surface comparable "
                "published cases, the pharmacogenomic or clinical decisions "
                "made, and their reported outcomes."
            )


tab1, tab2 = st.tabs(["Clinical Dashboard", "Audit & Governance"])

with st.sidebar:
    st.header("Clinical Encounter Metadata")
    st.caption("Required to log a decision from the Clinical Dashboard tab.")
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
        adr_risk_flag=st.session_state.get("adr_risk_flag"),
        **common_kwargs,
    )
    st.session_state["fhir_bundle"] = generate_fhir_bundle(
        ctx["patient_id"], ctx["drug"], ctx["test_type"], ctx["test_result"],
        ctx["recommendation_given"], clinician_decision, override_reason,
        **common_kwargs,
    )
    st.success("Decision recorded to audit log")


with tab1:
    patient_id = st.text_input("Patient ID (Medical Record Number)", placeholder="e.g. PT-1001")

    st.header("👤 LAYER 1: Patient Baseline")
    with st.container(border=True):
        st.markdown("**Demographics**")
        col1, col2, col3 = st.columns(3)
        with col1:
            patient_name = st.text_input("Name", placeholder="e.g. Ramesh Kumar")
        with col2:
            age = st.number_input("Age (years)", min_value=0, max_value=120, value=40, step=1)
        with col3:
            address = st.text_input("Address", placeholder="e.g. New Delhi, India")

        st.markdown("**Anthropometrics**")
        col4, col5 = st.columns(2)
        with col4:
            height = st.number_input("Height (cm)", min_value=0.0, max_value=250.0, value=165.0, step=0.5)
        with col5:
            weight = st.number_input("Weight (kg)", min_value=0.0, max_value=250.0, value=70.0, step=0.5)

        st.markdown("**Vitals**")
        vcol1, vcol2, vcol3, vcol4, vcol5, vcol6 = st.columns(6)
        with vcol1:
            pulse_rate = st.number_input("PR (bpm)", min_value=0, max_value=250, value=80, step=1)
        with vcol2:
            bp_systolic = st.number_input("BP Sys (mmHg)", min_value=0, max_value=300, value=120, step=1)
        with vcol3:
            bp_diastolic = st.number_input("BP Dia (mmHg)", min_value=0, max_value=200, value=80, step=1)
        with vcol4:
            respiratory_rate = st.number_input("RR (/min)", min_value=0, max_value=80, value=16, step=1)
        with vcol5:
            spo2 = st.number_input("SpO2 (%)", min_value=0, max_value=100, value=98, step=1)
        with vcol6:
            temperature = st.number_input("Temp (°F)", min_value=80.0, max_value=115.0, value=98.6, step=0.1)

        st.markdown("**🖥️ Vitals Monitor**")
        mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
        mcol1.metric(
            "Pulse Rate", f"{pulse_rate} bpm",
            delta=("Tachycardia" if pulse_rate > 100 else "Bradycardia" if pulse_rate < 60 else None),
            delta_color="inverse",
        )
        mcol2.metric("BP (mmHg)", f"{bp_systolic}/{bp_diastolic}")
        mcol3.metric("Respiratory Rate", f"{respiratory_rate} /min")
        mcol4.metric(
            "SpO2", f"{spo2}%",
            delta=("Low" if spo2 < 95 else None), delta_color="inverse",
        )
        mcol5.metric(
            "Temperature", f"{temperature}°F",
            delta=("Fever" if temperature >= 100.4 else None), delta_color="inverse",
        )

    st.session_state["layer1_age"] = age

    st.header("⚠️ LAYER 2: ADR Risk Prediction")
    with st.container(border=True):
        st.caption(
            "Baseline Adverse Drug Reaction (ADR) risk, from two predictor "
            "models -- entirely independent of the drug being requested."
        )
        model_a_col, model_b_col = st.columns(2)
        with model_a_col:
            with st.container(border=True):
                st.markdown("**Model A (9-Predictor ADR Risk Model)**")
                chronic_lung_disease = st.checkbox("Chronic lung disease")
                bleeding_or_gi_disorder = st.checkbox("Presenting with bleeding / GI disorder")
                syncope_on_admission = st.checkbox("Syncope on admission")
                on_antithrombotics = st.checkbox("On antithrombotics")
                on_diuretics = st.checkbox("On diuretics")
                on_raas_drugs = st.checkbox("On RAAS drugs (ACEi / ARB)")
        with model_b_col:
            with st.container(border=True):
                st.markdown("**Model B — GerontoNet (6-Predictor)**")
                num_concurrent_drugs = st.number_input(
                    "Number of concurrent drugs", min_value=0, max_value=30, value=0, step=1
                )
                history_of_adr = st.checkbox("History of ADR ⭐ (strongest predictor)")
                heart_failure = st.checkbox("Heart failure")
                liver_disease = st.checkbox("Liver disease")
                gt4_medical_conditions = st.checkbox("> 4 medical conditions")
                renal_failure = st.checkbox("Renal failure")

        adr_result = calculate_adr_risk(
            chronic_lung_disease=chronic_lung_disease,
            bleeding_or_gi_disorder=bleeding_or_gi_disorder,
            syncope_on_admission=syncope_on_admission,
            on_antithrombotics=on_antithrombotics,
            on_diuretics=on_diuretics,
            on_raas_drugs=on_raas_drugs,
            num_concurrent_drugs=num_concurrent_drugs,
            history_of_adr=history_of_adr,
            heart_failure=heart_failure,
            liver_disease=liver_disease,
            gt4_medical_conditions=gt4_medical_conditions,
            renal_failure=renal_failure,
        )
        st.session_state["adr_risk_flag"] = adr_result["adr_risk_flag"]

        if adr_result["high_baseline_adr_risk"]:
            reasons_html = html.escape("; ".join(adr_result["reasons"]))
            st.markdown(
                f"<div class='adr-banner adr-banner-high'>⚠️ "
                f"{html.escape(adr_result['adr_risk_flag'])} — {reasons_html}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='adr-banner adr-banner-standard'>✅ Standard baseline ADR risk</div>",
                unsafe_allow_html=True,
            )

    st.header("🧬 LAYER 3: PGx Triage & Decision Support")
    with st.container(border=True):
        col_drug, col_meds = st.columns(2)
        with col_drug:
            drug = st.selectbox("Drug Requested", DRUG_OPTIONS)
        with col_meds:
            concomitant_drugs_text = st.text_input(
                "Current Medications",
                placeholder="e.g. Omeprazole, Amiodarone",
                help="Comma-separated. Checked against known severe interactions. "
                     f"Interactions are modeled for: {', '.join(d.title() for d in ALL_INTERACTING_DRUGS)}.",
            )
        concurrent_medications = [d.strip() for d in concomitant_drugs_text.split(",") if d.strip()]
        st.session_state["layer3_drug"] = drug

        diagnostic_data_choice = st.radio("Diagnostic Data Available:", DIAGNOSTIC_DATA_OPTIONS, horizontal=True)

    if diagnostic_data_choice in ("Genotype Data", "Phenotype / TDM Data"):
        # Path A: a PGx test result already exists -- go straight to interpretation.
        test_type = "Genotype" if diagnostic_data_choice == "Genotype Data" else "Phenotype"

        with st.container(border=True):
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
                    _alert_card(
                        "high", "⚠️ HIGH RISK",
                        f"{html.escape(result['reason'])}<br><br>"
                        f"<b>Recommended Action &amp; Dosage:</b> "
                        f"{html.escape(result['recommendation_and_dosage'])}",
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
                    _alert_card(
                        "low", "✅ NO ACTIONABLE ALERT",
                        f"{html.escape(result['reason'])}<br><br>"
                        f"<b>Recommended Action &amp; Dosage:</b> "
                        f"{html.escape(result['recommendation_and_dosage'])}",
                    )
                    if st.button("Accept"):
                        _log_and_export("ACCEPTED")

                else:
                    _alert_card("info", "ℹ️ INFO", html.escape(result["reason"]))

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

    else:
        # Path B: no PGx result yet -- run the Pre-Test Triage Engine instead.
        with st.container(border=True):
            st.subheader("Pre-Test PGx Actionability Triage")
            st.caption(
                "No genotype or phenotype data available. Tier 1 (Clinical Engine: "
                "exact numeric labs) and Tier 2 (DDI Engine) combine with the Layer "
                "2 ADR risk flag above to answer one question before any genetic "
                "test is ordered: is PGx testing for this drug actually likely to "
                "change this patient's management?"
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

            triage_clicked = st.button("🧬 Run Triage", type="primary")

            if triage_clicked:
                st.session_state["triage_result"] = triage_pgx_actionability(
                    drug, concurrent_medications,
                    age=age, weight=weight, egfr=egfr, alt_ast=alt_ast,
                    platelets=platelets, pt_inr=pt_inr,
                    high_baseline_adr_risk=adr_result["high_baseline_adr_risk"],
                )
                st.session_state["triage_drug"] = drug

            triage_result = st.session_state.get("triage_result")

            if not triage_result:
                st.info("Enter the available labs above, then click Run Triage.")
            else:
                triage_drug = st.session_state.get("triage_drug", drug)
                triage_state = triage_result["triage"]
                triage_drug_safe = html.escape(triage_drug)

                if triage_state == TRIAGE_HIGH:
                    _alert_card(
                        "high", "🔴 HIGH PRIORITY",
                        f"PGx testing for <b>{triage_drug_safe}</b> is strongly indicated.",
                    )
                elif triage_state == TRIAGE_CONSIDER:
                    _alert_card(
                        "consider", "🟡 CONSIDER",
                        f"Genetic information for <b>{triage_drug_safe}</b> may influence treatment.",
                    )
                else:
                    _alert_card(
                        "low", "🟢 LOW PRIORITY",
                        f"PGx testing for <b>{triage_drug_safe}</b> is unlikely to change management.",
                    )

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

_similar_cases_sidebar_panel()

with tab2:
    st.subheader("Audit & Governance Log")
    st.caption("Full history of clinician decisions on PRISM-AIIMS recommendations.")
    logs_df = get_all_logs()
    if logs_df.empty:
        st.info("No decisions have been recorded yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)
