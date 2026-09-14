# PRISM-India
### Bedside Pharmacogenomics Decision Support
**Team ID:** DENDRITE-PE-XD-018

---

## Executive Summary

Adverse drug reactions driven by genetic variation are a well-documented, largely preventable cause of harm — yet the pharmacogenomic (PGx) evidence base (CPIC) rarely reaches the point of care in a form a prescriber can act on in seconds. A lab report showing `CYP2C19 *2/*2` or `HLA-B*15:02: Positive` is clinically meaningless to a doctor mid-consult unless it is translated into a concrete prescribing action: *stop, switch, or proceed*.

**PRISM-India closes that gap.** It is a bedside decision-support layer that sits between the lab result and the prescription pad: a clinician selects the drug they intend to prescribe, indicates whether they're working from a **genotype assay** or a **phenotype/clinical test**, and chooses the exact result from a validated set of options — no free text. PRISM instantly returns a deterministic, guideline-backed verdict — **NO ACTIONABLE ALERT** or **HIGH RISK** — along with a specific recommended action *and dosage* (switch drug, reduce/increase/maintain a dose, or avoid entirely). Every decision a clinician makes in response, whether they accept the recommendation or override it, is captured alongside structured clinical-encounter metadata in an append-only audit trail and exported as an FHIR R4 bundle, so the system is not just a calculator but a governance-ready component moving toward interoperability with India's digital health stack.

In short: PRISM-India turns a genotype or phenotype result into a concrete, dosed prescribing decision, and turns that decision into an auditable, interoperable clinical record.

---

## Clinical Workflow

### The Genotype & Phenotype Dosage Engine

PRISM-India's rule engine (`engine/rules.py`) exposes a single function, `evaluate_prescription(drug, test_type, test_result)`, where `test_type` is `"Genotype"` or `"Phenotype"`. It covers seven drugs across two evidence modalities, each mapped to a specific, dosed prescribing action:

| Drug | Evidence | Trigger | Verdict | Recommended Action & Dosage |
|------|----------|---------|---------|-------------------------------|
| **Clopidogrel** | CYP2C19 Genotype | `*1/*1` (normal) | NO ACTIONABLE ALERT | Standard dose: 75 mg/day |
| **Clopidogrel** | CYP2C19 Genotype | `*1/*2` or `*1/*3` (intermediate) | HIGH RISK | Consider alternative P2Y12 inhibitor (prasugrel or ticagrelor) if no contraindication |
| **Clopidogrel** | CYP2C19 Genotype | `*2/*2`, `*2/*3`, `*3/*3` (poor) | HIGH RISK | Avoid clopidogrel; use alternative P2Y12 inhibitor (prasugrel or ticagrelor) if no contraindication |
| **Clopidogrel** | Platelet Reactivity (PRU) Phenotype | PRU > 208 | HIGH RISK | Recommend alternative P2Y12 inhibitor (prasugrel or ticagrelor) |
| **Clopidogrel** | Platelet Reactivity (PRU) Phenotype | PRU ≤ 208 | NO ACTIONABLE ALERT | Standard dose: 75 mg/day |
| **Carbamazepine** | HLA-B\*15:02 Genotype | Positive | HIGH RISK — Stevens-Johnson Syndrome / TEN | Avoid carbamazepine entirely |
| **Allopurinol** | HLA-B\*58:01 Genotype | Positive | HIGH RISK — severe cutaneous adverse reaction | Avoid allopurinol; consider alternative therapy based on clinical context |
| **Abacavir** | HLA-B\*57:01 Genotype | Positive | HIGH RISK — hypersensitivity reaction | Avoid abacavir entirely |
| **Primaquine / Rasburicase** | G6PD Genotype or Enzyme Activity Phenotype | Deficient variant, or activity < 10% | HIGH RISK — hemolytic anemia | Avoid drug entirely |
| **Tacrolimus** | **CYP3A5 Genotype** (starting-dose PGx) | Expresser (`*1/*1`, `*1/*3`) | HIGH RISK | Increase starting dose (~1.5–2x standard weight-based dose per CPIC); confirm with early trough monitoring |
| **Tacrolimus** | **CYP3A5 Genotype** (starting-dose PGx) | Non-expresser (`*3/*3`) | NO ACTIONABLE ALERT | Standard weight-based starting dose |
| **Tacrolimus** | **Trough Level Phenotype** (TDM alert) | > 15 ng/mL | HIGH RISK — nephrotoxicity | Reduce dose and recheck trough level |
| **Tacrolimus** | **Trough Level Phenotype** (TDM alert) | < 5 ng/mL | HIGH RISK — rejection risk | Increase dose and recheck trough level |
| **Tacrolimus** | **Trough Level Phenotype** (TDM alert) | 5–15 ng/mL | NO ACTIONABLE ALERT | Maintain current dose |

