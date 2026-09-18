import html
import json

import streamlit as st

from abdm.fhir_builder import generate_fhir_bundle
from engine.clinical import ADR_RISK_HIGH, calculate_adr_risk
from engine.ddi import ALL_INTERACTING_DRUGS
from engine.rules import (
    EVIDENCE_SOURCE,
    GUIDELINE_VERSION,
    RISK_HIGH,
    RISK_NO_ALERT,
    RULE_VERSION,
    evaluate_prescription,
)
from engine.triage import (
    ETHNICITY_OPTIONS,
    TRIAGE_CONSIDER,
    TRIAGE_HIGH,
    genomeindia_population_priority,
    triage_pgx_actionability,
)
from storage.audit_logger import get_all_logs, log_decision

SOFTWARE_VERSION = "PRISM-AIIMS v8.0.0"

st.set_page_config(page_title="PRISM-AIIMS", layout="wide")

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], [class*="st-"], [data-testid] {
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif !important;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {visibility: hidden;}

.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 10px !important;
    border: 1px solid rgba(0, 0, 0, 0.08);
    box-shadow: 0 1px 6px rgba(0, 0, 0, 0.05);
}

div[data-testid="stMetric"] {
    background-color: rgba(127, 127, 127, 0.05);
    border: 1px solid rgba(127, 127, 127, 0.16);
    border-radius: 8px;
    padding: 14px 10px 8px 10px;
}

section[data-testid="stSidebar"] {
    border-right: 1px solid rgba(0, 0, 0, 0.08);
}

