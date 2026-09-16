# PRISM-AIIMS
### 3-Layer Clinical + PGx Decision Support
**Team ID:** DENDRITE-PE-XD-018

---

## 1. Executive Summary

PRISM-AIIMS is **not** a post-test genotype lookup dictionary — a tool that sits idle until a genetic test result arrives and only then tells you what to do with it. That framing accepts an expensive assumption: that the test was worth ordering in the first place, and that baseline patient risk was already accounted for. Pharmacogenomic panels are not free, not instant, and not always necessary — in a resource-constrained health system, ordering one for every patient on every drug is neither clinically nor economically defensible.

**PRISM-AIIMS is a 3-Layer Clinical + PGx Decision Support engine.** Every encounter flows through three sequential, increasingly specific layers on one screen, top to bottom:

1. **Layer 1 — Patient Details & Vitals.** Objective demographic, anthropometric, and vital-sign data collected first, before any risk scoring happens.
2. **Layer 2 — ADR Risk Prediction.** Two published/institutional Adverse Drug Reaction (ADR) risk models run against that patient's baseline predictors, producing a single verdict: **Standard** or **High Baseline ADR Risk**.
3. **Layer 3 — PGx Triage.** The pre-test triage engine (previously "Pre-Test Triage," 🔴/🟡/🟢) decides whether a pharmacogenomic test is actually likely to change management for the requested drug — now *amplified* by the Layer 2 verdict, not just by labs and drug-drug interactions.

The pivot is deliberate: **baseline risk comes first, drug-specific triage comes second, genotype interpretation comes third.** Only once Layer 3 says testing is worthwhile does the system's fourth role — genotype/phenotype-to-dosing recommendation (`engine/rules.py`) — become relevant.

### The Workflow: Layer 1 → Layer 2 → Layer 3 → Evaluation

The dashboard follows this exact sequence on one screen, top to bottom:

1. **Patient ID**, then **Layer 1: Patient Details & Vitals** — Demographics (Name, Age, Address), Anthropometrics (Height, Weight), and Vitals (Pulse Rate, Blood Pressure, Respiratory Rate, SpO2, Temperature), collected in an expander before anything else.
2. **Layer 2: ADR Risk Prediction** — checkboxes and numeric inputs for Model A and GerontoNet (Model B), evaluated reactively via `calculate_adr_risk()` the moment they're filled in, surfacing a single "Standard" or "High Baseline ADR Risk" verdict.
3. **Layer 3: PGx Triage** — the drug being requested and any current medications, followed by a routing question, **"Diagnostic Data Available:"**, with three answers: *Genotype Data*, *Phenotype / TDM Data*, or *None of the above (Run Triage)*.
   - **Path A — Genotype/Phenotype Evaluation.** If a PGx result already exists, the dashboard goes straight to interpreting it: the exact test result, an Evaluate button, and the full risk/dosage/audit/FHIR flow (`engine/rules.py`).
   - **Path B — Numerical Pre-Test Triage.** If no PGx result exists yet, the dashboard instead collects exact numeric labs (eGFR, ALT/AST, Platelets, PT/INR — each with a "Test Not Done / Unknown" checkbox) and runs `triage_pgx_actionability()`, now also fed the Layer 2 ADR risk verdict, to decide whether ordering a test is even worthwhile.

Both paths end in the same **🔍 Web Search: Similar Clinical Cases (Prototype)** panel — a UI mockup, clearly labeled and non-functional, previewing a planned literature-search feature (see "Similar Cases Mockup" below).

---

## 2. Layer 1 — Patient Details & Vitals

Purely objective intake data, collected in the `st.expander("LAYER 1: Patient Details & Vitals")` before any scoring runs:

| Group | Fields |
|-------|--------|
| Demographics | Patient Name, Age, Address |
| Anthropometrics | Height (cm), Weight (kg) |
| Vitals | Pulse Rate (PR), Blood Pressure (systolic/diastolic), Respiratory Rate (RR), SpO2, Temperature |