A normal/negative result (e.g. `*1/*1`, allele status **Negative**, or an enzyme level/trough comfortably inside range) returns **NO ACTIONABLE ALERT** — PRISM deliberately does not use the word "SAFE," since the absence of a flagged interaction is not a clinical guarantee of safety. Any drug, test type, or result outside this scope — an unrecognized diplotype, a non-numeric phenotype value, or a drug/test-type combination with no defined rule — returns a transparent `No actionable guidance -> No automated prescribing recommendation` (risk = `UNKNOWN`), rather than a false negative. PRISM never fabricates confidence it doesn't have.

**Tacrolimus is intentionally modeled as two separate rules**, not one: `_evaluate_tacrolimus_pgx` answers a one-time, pre-prescribing question ("what starting dose, given this patient's CYP3A5 genotype?"), while `_evaluate_tacrolimus_tdm` answers a recurring, post-prescribing question ("is this patient's current dose producing a safe blood level?"). They are dispatched by `test_type` and never share logic, because conflating a starting-dose genotype rule with a therapeutic drug monitoring (TDM) alert would blur two clinically distinct decisions with different triggers, different cadences, and different actions.

### The CPIC Guideline Lock

Every rule is a direct, hard-coded translation of a published **CPIC (Clinical Pharmacogenetics Implementation Consortium)** guideline, whether the supporting evidence is a genotype or a phenotypic/clinical test. This is a deliberate design choice for a clinical safety tool:

- **Deterministic, not probabilistic.** The engine is pure Python logic (no ML, no inference) — the same input always produces the same output, which is a requirement for clinical auditability and regulatory trust.
- **No silent drift.** Thresholds, dosages, and recommendations cannot change without a code change and review, unlike a model that could quietly re-weight its own outputs.
- **Traceable to source.** Every verdict carries an `evidence_type` field naming the exact gene, enzyme, or clinical marker it was based on, and every logged decision carries `guideline_version`, `rule_version`, and `evidence_source` provenance fields, so a clinician or auditor can always answer "why did the system say this, and against which version of which guideline?"

This "guideline lock" is what makes PRISM-India defensible as a *decision support* tool rather than a black box — it augments the clinician's judgement instead of replacing it.

---

## Structured Clinical Input

Earlier prototypes accepted the test result as free text. **Every genotype and phenotype input is now a validated `st.selectbox` or `st.number_input`** — a clinician can no longer type an ambiguous or malformed value into the field the rule engine keys its verdict on:

- Diplotypes (CYP2C19, CYP3A5) and allele/enzyme statuses (HLA-B, G6PD) are chosen from a fixed dropdown of the exact values the rule engine recognizes — including an explicit "not covered" option (e.g. `*1/*17`) so the UNKNOWN fallback path is reachable and honest, not hidden.
- Numeric phenotypes (PRU, G6PD enzyme activity %, tacrolimus trough level) are `st.number_input` fields with clinically sane min/max bounds and step sizes, not strings requiring downstream parsing.

### Clinical Encounter Metadata

Every evaluation is also anchored to a structured clinical context, captured in the sidebar and required before a decision can be logged: **Clinician ID**, **Institution**, **Encounter ID**, **Assay/Lab**, **Specimen Date**, and **Result Verification Status** (Verified / Preliminary / Unverified). This mirrors what a real audit or ABDM record actually needs to be usable downstream — a recommendation with no record of who reviewed it, which lab ran the assay, or whether the result was confirmed is not a governance-ready artifact.

---

## Safety & Governance

A decision-support tool that clinicians cannot override, or whose recommendations vanish the moment the screen changes, is not safe for a real clinical environment. PRISM-India is built around two governance pillars:

### Clinician Override System

PRISM never blocks a prescription — it flags risk and hands the final call back to the clinician:

