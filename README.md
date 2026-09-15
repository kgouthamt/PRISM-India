# PRISM-India
### Cost-Conscious Clinical + PGx Decision Support
**Team ID:** DENDRITE-PE-XD-018

---

## 1. Executive Summary

PRISM-India is **not** a post-test genotype lookup dictionary — a tool that sits idle until a genetic test result arrives and only then tells you what to do with it. That framing accepts an expensive assumption: that the test was worth ordering in the first place. Pharmacogenomic panels are not free, not instant, and not always necessary — in a resource-constrained health system, ordering one for every patient on every drug is neither clinically nor economically defensible.

**PRISM-India is a Cost-Conscious Pre-Test Triage Engine.** Before a clinician orders a genetic test, PRISM first analyzes the routine clinical data already on hand — labs, current medications — to determine whether a PGx result is actually likely to change how this patient is managed. Only when that analysis says testing is worthwhile does the system's second role, genotype/phenotype-to-dosing recommendation, become relevant. The pivot is deliberate: **triage comes first, interpretation comes second.**

This reframes the product from "what does this genotype mean?" to "should we even be asking for a genotype?" — the question a cost-conscious health system actually needs answered before it spends on a molecular diagnostics panel.

### The Workflow: Baseline → Routing → Triage/Evaluation

The dashboard follows this exact sequence on one screen, top to bottom:

1. **Patient Baseline** — Patient ID, Age, Weight, the drug being requested, and any current medications, collected once at the top before anything else.
2. **Routing** — a single question, **"Diagnostic Data Available:"**, with three answers: *Genotype Data*, *Phenotype / TDM Data*, or *None of the above (Run Triage)*.
3. **Path A — Genotype/Phenotype Evaluation.** If a PGx result already exists, the dashboard goes straight to interpreting it: the exact test result, an Evaluate button, and the full risk/dosage/audit/FHIR flow (`engine/rules.py`).
4. **Path B — Numerical Pre-Test Triage.** If no PGx result exists yet, the dashboard instead collects exact numeric labs (eGFR, ALT/AST, Platelets, PT/INR — each with a "Test Not Done / Unknown" checkbox) and runs the 3-Tier Triage Engine below to decide whether ordering a test is even worthwhile.

Both paths end in the same **🔍 Web Search: Similar Clinical Cases (Prototype)** panel — a UI mockup, clearly labeled and non-functional, previewing a planned literature-search feature (see "Similar Cases Mockup" below).

---

## 2. The 3-Tier Decision Pipeline

The Pre-Test Triage Engine (`engine/triage.py`) is a multi-layer assessment, not a single lookup. It combines two independent evidence tiers into one recommendation:

### Tier 1 — Clinical Engine (`engine/clinical.py`)
Assesses only **objective, exact numeric data the clinician already has — never subjective patient-reported history.** There is no "previous adverse drug reaction" or "previous treatment failure" input anywhere in this pipeline: those are real clinical signals, but they aren't the kind of routine, verifiable data this tier is scoped to reason about. The inputs are exactly:

| Parameter | Widget | Unit | Threshold |
|-----------|--------|------|-----------|
| `age` | Number input | Years | — |
| `weight` | Number input | kg | — |
| `egfr` | Number input + "Test Not Done / Unknown" checkbox | mL/min/1.73m² | < 60 flags renal risk (KDIGO 2024) |
| `alt_ast` | Number input + "Test Not Done / Unknown" checkbox | U/L | > 40 flags hepatic risk (NFI) |
| `platelets` | Number input + "Test Not Done / Unknown" checkbox | x10³/µL | < 150 flags bleeding risk |
| `pt_inr` | Number input + "Test Not Done / Unknown" checkbox | ratio | > 1.2 flags bleeding risk |

Checking a lab's "Test Not Done / Unknown" box passes `None` for that parameter rather than whatever value is left in the (now disabled) number field — a skipped test is never silently treated as a normal result.

- **`assess_renal_function(egfr)`** — an exact eGFR below the KDIGO 2024 threshold (60 mL/min/1.73m²) flags nephrotoxicity risk; `egfr=None` never does.
- **`assess_hepatic_function(alt_ast)`** — an exact ALT/AST above the standard upper limit of normal (40 U/L) flags hepatic-impairment risk for empirical dose-caution framing per **CDSCO's National Formulary of India**; `alt_ast=None` never does.
- **`assess_bleeding_risk_labs(platelets, pt_inr)`** — flags elevated baseline bleeding risk before starting an anticoagulant: platelets below 150 x10³/µL or PT/INR above 1.2 raises risk; either value being `None` never does on its own.
- **`assess_age_weight_context(age, weight)`** — flags pediatric-age or low-body-weight dosing considerations per **FDA guidance on pediatric and weight-based dosing**, surfaced for every drug regardless of which triage path it takes.