Age and Weight feed forward into Layer 3's `assess_age_weight_context()` (pediatric/low-body-weight dosing flags, FDA-anchored) and, for Warfarin specifically, Age feeds the Layer 2 amplification rule described below. The remaining vitals are collected for the clinical record but are not yet consumed by the rule engine — a v5.0.0 scope decision that keeps this MVP's logic traceable to the exact inputs it reasons about, rather than implying a vitals-driven risk model that doesn't exist yet.

---

## 3. Layer 2 — ADR Risk Prediction

`calculate_adr_risk()` (`engine/clinical.py`) evaluates two independent, published/institutional ADR risk predictor sets — entirely before any drug or genotype is considered — and reduces them to a single boolean/string verdict that the rest of the pipeline consumes.

### Model A — institutional 9-predictor model (6 implemented)

| Predictor | Type |
|-----------|------|
| Chronic lung disease | checkbox |
| Presenting with bleeding/GI disorder | checkbox |
| Syncope on admission | checkbox |
| On antithrombotics | checkbox |
| On diuretics | checkbox |
| On RAAS drugs | checkbox |

The remaining 3 of Model A's 9 predictors are out of this MVP's scope and are not represented in the UI or logic — there is no placeholder standing in for them.

### Model B — GerontoNet ADR Risk Score (6 predictors)

Published clinical score: Onder G, et al. *"Development and validation of a score to assess risk of adverse drug reactions among in-hospital patients 65 years or older: the GerontoNet ADR risk score."* Arch Intern Med. 2010.

| Predictor | Type |
|-----------|------|
| Number of concurrent drugs | numeric input |
| History of ADR ⭐ (strongest single predictor) | checkbox |
| Heart failure | checkbox |
| Liver disease | checkbox |
| \>4 medical conditions | checkbox |
| Renal failure | checkbox |

### Trigger logic

`calculate_adr_risk()` returns **`ADR_RISK_HIGH` ("HIGH BASELINE ADR RISK")** if **any** of the following hold, otherwise **`ADR_RISK_STANDARD`**:

- `history_of_adr` is `True` (the strongest single predictor, on its own), **or**
- `num_concurrent_drugs > 4` (polypharmacy; exactly 4 does **not** trigger — the threshold is strictly "more than 4"), **or**
- **2 or more** Model A predictors are present, **or**
- **2 or more** of the other GerontoNet predictors (heart failure, liver disease, >4 medical conditions, renal failure) are present.

The result dict — `{"high_baseline_adr_risk", "adr_risk_flag", "model_a_trigger_count", "gerontonet_trigger_count", "reasons", "source"}` — is what actually crosses into Layer 3 and the audit log. Layer 3 never receives the raw predictor checkboxes (no "history of ADR" or "heart failure" reaches `engine/triage.py` directly); it only receives this single computed verdict, exactly like a lab result crosses in as `"HIGH"/"LOW"/"UNKNOWN"` rather than the raw lab value plus its interpretation logic.

---

## 4. Layer 3 — PGx Triage

The engine formerly documented as the "Pre-Test Triage Engine" (🔴/🟡/🟢) is unchanged in its core lab/DDI logic, but is now explicitly framed as **Layer 3**, and its Warfarin path is *amplified* by the Layer 2 verdict.

### Tier breakdown (unchanged internals)

- **Clinical assessment (`engine/clinical.py`)** — objective, exact numeric data: `age`, `weight`, `egfr` (KDIGO 2024, < 60 flags renal risk), `alt_ast` (CDSCO/NFI, > 40 flags hepatic risk), `platelets` (< 150 flags bleeding risk), `pt_inr` (> 1.2 flags bleeding risk). Any lab marked "Test Not Done / Unknown" passes `None` and never raises a flag.
- **DDI Engine (`engine/ddi.py`)** — `check_drug_interactions(drug, concurrent_medications)` checks the patient's current medication list against a curated table of clinically significant drug-drug interactions.
- **PGx Actionability Triage (`engine/triage.py`)** — `triage_pgx_actionability(drug, concurrent_medications, age=, weight=, egfr=, alt_ast=, platelets=, pt_inr=, high_baseline_adr_risk=)` combines all of the above into one of three states:

| State | Meaning |
|-------|---------|
| 🔴 **HIGH PRIORITY** | Testing strongly indicated — genotype is expected to materially change drug selection or dosing. |
| 🟡 **CONSIDER** | Genetic information may influence treatment, but is not clearly essential — routine monitoring may already be sufficient. |
| 🟢 **LOW PRIORITY** | Testing is unlikely to change management (including drugs outside this MVP's triage scope, reported as low priority with an explicit "not modeled" rationale rather than a fabricated assessment). |

This triage runs whenever "None of the above (Run Triage)" is selected, entirely independent of `engine/rules.py` (the downstream genotype/phenotype → dosing engine, used instead when Genotype or Phenotype data is selected): Layer 3 answers *"should we test?"*, `evaluate_prescription()` answers *"given the result, what do we do?"*

### Layer 2 as an amplifying factor

**Warfarin** is the drug where the Layer 2 verdict can change the triage outcome outright. `_warfarin_triage()` computes `is_elderly = age >= ELDERLY_AGE_THRESHOLD (65)` and escalates straight to 🔴 **HIGH PRIORITY** whenever `high_baseline_adr_risk AND is_elderly` — on top of the existing lab/DDI escalation conditions (PT/INR > 1.2, platelets < 150, or a severe DDI such as amiodarone/an NSAID). This mirrors GerontoNet's own target population (in-hospital patients ≥ 65): an elderly patient already flagged as high ADR risk is the population where genotype-guided starting-dose selection is most valuable, so the triage escalates immediately regardless of labs. A missing `age` never escalates (it's treated as "not confirmed elderly," not "assume elderly"), and a high ADR-risk flag on a non-elderly patient is surfaced only as an explanatory rationale line, not an escalation.

**Clopidogrel and Tacrolimus** are already always 🔴 HIGH PRIORITY (CYP2C19/CYP3A5 status is directly actionable regardless of routine labs), so there's no higher triage state to escalate to. For these two, a "High Baseline ADR Risk" verdict instead appends an extra rationale line noting that the case warrants additional vigilance when monitoring for adverse effects — the amplifying factor is preserved as clinical signal even at the triage ceiling.

The result dict separates two kinds of output: `rationale` explains *why* the triage level was chosen, while a distinct `warnings` list carries strong, safety-relevant alerts — e.g. Tacrolimus's mandatory-TDM warning on an abnormal eGFR/ALT-AST, or Warfarin's elderly + high-ADR-risk escalation warning — rendered in the dashboard as their own alert block beneath the rationale bullets.

---

## 5. Evidence-Based Clinical Anchors

Every threshold and recommendation in the pipeline is traceable to a named, published source — nothing is inferred or fabricated:

| Guideline / Model | Used for |
|-----------|----------|
| **KDIGO 2024** | Renal function (eGFR) staging and nephrotoxicity risk classification. |
| **CDSCO / National Formulary of India (NFI)** | Hepatic impairment framing and empirical dosing caution when genetic data alone doesn't govern the decision. |
| **FDA Guidance** | Severe drug-drug interaction (DDI) identification, and pediatric/weight-based dosing context. |
| **ADR Risk Predictor Model A** (institutional, 9-predictor, 6 implemented) | Layer 2 baseline ADR risk scoring. |
| **GerontoNet ADR Risk Score** (Onder et al., *Arch Intern Med* 2010) | Layer 2 baseline ADR risk scoring, and the Warfarin elderly-amplification rule in Layer 3. |
| **CPIC & FDA Pharmacogenomics** | The final genotype/phenotype-to-prescribing therapeutic recommendations once a PGx test has actually been ordered and resulted. |

This is the same "guideline lock" philosophy the rule engine has followed throughout this project: deterministic, source-cited logic instead of a model that could quietly drift from the evidence it's supposed to represent.

---

## 6. High-Value Drug Workflows (MVP Scope)