- On a **HIGH RISK** verdict, the clinician can **Accept** the system's alternative recommendation, or **Override** it.
- Overriding requires a **mandatory free-text clinical justification** (e.g. "patient tolerated this drug previously; specialist consulted") — an override with no reasoning cannot be submitted.
- Logging is gated on the **Clinical Encounter Metadata** above: if Clinician ID, Institution, Encounter ID, or Assay/Lab is missing, the decision is not recorded and the clinician is prompted to complete them first.
- Every decision — `ACCEPTED` or `OVERRIDDEN`, with the justification when applicable — is written immediately to a persistent **SQLite audit log** (`storage/audit_logger.py`, `decisions.db`) with a local timestamp *and* a UTC timestamp, the full patient/drug/test/recommendation record, the structured clinical-encounter metadata, and system provenance fields (`guideline_version`, `rule_version`, `evidence_source`, `software_version`).
- **Schema changes are additive only.** If a decisions.db created under an older, narrower schema is opened, `_get_connection()` adds whatever columns it's missing via `ALTER TABLE ... ADD COLUMN` — it never drops or rebuilds the table, so existing audit rows are never destroyed by a rule-engine or schema upgrade.
- The **Audit & Governance Log** tab in the dashboard surfaces this entire history in a live table, so a hospital's clinical governance committee can review — in real time — exactly which PRISM warnings were followed and which were overridden, and why.

This turns "doctor overrode an AI warning" from an invisible risk into a reviewable, defensible clinical decision.

### FHIR R4 / ABDM-aligned Interoperability Export

India's Ayushman Bharat Digital Mission (ABDM) requires health data to be portable across providers in a standard format. PRISM-India does not create a data silo, but it also does not claim a certification it doesn't have — this is an **FHIR R4 / ABDM-aligned interoperability prototype**, not a validated, ABDM-compliant integration:

- Every clinician decision (accepted or overridden) is compiled by `abdm/fhir_builder.py` into a standards-shaped **FHIR R4 `Bundle`** containing:
  - A **`DiagnosticReport`** resource capturing the test type (Genotype/Phenotype), the raw test result, the PRISM recommendation as its conclusion, and — where provided — the performing clinician and specimen collection date.
  - A **`MedicationRequest`** resource capturing the final prescribed drug, the clinician's decision, the override justification (if any) as a clinical note, the requesting clinician, and the associated encounter.
  - Clinical-encounter and system-provenance fields with no matching native FHIR element (institution, guideline/rule/software version, evidence source) are carried as local `extension`s on the Bundle, rather than silently dropped or shoehorned into the wrong field.
- The bundle is rendered live in a **"FHIR R4 / ABDM-aligned Interoperability Record"** expander (`st.json`) directly in the dashboard, and can be downloaded as a `.json` file for ingestion into a Health Information Exchange, ABDM sandbox, or hospital EHR — no separate export tooling required.

---

## Automated Testing

`tests/test_rules.py` is a `unittest` suite covering the rule engine's core clinical logic and its fallback behavior: CYP2C19 normal/intermediate/poor metabolizer paths, an HLA-positive high-risk alert, an HLA-negative no-actionable-alert result, an unrecognized genotype, a malformed PRU value, an unsupported drug, and the CYP3A5 PGx / tacrolimus-trough TDM separation — 14 tests in total.

Run the suite from the project root:

```bash
python -m unittest tests.test_rules -v
```

or discover every test module under `tests/`:

```bash
python -m unittest discover -s tests -t . -v
```

Both commands exit `0` with `OK` when the suite passes and use only the Python standard library — no extra dependency is required beyond what's already in `requirements.txt`.

---

## Execution Guide

PRISM-India is fully containerized and runs identically on **Windows**, **macOS**, and **Linux**. The recommended path is Docker Compose; a native (non-Docker) path is also provided for local development.

### Prerequisites

| OS | Install |
|----|---------|
| **Windows 10/11** | [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) with the WSL2 backend enabled. Run all commands below from **PowerShell**, **Command Prompt**, or a **WSL2** terminal. |
| **macOS** (Intel or Apple Silicon) | [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/). Run all commands below from **Terminal**. |
| **Linux** | Docker Engine + the Compose plugin, e.g. on Ubuntu/Debian: `sudo apt-get update && sudo apt-get install docker.io docker-compose-plugin`. Add your user to the `docker` group (`sudo usermod -aG docker $USER`, then log out/in) to avoid needing `sudo` on every command. |

### 1. Clone the repository

Identical on all three platforms:

```bash
git clone https://github.com/kgouthamt/PRISM-India.git
cd PRISM-India
```

### 2. Build and run with Docker Compose

Identical on all three platforms — Docker abstracts away the OS:

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

---

### Running without Docker (local development)

Requires **Python 3.11+** installed natively ([python.org](https://www.python.org/downloads/) on Windows/macOS, or your Linux distro's package manager). Virtual-environment activation syntax differs by shell, so follow the block for your platform.

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
streamlit run app.py
```

**macOS / Linux (bash/zsh):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

In every case, the app is served at `http://localhost:8501`. Deactivate the virtual environment when finished with `deactivate` (all platforms).

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
├── tests/
│   └── test_rules.py           # unittest suite for the rule engine
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