### Tier 2 — DDI Engine (`engine/ddi.py`)
`check_drug_interactions(drug, concurrent_medications)` checks the patient's current medication list — entered as a comma-separated **Current Medications** field in the Patient Baseline section — against a curated table of clinically significant drug-drug interactions for each modeled drug, returning severity, mechanism, and an actionable recommendation for every match.

### Tier 3 — PGx Actionability Triage (`engine/triage.py`)
`triage_pgx_actionability(drug, concurrent_medications, age=, weight=, egfr=, alt_ast=, platelets=, pt_inr=)` combines Tier 1 and Tier 2 findings — and *only* those — into one of three states:

| State | Meaning |
|-------|---------|
| 🔴 **HIGH PRIORITY** | Testing strongly indicated — genotype is expected to materially change drug selection or dosing. |
| 🟡 **CONSIDER** | Genetic information may influence treatment, but is not clearly essential — routine monitoring may already be sufficient. |
| 🟢 **LOW PRIORITY** | Testing is unlikely to change management (including drugs outside this MVP's triage scope, which are reported as low priority with an explicit "not modeled" rationale rather than a fabricated assessment). |

This triage runs on the **Clinical Assessment** tab whenever "None of the above (Run Triage)" is selected, entirely independent of `engine/rules.py` (the downstream genotype/phenotype → dosing engine, used on the same tab when Genotype or Phenotype data is selected instead): triage answers *"should we test?"*, `evaluate_prescription()` answers *"given the result, what do we do?"*

The result dict separates two kinds of output: `rationale` explains *why* the triage level was chosen, while a distinct `warnings` list carries strong, lab-driven safety alerts that stand independently of the triage color itself — e.g. Tacrolimus's mandatory-TDM warning on an abnormal RFT/LFT, rendered in the dashboard as its own red alert block beneath the rationale bullets.

---

## 3. Evidence-Based Clinical Anchors

Every threshold and recommendation in the pipeline is traceable to a named, published source — nothing is inferred or fabricated:

| Guideline | Used for |
|-----------|----------|
| **KDIGO 2024** | Renal function (eGFR) staging and nephrotoxicity risk classification. |
| **CDSCO / National Formulary of India (NFI)** | Hepatic impairment framing and empirical dosing caution when genetic data alone doesn't govern the decision. |
| **FDA Guidance** | Severe drug-drug interaction (DDI) identification (e.g. boxed warnings, drug-label interaction sections). |
| **CPIC & FDA Pharmacogenomics** | The final genotype/phenotype-to-prescribing therapeutic recommendations once a PGx test has actually been ordered and resulted. |

This is the same "guideline lock" philosophy the rule engine has followed throughout this project: deterministic, source-cited logic instead of a model that could quietly drift from the evidence it's supposed to represent.

---

## 4. High-Value Drug Workflows (MVP Scope)

The triage layer's MVP scope is three drugs, chosen specifically because each demonstrates a *different* facet of the engine's nuance rather than repeating the same pattern three times:

### Clopidogrel (CYP2C19) — the HIGH PRIORITY + DDI case
Always triages 🔴 **HIGH PRIORITY**: an FDA boxed warning and CPIC guidance both treat CYP2C19 poor/intermediate metabolizer status as directly actionable for antiplatelet selection. The DDI Engine layers on top of that: prescribing clopidogrel alongside a strong CYP2C19 inhibitor such as **omeprazole** independently reduces clopidogrel activation, compounding — not replacing — the genetic risk. Downstream, `evaluate_prescription()` maps the resulting CYP2C19 genotype (normal / intermediate / poor) to a specific antiplatelet recommendation (see prior sections of this codebase's history for the exact dosing table).

### Tacrolimus (CYP3A5) — the nephrotoxicity + hepatic case
Also always triages 🔴 **HIGH PRIORITY** (narrow therapeutic index, ~1.5–2x starting-dose difference between CYP3A5 expresser/non-expresser genotypes per CPIC) — but an **eGFR below 60** or an **ALT/AST above 40** independently produces a **strong clinical warning**, distinct from the triage color itself and naming the exact value and threshold crossed: PGx sets the starting-dose *baseline*, but an abnormal lab makes lab-driven therapeutic drug monitoring (TDM) *mandatory* regardless of genotype (KDIGO 2024 for renal, NFI for hepatic). A clinician sees both signals side by side — the genetic starting-dose adjustment and the routine-lab safety mandate — rather than one in isolation.

### Warfarin (CYP2C9 & VKORC1) — the CONSIDER case
The only one of the three that does **not** default to HIGH PRIORITY. Routine PT/INR-guided dose titration is often sufficient for warfarin management without upfront genetic testing, so the baseline triage state is 🟡 **CONSIDER**. It escalates to 🔴 **HIGH PRIORITY** only if **one of three objective conditions holds**: PT/INR is **above 1.2** (elevated baseline bleeding risk before dosing even starts), Platelets are **below 150 x10³/µL** (compounding hematologic risk), or the DDI Engine detects a severe interaction — **amiodarone** (CYP2C9/3A4 inhibition, raises INR) or an **NSAID** (additive bleeding risk), both modeled as hard, FDA-labeled severe interactions. A lab marked **"Test Not Done / Unknown"** never escalates on its own — only a value that actually crosses the threshold, or a confirmed DDI, does. Downstream, `evaluate_prescription()` combines a CYP2C9 diplotype and a VKORC1 genotype into a single sensitivity category (normal / increased / highly increased) — a simplified categorical form of CPIC's warfarin dosing framework, not the full multi-covariate pharmacogenetic equation.

**Scope note:** the five other drugs this prototype models (Carbamazepine, Allopurinol, Abacavir, Primaquine, Rasburicase) retain their existing direct genotype/phenotype-to-dosing rules in `engine/rules.py`, but do not yet have a Tier 1/Tier 2 pre-test triage model — requesting triage for them correctly returns 🟢 LOW PRIORITY with an explicit "not modeled in current MVP scope" rationale, rather than a guess.

### Similar Cases Mockup

Both Path A (Genotype/Phenotype Evaluation) and Path B (Pre-Test Triage) end in a **"🔍 Web Search: Similar Clinical Cases (Prototype)"** expander. This is a **UI mockup only** — it performs no web request, no literature search, and no scraping of any kind. It exists to communicate a planned feature (surfacing comparable published cases by age, drug, and lab profile) without pretending it's already built; the panel is explicitly labeled **"Mockup / Coming Soon"** so a judge or clinician never mistakes the placeholder text for a real result.

---

## 5. Execution Guide

PRISM-India is fully containerized and runs identically on **Windows**, **macOS**, and **Linux**. The recommended path is Docker Compose; a native (non-Docker) path is also provided for local development.

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

`tests/` is a `unittest` suite of **72 tests** covering every tier: `test_clinical.py` (renal/hepatic/bleeding-risk/age-weight assessment from exact numeric labs, including every threshold boundary), `test_ddi.py` (drug-drug interaction matching), `test_triage.py` (all three triage states across Clopidogrel, Tacrolimus, and Warfarin — including the lab-driven "mandatory TDM" warnings, the requirement that only a value actually crossing a threshold or a confirmed DDI ever escalates, and that every parameter being `None` never raises a `TypeError`), and `test_rules.py` (the downstream genotype/phenotype dosing engine, including Warfarin's combined CYP2C9 + VKORC1 categorization).

Run the full suite from the project root:

```bash
python -m unittest discover -s tests -t . -v
```

This exits `0` with `OK` when the suite passes, using only the Python standard library.

---

## Project Structure

```
PRISM-India/
├── app.py                     # Streamlit dashboard: Patient Baseline -> Routing -> Triage/Evaluation + Audit
├── engine/
│   ├── clinical.py             # Tier 1: routine lab assessment (KDIGO renal, NFI hepatic, bleeding risk)
│   ├── ddi.py                  # Tier 2: drug-drug interaction checker (FDA-anchored)
│   ├── triage.py                # Tier 3: PGx Actionability Triage orchestrator
│   └── rules.py                 # Downstream genotype/phenotype -> dosing engine: evaluate_prescription()
├── storage/
│   └── audit_logger.py         # SQLite audit trail: log_decision(), get_all_logs()
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