.pgx-card {
    border-radius: 8px;
    padding: 18px 22px;
    margin: 10px 0 16px 0;
    border: 1px solid rgba(0, 0, 0, 0.08);
    font-size: 1.0rem;
    line-height: 1.5;
}
.pgx-card h3 {margin-top: 0; margin-bottom: 6px; font-weight: 600;}
.pgx-card-high {background: #fdecea; border-left: 5px solid #b3261e; color: #5c140f;}
.pgx-card-consider {background: #fef7e0; border-left: 5px solid #b06f00; color: #543e00;}
.pgx-card-low {background: #e6f4ea; border-left: 5px solid #1e7b34; color: #103e1a;}
.pgx-card-info {background: #e8f0fe; border-left: 5px solid #1a56b0; color: #0b3d91;}

.adr-banner {
    border-radius: 8px;
    padding: 14px 18px;
    font-weight: 600;
    margin-top: 8px;
    border: 1px solid rgba(0, 0, 0, 0.08);
}
.adr-banner-high {background: #fdecea; border-left: 5px solid #b3261e; color: #5c140f;}
.adr-banner-standard {background: #e6f4ea; border-left: 5px solid #1e7b34; color: #103e1a;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("PRISM-AIIMS")
st.caption("Cost-Conscious Pre-Test Triage Engine and Clinical Decision Support System")
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

GENOTYPING_AVAILABILITY_OPTIONS = ["Available", "Not Available"]

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
                     "'Genotype' as the Result Type above instead.",
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
                 "Result Type above.",
        )
        return None
    if spec["type"] == "select":
        return st.selectbox("Test Result", spec["options"], help=spec.get("help"))
    value = st.number_input(
        spec["label"], min_value=spec["min"], max_value=spec["max"],
        value=spec["default"], step=spec["step"], help=spec.get("help"),
    )
    return str(value)


_LAB_FLAG_OPTIONS = ["Missing Data", "Normal", "Abnormal"]
_LAB_FLAG_STATE = {"Missing Data": None, "Normal": False, "Abnormal": True}


def _lab_flag_input(label: str, key: str):
    """Render a strict three-valued state selector for a single Layer 1
    laboratory parameter: True (Abnormal), False (Normal), or None (Missing
    Data) -- never a raw numeric reading. Selecting Abnormal immediately
    transitions this parameter's backend state to ABNORMAL -> FLAG the
    instant the widget resolves; there is no intermediate numeric
    comparison anywhere downstream of this function.
    """
    choice = st.radio(label, _LAB_FLAG_OPTIONS, horizontal=True, key=key)
    flag = _LAB_FLAG_STATE[choice]
    if flag is True:
        st.error(f"ABNORMAL → FLAG: {label}")
    return flag


TACROLIMUS_INDICATION_OPTIONS = ["Kidney Transplant", "Liver Transplant", "Other / Unspecified"]


def _render_clinical_context_inputs(drug: str, test_type: str) -> dict:
    """Render drug-specific clinical-context inputs that refine, but never
    replace, the genotype/phenotype rule: Tacrolimus's transplant indication
    (which sets the TDM target trough range) and G6PD's local laboratory
    reference range (since the enzyme-activity assay is not standardized
    across labs). Returns kwargs to merge into evaluate_prescription(...).
    """
    drug_key = drug.lower()
    context = {}
    if drug_key == "tacrolimus":
        indication = st.selectbox(
            "Indication / Clinical Context", TACROLIMUS_INDICATION_OPTIONS,
            help="Sets the therapeutic trough target range used by the TDM "
                 "alert below; transplant protocols differ in target trough "
                 "by indication.",
        )
        context["indication"] = None if indication == "Other / Unspecified" else indication
    elif drug_key in ("primaquine", "rasburicase") and test_type == "Phenotype":
        context["reference_range_low"] = st.number_input(
            "Local Laboratory Reference Range -- Lower Limit of Normal (%)",
            min_value=0.0, max_value=100.0, value=10.0, step=0.5,
            help="G6PD enzyme-activity assays are not standardized across "
                 "labs; enter this lab's own lower limit of normal rather "
                 "than relying on a fixed cutoff.",
        )
    return context


def _alert_card(level: str, title: str, body_html: str) -> None:
    """Render a large, colored alert card (level: 'high'/'consider'/'low'/'info')."""
    st.markdown(
        f"<div class='pgx-card pgx-card-{level}'><h3>{title}</h3>{body_html}</div>",
        unsafe_allow_html=True,
    )


_MOCK_CASE_REPORT_QUERIES = {
    "ADR Risk": "https://pubmed.ncbi.nlm.nih.gov/?term=adverse+drug+reaction+case+report",
    "Family Risk": "https://pubmed.ncbi.nlm.nih.gov/?term=familial+pharmacogenomic+risk+case+report",
    "Allergic Risk": "https://pubmed.ncbi.nlm.nih.gov/?term=drug+allergy+case+report",
}


def _web_search_mockup(adatip_high: bool, allergy_history: bool, family_history: bool) -> None:
    """Layer 2's Web Search mockup: three independent literature queries,
    one per risk dimension (ADR Risk, Family Risk, Allergic Risk), each
    evaluated against its own boolean input variable rather than a single
    combined flag. No live search is performed server-side by PRISM-AIIMS
    itself -- each query term links out to a real PubMed search so a
    clinician can inspect actual literature, but the case counts below are
    illustrative placeholders, not the result of an executed search.
    """
    st.markdown("**Web Search — Related Case Reports (Prototype)**")
    query_flags = {
        "ADR Risk": adatip_high,
        "Family Risk": family_history,
        "Allergic Risk": allergy_history,
    }
    for label, flag in query_flags.items():
        case_count = 4 if flag else 1
        url = _MOCK_CASE_REPORT_QUERIES[label]
        st.markdown(
            f"Querying literature for “{label}”... found {case_count} "
            f"similar case report(s). [Search PubMed]({url})"
        )
    st.caption(
        "This preview's case counts are generated locally for demonstration "
        "purposes; PRISM-AIIMS performs no server-side literature search of "
        "its own."
    )


def _similar_cases_sidebar_panel() -> None:
    with st.sidebar:
        st.markdown("---")
        st.subheader("Live Clinical Literature & Similar Cases (Prototype)")
        age_val = st.session_state.get("patient_age")
        drug_val = st.session_state.get("requested_drug")
        if age_val is None or drug_val is None:
            st.caption(
                "Complete Layer 1 and Layer 3 above to preview literature "
                "matches here."
            )
            return

        adr_flag = st.session_state.get("adr_risk_flag")
        triage_result = st.session_state.get("triage_result")
        eval_result = st.session_state.get("result")

        if triage_result:
            outcome_note = f"Most recent triage outcome referenced: {triage_result['triage']}."
        elif eval_result:
            outcome_note = f"Most recent evaluation outcome referenced: {eval_result['risk']}."
        else:
            outcome_note = None

        case_count = 4 if adr_flag == ADR_RISK_HIGH else 2
        risk_profile = "high ADR risk profiles" if adr_flag == ADR_RISK_HIGH else "standard-risk profiles"

        st.markdown(f"**Querying recent literature for {html.escape(drug_val)}...**")
        st.markdown(f"Found {case_count} similar cases (age approximately {age_val}) with {risk_profile}.")
        if outcome_note:
            st.caption(outcome_note)
        st.caption(
            "This preview is generated locally for demonstration purposes and "
            "does not perform a live literature search."
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
        # Per-rule provenance (guideline_url / evidence_date), when the
        # matched rule has any, takes precedence over the coarse whole-engine
        # fallback constants -- there is no single blanket guideline label.
        guideline_version=ctx.get("evidence_date") or GUIDELINE_VERSION,
        rule_version=ctx.get("rule_hash") or RULE_VERSION,
        evidence_source=ctx.get("guideline_url") or EVIDENCE_SOURCE,
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
    st.header("Layer 1: Clinical Details")
    with st.container(border=True):
        st.markdown("**Demographics**")
        col1, col2, col3 = st.columns(3)
        with col1:
            patient_name = st.text_input("Name", placeholder="e.g. Ramesh Kumar")
        with col2:
            patient_id = st.text_input("Patient ID (Medical Record Number)", placeholder="e.g. PT-1001")
        with col3:
            age = st.number_input("Age (years)", min_value=0, max_value=120, value=40, step=1)

        st.markdown("**Vitals**")
        vcol0, vcol1, vcol2, vcol3, vcol4, vcol5, vcol6 = st.columns(7)
        with vcol0:
            weight = st.number_input("Weight (kg)", min_value=0.0, max_value=250.0, value=70.0, step=0.5)
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

        st.markdown("**Laboratory Data**")
        st.caption(
            "Each parameter is a strict three-valued state -- Abnormal "
            "(True), Normal (False), or Missing Data (None). This boolean/"
            "None flag, not a numeric reading, is what crosses into the "
            "backend state machine below. Marking a parameter Abnormal "
            "immediately transitions it to its ABNORMAL → FLAG state."
        )
        lab_col1, lab_col2 = st.columns(2)
        with lab_col1:
            egfr_abnormal = _lab_flag_input("eGFR (Renal Function)", key="egfr_flag")
            alt_ast_abnormal = _lab_flag_input("ALT/AST (Hepatic Function)", key="alt_ast_flag")
        with lab_col2:
            platelets_abnormal = _lab_flag_input("Platelets (Coagulation/CBC)", key="platelets_flag")
            pt_inr_abnormal = _lab_flag_input("PT/INR (Coagulation/CBC)", key="pt_inr_flag")

    st.session_state["patient_age"] = age

    st.header("Layer 2: ADR Risk Prediction")
    with st.container(border=True):
        st.caption(
            "ADATIP and GerontoNet are evaluated as isolated execution "
            "contexts -- two statistically independent predictor sets over "
            "the same patient, each producing its own verdict below, with "
            "neither computation observing the other's internal state."
        )
        adatip_col, gerontonet_col = st.columns(2)
        with adatip_col:
            with st.container(border=True):
                st.markdown("**ADATIP 9-Predictor Model (Isolated Context)**")
                st.caption(f"Age (from Layer 1): {age} years")
                chronic_lung_disease = st.checkbox("Chronic lung disease")
                presenting_respiratory_disorder = st.checkbox(
                    "Primary presenting complaints of respiratory disorders"
                )
                presenting_bleeding_disorder = st.checkbox(
                    "Primary presenting complaints of bleeding disorders"
                )
                presenting_gi_disorder = st.checkbox(
                    "Primary presenting complaints of GI disorders"
                )
                syncope_on_admission = st.checkbox("Syncope on hospital admission")
                antithrombotics = st.checkbox("Antithrombotics")
                diuretics = st.checkbox("Diuretics")
                raas_drugs = st.checkbox("RAAS drugs")
        with gerontonet_col:
            with st.container(border=True):
                st.markdown("**GerontoNet Risk Score (Isolated Context)**")
                st.caption(
                    "History of ADR is captured under General Clinical History "
                    "below. Scored using the actual validated GerontoNet point "
                    "weights, not a simple predictor count."
                )
                num_drugs = st.number_input(
                    "Number of concurrent drugs", min_value=0, max_value=30, value=0, step=1
                )
                heart_failure = st.checkbox("Heart failure")
                liver_disease = st.checkbox("Liver disease")
                gte4_comorbid_conditions = st.checkbox("≥ 4 comorbid conditions")
                renal_failure = st.checkbox("Renal failure")

        st.markdown("**General Clinical History**")
        hist_col1, hist_col2, hist_col3 = st.columns(3)
        with hist_col1:
            previous_adr_history = st.checkbox("Previous ADR history")
        with hist_col2:
            allergy_history = st.checkbox("Allergy history")
        with hist_col3:
            family_history = st.checkbox("Family history")

        adr_result = calculate_adr_risk(
            age=age,
            chronic_lung_disease=chronic_lung_disease,
            presenting_respiratory_disorder=presenting_respiratory_disorder,
            presenting_bleeding_disorder=presenting_bleeding_disorder,
            presenting_gi_disorder=presenting_gi_disorder,
            syncope_on_admission=syncope_on_admission,
            antithrombotics=antithrombotics,
            diuretics=diuretics,
            raas_drugs=raas_drugs,
            num_drugs=num_drugs,
            heart_failure=heart_failure,
            liver_disease=liver_disease,
            gte4_comorbid_conditions=gte4_comorbid_conditions,
            renal_failure=renal_failure,
            previous_adr_history=previous_adr_history,
            allergy_history=allergy_history,
            family_history=family_history,
        )
        st.session_state["adr_risk_flag"] = adr_result["adr_risk_flag"]

        gerontonet_score = adr_result["gerontonet_score"]
        score_col, category_col = st.columns(2)
        score_col.metric(
            "GerontoNet ADR Risk Score",
            f"{gerontonet_score['total_score']} / {gerontonet_score['max_score']}",
        )
        category_col.metric("GerontoNet Risk Category", gerontonet_score["risk_category"])

        st.markdown("---")
        verdict_col1, verdict_col2 = st.columns(2)
        adatip_high = adr_result["adatip_isolated_verdict"] == "High Risk"
        gerontonet_high = adr_result["gerontonet_isolated_verdict"] == "High Risk"
        with verdict_col1:
            banner_class = "adr-banner-high" if adatip_high else "adr-banner-standard"
            st.markdown(
                f"<div class='adr-banner {banner_class}'>ADR in acute vulnerable patient: "
                f"{html.escape(adr_result['adatip_isolated_verdict'])}</div>",
                unsafe_allow_html=True,
            )
        with verdict_col2:
            banner_class = "adr-banner-high" if gerontonet_high else "adr-banner-standard"
            st.markdown(
                f"<div class='adr-banner {banner_class}'>ADR in chronic fragility: "
                f"{html.escape(adr_result['gerontonet_isolated_verdict'])}</div>",
                unsafe_allow_html=True,
            )

        st.markdown("")
        _web_search_mockup(adatip_high, allergy_history, family_history)

    st.header("Layer 3: Pharmacogenomics")
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
        st.session_state["requested_drug"] = drug
        st.caption(
            "Note: This DDI database is a curated MVP subset, not a "
            "comprehensive interaction checker."
        )

        genotyping_available = st.radio(
            "Genotyping Results:", GENOTYPING_AVAILABILITY_OPTIONS, horizontal=True
        )

    if genotyping_available == "Available":
        # Path A: a PGx result already exists -- go straight to the
        # standard CPIC allele pathway lookup.
        with st.container(border=True):
            st.subheader("CPIC Allele Pathway Lookup")
            result_type_choice = st.radio(
                "Result Type:", ["Genotype", "Phenotype / TDM"], horizontal=True
            )
            test_type = "Genotype" if result_type_choice == "Genotype" else "Phenotype"
            test_result = _render_test_result_input(drug, test_type)
            clinical_context = _render_clinical_context_inputs(drug, test_type)
            evaluate_clicked = st.button("Evaluate", type="primary")

            if evaluate_clicked:
                if not patient_id.strip():
                    st.warning("Patient ID is required before evaluating.")
                else:
                    result = evaluate_prescription(drug, test_type, test_result, **clinical_context)
                    st.session_state["result"] = result
                    st.session_state["triage_result"] = None
                    st.session_state["eval_context"] = {
                        "patient_id": patient_id.strip(),
                        "drug": drug,
                        "test_type": test_type,
                        "test_result": test_result,
                        "recommendation_given": result["recommendation_and_dosage"] or result["reason"],
                        "guideline_url": result.get("guideline_url"),
                        "evidence_date": result.get("evidence_date"),
                        "rule_hash": result.get("rule_hash"),
                    }
                    st.session_state["fhir_bundle"] = None

            result = st.session_state.get("result")

            if not result:
                st.info("Select a test result above, then click Evaluate.")
            else:
                st.subheader("Decision Support Output")
                if result["risk"] == RISK_HIGH:
                    _alert_card(
                        "high", "HIGH RISK",
                        f"{html.escape(result['reason'])}<br><br>"
                        f"<b>Recommended Action &amp; Dosage:</b> "
                        f"{html.escape(result['recommendation_and_dosage'])}",
                    )
                elif result["risk"] == RISK_NO_ALERT:
                    _alert_card(
                        "low", "NO ACTIONABLE ALERT",
                        f"{html.escape(result['reason'])}<br><br>"
                        f"<b>Recommended Action &amp; Dosage:</b> "
                        f"{html.escape(result['recommendation_and_dosage'])}",
                    )
                else:
                    _alert_card("info", "INFORMATION", html.escape(result["reason"]))

                if result.get("guideline_url"):
                    st.caption(
                        f"Rule provenance -- Guideline: {result['guideline_url']} | "
                        f"Evidence date: {result.get('evidence_date')} | "
                        f"Rule hash: {result.get('rule_hash')}"
                    )
                st.caption(
                    "Accept or Override this recommendation in the Reporting "
                    "and Audit section at the bottom of this page."
                )

    else:
        # Path B: no PGx result yet -- run the Pre-Test Triage Engine instead.
        with st.container(border=True):
            st.subheader("Pre-Test PGx Actionability Triage")
            st.caption(
                "No genotype or phenotype data available. The Layer 1 lab "
                "flags and the DDI Engine combine with Layer 2's baseline "
                "ADR risk verdict to answer one question before any genetic "
                "test is ordered: is PGx testing for this drug actually "
                "likely to change this patient's management?"
            )

            triage_clicked = st.button("Run Triage", type="primary")

            if triage_clicked:
                if not patient_id.strip():
                    st.warning("Patient ID is required before running triage.")
                else:
                    triage_result = triage_pgx_actionability(
                        drug, concurrent_medications,
                        age=age, weight=weight,
                        egfr_abnormal=egfr_abnormal, alt_ast_abnormal=alt_ast_abnormal,
                        platelets_abnormal=platelets_abnormal, pt_inr_abnormal=pt_inr_abnormal,
                        high_baseline_adr_risk=adr_result["high_baseline_adr_risk"],
                    )
                    st.session_state["triage_result"] = triage_result
                    st.session_state["triage_drug"] = drug
                    st.session_state["result"] = None
                    st.session_state["eval_context"] = {
                        "patient_id": patient_id.strip(),
                        "drug": drug,
                        "test_type": "Pre-Test Triage (Genotyping Not Available)",
                        "test_result": "N/A",
                        "recommendation_given": (
                            f"Testing Priority: {triage_result['triage']}; "
                            f"CPIC Recommendation: {triage_result['cpic_testing_recommendation']}"
                        ),
                        "guideline_url": None,
                        "evidence_date": None,
                        "rule_hash": None,
                    }
                    st.session_state["fhir_bundle"] = None

            triage_result = st.session_state.get("triage_result")

            if not triage_result:
                st.info("Click Run Triage above to resolve the Testing-Priority state machine.")
            else:
                triage_drug = st.session_state.get("triage_drug", drug)
                triage_state = triage_result["triage"]
                triage_drug_safe = html.escape(triage_drug)

                if triage_state == TRIAGE_HIGH:
                    _alert_card(
                        "high", "HIGH PRIORITY",
                        f"PGx testing for <b>{triage_drug_safe}</b> is strongly indicated.",
                    )
                elif triage_state == TRIAGE_CONSIDER:
                    _alert_card(
                        "consider", "CONSIDER",
                        f"Genetic information for <b>{triage_drug_safe}</b> may influence treatment.",
                    )
                else:
                    _alert_card(
                        "low", "LOW PRIORITY",
                        f"PGx testing for <b>{triage_drug_safe}</b> is unlikely to change management.",
                    )

                st.markdown("**CPIC Pre-Test Testing Recommendation:**")
                st.metric("Testing Recommendation", triage_result["cpic_testing_recommendation"])

                st.markdown("**Rationale (PGx Actionability):**")
                for line in triage_result["rationale"]:
                    st.markdown(f"- {line}")

                if triage_result.get("warnings"):
                    st.markdown("**Lab-Driven Safety Warnings:**")
                    for warning_text in triage_result["warnings"]:
                        st.error(warning_text)

                contextual_modifier = triage_result.get("contextual_modifier")
                if contextual_modifier:
                    st.markdown("**Contextual Modifier (Layer 2 Baseline ADR Risk Covariate):**")
                    st.info(contextual_modifier["note"])

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
                    st.markdown("**Clinical Engine (Layer 1 Lab Flags) Findings:**")
                    st.json(triage_result["clinical_findings"])

                st.caption(
                    "Accept or Override this recommendation in the Reporting "
                    "and Audit section at the bottom of this page."
                )

        with st.container(border=True):
            st.subheader("Population Context: GenomeIndia (Isolated, Decoupled Module)")
            st.caption(
                "This output is an independent variable: a function of "
                "ethnicity alone. It is never integrated, multiplied, or "
                "combined with Layer 1 or Layer 2 outputs, and it never "
                "enters the Testing-Priority decision matrix above -- it "
                "serves as an independent, population-based recommendation "
                "only."
            )
            ethnicity = st.selectbox("Ethnicity", ETHNICITY_OPTIONS, key="ethnicity_select")
            genomeindia_result = genomeindia_population_priority(ethnicity)
            st.metric("GenomeIndia Population Priority", genomeindia_result["genomeindia_priority"])
            st.session_state["genomeindia_result"] = genomeindia_result
            st.warning(
                "Population-level frequencies act as an isolated, "
                "independent contextual signal; they cannot determine an "
                "individual's genotype, do not replace clinical prescribing "
                "guidelines, and do not alter the Testing-Priority state "
                "above."
            )

    if genotyping_available == "Available":
        st.session_state["genomeindia_result"] = None

    st.header("Reporting and Audit")
    with st.container(border=True):
        st.caption(
            "An integrated summary of Layer 1, Layer 2, and Layer 3 "
            "outputs. Per the CRITICAL DECOUPLING constraint in Layer 3, "
            "the GenomeIndia population-context output (when present) is "
            "reported below without being merged into any other value."
        )

        st.markdown("**Layer 1 — Clinical Details (Laboratory Flags)**")
        lab_flag_summary = {
            "eGFR (Renal Function)": egfr_abnormal,
            "ALT/AST (Hepatic Function)": alt_ast_abnormal,
            "Platelets (Coagulation/CBC)": platelets_abnormal,
            "PT/INR (Coagulation/CBC)": pt_inr_abnormal,
        }
        for label, flag in lab_flag_summary.items():
            state = "ABNORMAL → FLAG" if flag is True else ("Normal" if flag is False else "Missing Data")
            st.markdown(f"- {label}: **{state}**")

        st.markdown("**Layer 2 — ADR Risk Prediction (Isolated Verdicts)**")
        st.markdown(f"- ADR in acute vulnerable patient: **{adr_result['adatip_isolated_verdict']}**")
        st.markdown(f"- ADR in chronic fragility: **{adr_result['gerontonet_isolated_verdict']}**")

        st.markdown("**Layer 3 — Pharmacogenomics**")
        report_result = st.session_state.get("result")
        report_triage_result = st.session_state.get("triage_result")
        report_genomeindia_result = st.session_state.get("genomeindia_result")

        if genotyping_available == "Available" and report_result:
            st.markdown(f"- CPIC Allele Pathway Outcome: **{report_result['risk']}**")
            st.markdown(
                f"- Recommendation & Dosage: "
                f"{report_result.get('recommendation_and_dosage') or report_result.get('reason')}"
            )
        elif genotyping_available == "Not Available" and report_triage_result:
            st.markdown(f"- Testing Priority: **{report_triage_result['triage']}**")
            st.markdown(
                f"- CPIC Pre-Test Recommendation: "
                f"**{report_triage_result['cpic_testing_recommendation']}**"
            )
        else:
            st.info("Complete Layer 3 above (Evaluate or Run Triage) to populate this report.")

        if report_genomeindia_result:
            st.markdown(
                f"- GenomeIndia Population Priority (isolated, decoupled): "
                f"**{report_genomeindia_result['genomeindia_priority']}** "
                f"(ethnicity: {report_genomeindia_result['ethnicity']})"
            )

        st.markdown("---")
        report_ready = bool(report_result or report_triage_result)
        if not report_ready:
            st.info("Run an evaluation or triage in Layer 3 above before recording a decision.")
        else:
            col_accept, col_override = st.columns(2)
            with col_accept:
                if st.button("Accept", key="report_accept"):
                    _log_and_export("ACCEPTED")
            with col_override:
                if st.button("Override", key="report_override"):
                    st.session_state["show_report_override"] = True

            if st.session_state.get("show_report_override"):
                justification = st.text_area(
                    "Clinical Justification for Override", key="report_override_reason"
                )
                if st.button("Submit Override", key="report_submit_override"):
                    if justification.strip():
                        _log_and_export("OVERRIDDEN", justification.strip())
                    else:
                        st.info("Please provide a justification before submitting the override.")

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

_similar_cases_sidebar_panel()

with tab2:
    st.subheader("Audit & Governance Log")
    st.caption("Full history of clinician decisions on PRISM-AIIMS recommendations.")
    logs_df = get_all_logs()
    if logs_df.empty:
        st.info("No decisions have been recorded yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)