The triage layer's MVP scope is three drugs, chosen specifically because each demonstrates a *different* facet of the engine's nuance rather than repeating the same pattern three times:

### Clopidogrel (CYP2C19) — the HIGH PRIORITY + DDI case
Always triages 🔴 **HIGH PRIORITY**: an FDA boxed warning and CPIC guidance both treat CYP2C19 poor/intermediate metabolizer status as directly actionable for antiplatelet selection. The DDI Engine layers on top of that: prescribing clopidogrel alongside a strong CYP2C19 inhibitor such as **omeprazole** independently reduces clopidogrel activation, compounding — not replacing — the genetic risk. A Layer 2 "High Baseline ADR Risk" verdict adds a rationale note rather than changing the triage color, since it's already at the ceiling. Downstream, `evaluate_prescription()` maps the resulting CYP2C19 genotype (normal / intermediate / poor) to a specific antiplatelet recommendation.

### Tacrolimus (CYP3A5) — the nephrotoxicity + hepatic case
Also always triages 🔴 **HIGH PRIORITY** (narrow therapeutic index, ~1.5–2x starting-dose difference between CYP3A5 expresser/non-expresser genotypes per CPIC) — but an **eGFR below 60** or an **ALT/AST above 40** independently produces a **strong clinical warning**, distinct from the triage color itself and naming the exact value and threshold crossed: PGx sets the starting-dose *baseline*, but an abnormal lab makes lab-driven therapeutic drug monitoring (TDM) *mandatory* regardless of genotype (KDIGO 2024 for renal, NFI for hepatic). A Layer 2 "High Baseline ADR Risk" verdict adds the same rationale note as Clopidogrel.

### Warfarin (CYP2C9 & VKORC1) — the CONSIDER case, with elderly + ADR-risk amplification
The only one of the three that does **not** default to HIGH PRIORITY. Routine PT/INR-guided dose titration is often sufficient for warfarin management without upfront genetic testing, so the baseline triage state is 🟡 **CONSIDER**. It escalates to 🔴 **HIGH PRIORITY** if **any** of the following hold: PT/INR is **above 1.2**, Platelets are **below 150 x10³/µL**, the DDI Engine detects a severe interaction (**amiodarone** or an **NSAID**), **or** — as of Layer 2 — the patient is **elderly (age ≥ 65) and carries a "High Baseline ADR Risk" verdict**, independent of labs or DDIs. A lab marked **"Test Not Done / Unknown"** never escalates on its own — only a value that actually crosses a threshold, a confirmed DDI, or the elderly + high-ADR-risk combination does. Downstream, `evaluate_prescription()` combines a CYP2C9 diplotype and a VKORC1 genotype into a single sensitivity category (normal / increased / highly increased) — a simplified categorical form of CPIC's warfarin dosing framework, not the full multi-covariate pharmacogenetic equation.

**Scope note:** the five other drugs this prototype models (Carbamazepine, Allopurinol, Abacavir, Primaquine, Rasburicase) retain their existing direct genotype/phenotype-to-dosing rules in `engine/rules.py`, but do not yet have a Layer 3 pre-test triage model — requesting triage for them correctly returns 🟢 LOW PRIORITY with an explicit "not modeled in current MVP scope" rationale, rather than a guess.

### Similar Cases Mockup

Both Path A (Genotype/Phenotype Evaluation) and Path B (Pre-Test Triage) end in a **"🔍 Web Search: Similar Clinical Cases (Prototype)"** expander. This is a **UI mockup only** — it performs no web request, no literature search, and no scraping of any kind. It exists to communicate a planned feature (surfacing comparable published cases by age, drug, lab profile, and Layer 2 ADR risk flag) without pretending it's already built; the panel is explicitly labeled **"Mockup / Coming Soon"** so a judge or clinician never mistakes the placeholder text for a real result.

---

## 7. Audit Trail

`storage/audit_logger.py` persists every clinician decision to SQLite (`decisions.db`), including the Layer 2 verdict alongside the existing clinical-encounter metadata and provenance fields:

