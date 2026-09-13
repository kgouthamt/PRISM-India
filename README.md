# PRISM-India
### Bedside Pharmacogenomics Decision Support
**Team ID:** DENDRITE-PE-XD-018

---

## Executive Summary

Adverse drug reactions driven by genetic variation are a well-documented, largely preventable cause of harm — yet the pharmacogenomic (PGx) evidence base (CPIC, ABDM's own genomics roadmap) rarely reaches the point of care in a form a prescriber can act on in seconds. A lab report showing `CYP2C19 *2/*2` or `HLA-B*15:02: Positive` is clinically meaningless to a doctor mid-consult unless it is translated into a concrete prescribing action: *stop, switch, or proceed*.

**PRISM-India closes that gap.** It is a bedside decision-support layer that sits between the genotype and the prescription pad: a clinician enters (or the system pulls) a patient's genotype and the drug they intend to prescribe, and PRISM instantly returns a deterministic, guideline-backed verdict — **SAFE** or **HIGH RISK** — along with an actionable alternative. Every decision a clinician makes in response, whether they accept the recommendation or override it, is captured in an immutable audit trail and exported as an ABDM-compliant FHIR bundle, so the system is not just a calculator but a governance-ready component of the national digital health stack.

In short: PRISM-India turns a genotype into a prescribing decision, and turns that decision into an auditable, interoperable clinical record.

---

## Clinical Workflow

### The 4-Pair MVP Logic

PRISM-India's rule engine (`engine/rules.py`) implements four deterministic gene–drug pairs, each mapped to a single, unambiguous prescribing action:

| # | Gene | Drug | Trigger | Verdict | Recommended Action |
|---|------|------|---------|---------|---------------------|
| 1 | **CYP2C19** | Clopidogrel | Genotype carries `*2` or `*3` | HIGH RISK — reduced platelet-inhibitor activation | Switch to **Prasugrel** |
| 2 | **HLA-B\*15:02** | Carbamazepine | Allele status **Positive** | HIGH RISK — Stevens-Johnson Syndrome / TEN | **Avoid** carbamazepine |
| 3 | **HLA-B\*58:01** | Allopurinol | Allele status **Positive** | HIGH RISK — severe cutaneous adverse reaction | Switch to **Febuxostat** |
| 4 | **HLA-B\*57:01** | Abacavir | Allele status **Positive** | HIGH RISK — hypersensitivity reaction | **Avoid** abacavir |

A normal/negative genotype (e.g. `*1/*1`, or allele status **Negative**) for any of the four pairs returns a **SAFE** verdict. Any genotype or drug outside this MVP scope returns a transparent `No actionable guidance -> No automated prescribing recommendation`, rather than a false negative — PRISM never fabricates confidence it doesn't have.

### The CPIC Guideline Lock

Every rule is a direct, hard-coded translation of a published **CPIC (Clinical Pharmacogenetics Implementation Consortium)** guideline. This is a deliberate design choice for a clinical safety tool:

- **Deterministic, not probabilistic.** The engine is pure Python logic (no ML, no inference) — the same input always produces the same output, which is a requirement for clinical auditability and regulatory trust.
- **No silent drift.** Thresholds and recommendations cannot change without a code change and review, unlike a model that could quietly re-weight its own outputs.
- **Traceable to source.** Every verdict can be traced back to the specific CPIC guideline pair that produced it, which is essential when a clinician or auditor asks "why did the system say this?"

This "guideline lock" is what makes PRISM-India defensible as a *decision support* tool rather than a black box — it augments the clinician's judgement instead of replacing it.

---

## Safety & Governance

A decision-support tool that clinicians cannot override, or whose recommendations vanish the moment the screen changes, is not safe for a real clinical environment. PRISM-India is built around two governance pillars:

### Clinician Override System

PRISM never blocks a prescription — it flags risk and hands the final call back to the clinician:

- On a **HIGH RISK** verdict, the clinician can **Accept** the system's alternative recommendation, or **Override** it.
- Overriding requires a **mandatory free-text clinical justification** (e.g. "patient tolerated this drug previously; specialist consulted") — an override with no reasoning cannot be submitted.
- Every decision — `ACCEPTED` or `OVERRIDDEN`, with the justification when applicable — is written immediately to a persistent **SQLite audit log** (`storage/audit_logger.py`, `decisions.db`) with a timestamp, patient ID, drug, genotype, and the recommendation that was given.
- The **Audit & Governance Log** tab in the dashboard surfaces this entire history in a live table, so a hospital's clinical governance committee can review — in real time — exactly which PRISM warnings were followed and which were overridden, and why.

This turns "doctor overrode an AI warning" from an invisible risk into a reviewable, defensible clinical decision.

### ABDM / FHIR Interoperability Export

India's Ayushman Bharat Digital Mission (ABDM) requires health data to be portable across providers in a standard format. PRISM-India does not create a data silo:

- Every clinician decision (accepted or overridden) is compiled by `abdm/fhir_builder.py` into a standards-shaped **FHIR R4 `Bundle`** containing:
  - A **`DiagnosticReport`** resource capturing the patient's genotype/allele status and the PRISM recommendation as its conclusion.
  - A **`MedicationRequest`** resource capturing the final prescribed drug, the clinician's decision, and the override justification (if any) as a clinical note.
- The bundle is rendered live in an **"ABDM / FHIR Interoperability Record"** expander (`st.json`) directly in the dashboard, and can be downloaded as a `.json` file for ingestion into a Health Information Exchange, ABDM sandbox, or hospital EHR — no separate export tooling required.

---

## Execution Guide

PRISM-India is fully containerized. The only prerequisite is **Docker** and **Docker Compose**.

### 1. Clone the repository

```bash
git clone https://github.com/kgouthamt/PRISM-India.git
cd PRISM-India
```

### 2. Build and run with Docker Compose

```bash
docker compose up --build
```

This builds the image from the `python:3.11-slim` base, installs dependencies, and starts the Streamlit server on port `8501`. The `storage/` directory is mounted as a volume, so the audit log (`decisions.db`) **persists across container restarts**.

### 3. Open the dashboard

```
http://localhost:8501
```

### 4. Stop the application

```bash
docker compose down
```

### Running without Docker (local development)

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Project Structure

```
PRISM-India/
├── app.py                     # Streamlit clinical dashboard
├── engine/
│   └── rules.py                # CPIC-locked rule engine: evaluate_prescription()
├── storage/
│   └── audit_logger.py         # SQLite audit trail: log_decision(), get_all_logs()
├── abdm/
│   └── fhir_builder.py         # FHIR R4 Bundle generator: generate_fhir_bundle()
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