- `adr_risk_flag` — the exact `ADR_RISK_HIGH` / `ADR_RISK_STANDARD` string computed by `calculate_adr_risk()` for that encounter.

Schema changes are strictly **additive**: `_get_connection()` never drops or rebuilds the `decisions` table. A database created under an older, narrower schema (e.g. one predating Layer 2) is brought up to date via `ALTER TABLE ADD COLUMN` for whatever columns it's missing, which preserves every existing row — there is no automatic destruction of audit data.

---

## 8. Execution Guide

PRISM-AIIMS is fully containerized and runs identically on **Windows**, **macOS**, and **Linux**. The recommended path is Docker Compose; a native (non-Docker) path is also provided for local development.

### Prerequisites

| OS | Install |
|----|---------|
| **Windows 10/11** | [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) with the WSL2 backend enabled. Run all commands below from **PowerShell**, **Command Prompt**, or a **WSL2** terminal. |
| **macOS** (Intel or Apple Silicon) | [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/). Run all commands below from **Terminal**. |
| **Linux** | Docker Engine + the Compose plugin, e.g. on Ubuntu/Debian: `sudo apt-get update && sudo apt-get install docker.io docker-compose-plugin`. Add your user to the `docker` group (`sudo usermod -aG docker $USER`, then log out/in) to avoid needing `sudo` on every command. |

### Run with Docker Compose

```bash
git clone https://github.com/kgouthamt/PRISM-India.git
cd PRISM-India
docker compose up --build
```

This builds the image from the `python:3.11-slim` base, installs dependencies, and starts the Streamlit server on port `8501`. The `storage/` directory is mounted as a volume, so the audit log (`decisions.db`) **persists across container restarts**. Open the dashboard at:

```
http://localhost:8501
```

Stop the application with:

```bash
docker compose down
```

### Running without Docker (local development)

Requires **Python 3.11+**. Virtual-environment activation syntax differs by shell:

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

## Automated Testing

`tests/` is a `unittest` suite of **90 tests** covering every layer: `test_clinical.py` (renal/hepatic/bleeding-risk/age-weight assessment from exact numeric labs including every threshold boundary, plus `TestCalculateAdrRisk` covering Layer 2's Model A and GerontoNet trigger logic), `test_ddi.py` (drug-drug interaction matching), `test_triage.py` (all three triage states across Clopidogrel, Tacrolimus, and Warfarin — including the lab-driven "mandatory TDM" warnings, the Layer 2 elderly + high-ADR-risk Warfarin amplification rule, the Clopidogrel/Tacrolimus rationale-only surfacing, and the requirement that every parameter being `None` never raises a `TypeError`), and `test_rules.py` (the downstream genotype/phenotype dosing engine, including Warfarin's combined CYP2C9 + VKORC1 categorization).

Run the full suite from the project root:

```bash
python -m unittest discover -s tests -t . -v
```

This exits `0` with `OK` when the suite passes, using only the Python standard library.

---

## Project Structure

```
PRISM-India/
├── app.py                     # Streamlit dashboard: Layer 1 -> Layer 2 -> Layer 3 -> Evaluation + Audit
├── engine/
│   ├── clinical.py             # Layer 1 labs (KDIGO renal, NFI hepatic, bleeding risk) + Layer 2 calculate_adr_risk()
│   ├── ddi.py                  # Drug-drug interaction checker (FDA-anchored), used within Layer 3
│   ├── triage.py                # Layer 3: PGx Actionability Triage orchestrator, amplified by the Layer 2 verdict
│   └── rules.py                 # Downstream genotype/phenotype -> dosing engine: evaluate_prescription()
├── storage/
│   └── audit_logger.py         # SQLite audit trail: log_decision(), get_all_logs() -- includes adr_risk_flag
├── abdm/
│   └── fhir_builder.py         # FHIR R4 Bundle generator: generate_fhir_bundle()
├── tests/
│   ├── test_clinical.py
│   ├── test_ddi.py
│   ├── test_triage.py
│   └── test_rules.py
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
