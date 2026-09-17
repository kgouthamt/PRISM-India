# PRISM-AIIMS
### Cost-Conscious Pre-Test Triage Engine and Clinical Decision Support System
**Team ID:** DENDRITE-PE-XD-018

---

## 1. Executive Summary

PRISM-AIIMS is not a post-test genotype lookup dictionary — a tool that sits idle until a genetic test result arrives and only then tells you what to do with it. That framing accepts an expensive assumption: that the test was worth ordering in the first place, and that baseline patient risk was already accounted for. Pharmacogenomic panels are not free, not instant, and not always necessary — in a resource-constrained health system, ordering one for every patient on every drug is neither clinically nor economically defensible.

PRISM-AIIMS is a **Cost-Conscious Pre-Test Triage Engine and Clinical Decision Support System**. Every encounter flows through three sequential stages, each narrowing the question further:

1. **Patient Baseline & Vitals** — captures objective physiological data (demographics, anthropometrics, vitals, and later, exact numeric labs such as eGFR and INR) anchored to published clinical guidelines (KDIGO, NFI).
2. **Clinical Risk Assessment** — evaluates systemic patient vulnerability using the ADATIP 9-Predictor Model (acute presentation) and the **actual, validated GerontoNet ADR Risk Score** (chronic fragility and polypharmacy), producing a single verdict: Standard or High Baseline ADR Risk.
3. **Pharmacogenomic (PGx) Triage** — an **integrated decision matrix**, not a linear escalation chain: it resolves `Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)` by combining three independent inputs — CPIC-anchored clinical actionability for the drug being requested, a mock GenomeIndia population-frequency prior for context, and this patient's own labs, drug-drug interactions, and Clinical Risk Assessment verdict — into a deterministic state: HIGH PRIORITY, CONSIDER, or LOW PRIORITY.

The pivot is deliberate: **baseline risk comes first, drug-specific triage comes second, genotype interpretation comes third.** Only once PGx Triage says testing is worthwhile does the system's fourth role — genotype/phenotype-to-dosing recommendation (`engine/rules.py`) — become relevant.

### This revision: an integrated decision matrix, not a linear escalation chain

A prior revision of the PGx Triage layer let a general baseline-vulnerability signal (Layer 2's ADR risk flag) independently force a drug's testing priority to HIGH — a linear-escalation model later identified as scientifically unsound: general vulnerability and a *specific* drug's validated PGx relationship are statistically independent variables, and conflating them overstates the case for testing drugs (Warfarin, specifically) where routine non-genetic monitoring already performs comparably well. This revision replaces that model with an integrated decision matrix:

- **Testing Priority is now `f(PGx Actionability, Patient-Specific Clinical Context)`**, resolved via an explicit state machine (`engine/triage.py`), not an additive escalation score. See Section 4.
- **Baseline ADR risk (Layer 2) is now modeled as an orthogonal covariate.** It never independently transitions a drug's priority state for any drug — only a *pathway-intersecting* clinical context (a severe drug-drug interaction, or an extreme lab value tied to the drug's own mechanism) can do that. A high baseline ADR risk still surfaces as a strong clinical warning; it just no longer overrides the state itself. See Section 4.
- **A mock, population-aware PGx context (GenomeIndia Prototype) has been added to the dashboard**, illustrating how a population allele-frequency prior would contextualize an individual's prior probability of an actionable variant, with an explicit safeguard disclaimer that it never determines an individual genotype. See Section 5.

An earlier revision of this prototype had also accumulated several clinical oversimplifications flagged by medical reviewers, which remain corrected in this revision:

- **Lab abnormalities no longer masquerade as diagnoses.** A reduced eGFR is no longer reported as "universally high nephrotoxicity risk"; an elevated ALT/AST is no longer reported as "hepatic impairment"; abnormal platelets/PT-INR are no longer reported as "universally high bleeding risk." Each is now reported as exactly what it is — a lab abnormality requiring clinical correlation — never an automatic diagnosis. See Section 2.
- **The GerontoNet ADR Risk Score is now the actual, published, weighted score** (0-10 points, High Risk only at 4+), not a derived "2-or-more-predictors" binary heuristic. See Section 3.
- **Tacrolimus TDM targets are now indication-aware** (Kidney vs. Liver Transplant), and **G6PD phenotype interpretation is now reference-range aware** (the ordering lab's own lower limit of normal, not a single universal cutoff). See Section 5.
- **The DDI database is explicitly labeled as a curated MVP subset**, not a comprehensive interaction checker.
- **There is no single blanket "CPIC" label** describing every rule in the engine. Each individual rule now carries its own `guideline_url`, `evidence_date`, and a short `rule_hash` fingerprint, surfaced on every evaluation. See Section 6.

### The Workflow

The dashboard follows this exact sequence on one screen, top to bottom:

1. **Patient ID**, then **Patient Baseline & Vitals** — Demographics (Name, Age, Address), Anthropometrics (Height, Weight), and Vitals (Pulse Rate, Blood Pressure, Respiratory Rate, SpO2, Temperature), collected before anything else.
2. **Clinical Risk Assessment** — checkboxes and numeric inputs for the ADATIP 9-Predictor Model, the actual GerontoNet Risk Score, and a General Clinical History section, evaluated reactively the moment they're filled in, surfacing the exact numerical GerontoNet score, its risk category, and a single overall "Standard" or "High Baseline ADR Risk" verdict.
3. **Pharmacogenomic (PGx) Triage** — the drug being requested and any current medications (with a disclaimer that the DDI database is a curated MVP subset), followed by a routing question, "Diagnostic Data Available:", with three answers: Genotype Data, Phenotype / TDM Data, or None of the above (Run Triage).
   - **Path A — Genotype/Phenotype Evaluation.** If a PGx result already exists, the dashboard goes straight to interpreting it: the exact test result, drug-specific clinical-context inputs (Tacrolimus's transplant indication; G6PD's local lab reference range), an Evaluate action, and the full risk/dosage/audit/FHIR flow (`engine/rules.py`) — including that specific rule's own provenance.
   - **Path B — Numerical Pre-Test Triage.** If no PGx result exists yet, the dashboard instead collects exact numeric labs (eGFR, ALT/AST, Platelets, PT/INR — each with a "Test Not Done / Unknown" checkbox) and runs `triage_pgx_actionability()`, fed by the Clinical Risk Assessment's ADR risk verdict, to resolve the integrated decision matrix described in Section 4 — reporting PGx actionability and the baseline-ADR-risk contextual modifier as two separate sections, followed by the mock Population-Aware PGx Context (GenomeIndia Prototype) panel described in Section 5.

The sidebar carries a permanent "Live Clinical Literature & Similar Cases" panel — a UI prototype, clearly labeled and non-functional, previewing a planned literature-search feature (see "Similar Cases Preview" below).

---

## 2. Patient Baseline & Vitals

Objective intake data, collected before any risk scoring runs:

| Group | Fields |
|-------|--------|
| Demographics | Patient Name, Age, Address |
| Anthropometrics | Height (cm), Weight (kg) |
| Vitals | Pulse Rate, Blood Pressure (systolic/diastolic), Respiratory Rate, SpO2, Temperature |

Age and Weight feed forward into the Clinical Risk Assessment (the ADATIP age predictor, described below) and into `assess_age_weight_context()` (pediatric/low-body-weight dosing flags, FDA-anchored).

Later, in Path B of PGx Triage, this stage extends to exact numeric routine labs — eGFR, ALT/AST, Platelets, and PT/INR — each anchored to a named guideline. **Per clinical reviewer feedback, each of these is now reported strictly as a lab abnormality requiring clinical correlation, never as an automatic diagnosis:**

| Parameter | Unit | Threshold | Reported as |
|-----------|------|-----------|-------------|
| eGFR | mL/min/1.73m² | < 60 (KDIGO 2024) | "Reduced eGFR; requires clinical correlation for renal dose adjustment." |
| ALT/AST | U/L | > 40 (CDSCO / National Formulary of India) | "Elevated transaminases; laboratory abnormality." |
| Platelets | x10³/µL | < 150 | "Abnormal coagulation/CBC parameters." |
| PT/INR | ratio | > 1.2 | "Abnormal coagulation/CBC parameters." |

The functions that compute these (`assess_renal_function`, `assess_hepatic_function`, `assess_bleeding_risk_labs` in `engine/clinical.py`) return a `renal_function_status` (REDUCED/NORMAL/UNKNOWN), `transaminase_status` (ELEVATED/NORMAL/UNKNOWN), and `coagulation_cbc_status` (ABNORMAL/NORMAL/UNKNOWN) respectively — deliberately neutral status names, not risk-magnitude judgments like the old "nephrotoxicity risk" or "bleeding risk" labels. Checking a lab's "Test Not Done / Unknown" box passes `None` for that parameter rather than whatever value is left in the disabled input field — a skipped test is never silently treated as a normal result.

---

## 3. Clinical Risk Assessment

`calculate_adr_risk()` (`engine/clinical.py`) evaluates systemic patient vulnerability using two independent predictor sets, plus a clinician-reported general history, and reduces them to a single verdict that the rest of the pipeline consumes — Pharmacogenomic (PGx) Triage never receives the raw predictor checkboxes directly, only this computed flag.

### ADATIP 9-Predictor Model (acute presentation)

An institutional model capturing acute-presentation risk factors, all 9 predictors implemented. No published point-weighted formula was available for this model, so it uses a "2 or more predictors present" heuristic:

| Predictor | Type |
|-----------|------|
| Age (≥ 65 years) | derived from Patient Baseline & Vitals |
| Chronic lung disease | checkbox |
| Primary presenting complaints of respiratory disorders | checkbox |
| Primary presenting complaints of bleeding disorders | checkbox |
| Primary presenting complaints of GI disorders | checkbox |
| Syncope on hospital admission | checkbox |
| Antithrombotics | checkbox |
| Diuretics | checkbox |
| RAAS drugs | checkbox |

### GerontoNet ADR Risk Score — the actual validated score

Published clinical score: Onder G, et al. "Development and validation of a score to assess risk of adverse drug reactions among in-hospital patients 65 years or older: the GerontoNet ADR risk score." Arch Intern Med. 2010.

**This is no longer a derived binary heuristic.** `calculate_gerontonet_score()` computes the real weighted point total (0-10):

| Criterion | Points |
|-----------|--------|
| ≥ 4 comorbid conditions | +1 |
| Heart failure | +1 |
| Liver disease | +1 |
| Renal failure | +1 |
| 5-7 concurrent drugs | +1 |
| ≥ 8 concurrent drugs | +4 (supersedes the 5-7 band) |
| Previous history of ADR | +2 |

The result is classified **High Risk only if the total score is 4 or more** — otherwise Low Risk. This is a meaningful behavior change from the prior heuristic: a single strong predictor (e.g. Previous ADR history alone, worth 2 points) is **not**, on its own, enough to reach High Risk under the real score, even though it is still the single largest point contributor. The dashboard displays the exact numerical score and its risk category as its own metric, separate from the overall composite ADR verdict.

### General clinical history (clinician-reported)

A dedicated section capturing history that sits above either predictor model:

| Field | Effect |
|-------|--------|
| Previous ADR history | feeds the GerontoNet score above (+2 points); also the model's single largest point contributor |
| Allergy history | contributes to a 2-of-2 secondary heuristic with Family history (no published weighting exists for these) |
| Family history | contributes to the same 2-of-2 secondary heuristic |

### Composite trigger logic

`calculate_adr_risk()` returns **High Baseline ADR Risk** if **any** of the following hold, otherwise **Standard**:

- the GerontoNet ADR Risk Score is High Risk (total score ≥ 4 — see above), **or**
- **2 or more** ADATIP predictors are present, **or**
- **both** Allergy history and Family history are present.

The result dict — `{"high_baseline_adr_risk", "adr_risk_flag", "adatip_trigger_count", "gerontonet_score", "general_history_trigger_count", "reasons", "source"}` — is what actually crosses into PGx Triage and the audit log. `gerontonet_score` is itself a full sub-dict: `{"total_score", "max_score", "risk_category", "breakdown", "source"}`.

---

## 4. Pharmacogenomic (PGx) Triage

`triage_pgx_actionability()` (`engine/triage.py`) is an **integrated decision matrix**, not a linear escalation chain: given a drug, routine labs, drug-drug interactions, and the Clinical Risk Assessment's baseline ADR risk verdict, it resolves a single deterministic equation:

```
Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)
```

`PGx Actionability` is a categorical prior — anchored to CPIC and related guidance — describing how strong and well-validated a drug's genotype-to-management relationship is, independent of any one patient:

| Actionability state | Meaning |
|---|---|
| `NOT_MODELED` | No validated relationship is encoded for this drug in the current MVP scope. |
| `VALIDATED_LOW_INTRINSIC` | A validated relationship exists, but an established non-genetic monitoring pathway already achieves comparable safety in the typical case (Warfarin: routine PT/INR titration). |
| `VALIDATED_HIGH_INTRINSIC` | A validated relationship whose intrinsic weight already saturates the decision matrix on its own — efficacy-critical or narrow-therapeutic-index (Clopidogrel, Tacrolimus). |

`Patient-Specific Clinical Context` is a boolean state describing whether a condition specific to *this drug's own* metabolic or pharmacodynamic pathway is present for *this* patient: `NEUTRAL`, or `PATHWAY_INTERSECTING` (a severe drug-drug interaction, or an extreme lab value directly implicating the drug's own pathway — e.g. an extreme INR for Warfarin).

These two inputs resolve against a fixed decision matrix (`_PRIORITY_STATE_MATRIX` — an explicit state machine, not an additive score) to exactly one output state:

| State | Meaning |
|-------|---------|
| 🔴 HIGH PRIORITY | A validated actionable PGx relationship exists **and** patient/drug context makes genotype information particularly relevant. |
| 🟡 CONSIDER | Actionable PGx information may be useful, but clinical context does not establish a strong need for immediate testing. |
| 🟢 LOW PRIORITY | No sufficiently actionable PGx relationship is identified for the current decision, or genotype is unlikely to alter management. |

### Baseline ADR risk is an orthogonal covariate, not a value of Clinical Context

This is the core correction from the prior linear-escalation model: a patient's baseline ADR risk (Layer 2's `high_baseline_adr_risk`) makes them generally **fragile** — but that is statistically independent of whether *this specific drug's* pathway is implicated, so it can never place Clinical Context into `PATHWAY_INTERSECTING`, and it **never transitions the priority state for any drug**. It is instead reported as its own structurally separate field:

- **`triage` / `rationale` / `warnings`** — purely about whether *this drug's* genetic relationship is actionable right now: driven only by labs, DDIs, and drug-specific pathway conditions.
- **`contextual_modifier`** — `{"high_baseline_adr_risk", "state_transition_applied", "note"}`: the patient's baseline ADR risk status. `state_transition_applied` is always `False` by construction — this covariate is surfaced for clinical awareness, never folded into the state transition.

### Outputs and labs

- **Objective labs** — `age`, `weight`, `egfr` (KDIGO 2024, < 60 flags a lab abnormality), `alt_ast` (CDSCO/NFI, > 40 flags a lab abnormality), `platelets` (< 150 flags a lab abnormality), `pt_inr` (> 1.2 flags a lab abnormality). None of these is treated as a diagnosis (see Section 2). Any lab marked "Test Not Done / Unknown" passes `None` and never raises a flag.
- **Drug-drug interactions** — `check_drug_interactions(drug, concurrent_medications)` checks the patient's current medication list against a curated table of clinically significant interactions. **This DDI database is a curated MVP subset, not a comprehensive interaction checker** — the dashboard states this explicitly next to the medication input.
- **Clinical Risk Assessment verdict** — the single `high_baseline_adr_risk` boolean from Section 3, surfaced as the contextual modifier described above.

This triage runs whenever "None of the above (Run Triage)" is selected, entirely independent of `engine/rules.py` (the downstream genotype/phenotype-to-dosing engine, used instead when Genotype or Phenotype data is selected): PGx Triage answers "should we test?", `evaluate_prescription()` answers "given the result, what do we do?"

### Warfarin: `VALIDATED_LOW_INTRINSIC` — escalation requires a pathway-intersecting context

Warfarin's actionability prior alone does not saturate the decision matrix, so its default state is CONSIDER. It resolves to HIGH PRIORITY only when Patient-Specific Clinical Context is `PATHWAY_INTERSECTING` — abnormal coagulation/CBC parameters (platelets < 150 or PT/INR > 1.2) or a severe drug-drug interaction (e.g. amiodarone, an NSAID) that directly implicates warfarin's own anticoagulation mechanism. A high baseline ADR risk — however it was derived (GerontoNet score, ADATIP predictor count, elderly age, or any combination) — is an orthogonal covariate: it never transitions Warfarin's state on its own, no matter how high the underlying score. It is instead surfaced as a strong clinical warning alongside the CONSIDER output, so the elevated risk is never silently dropped, only correctly attributed to general vulnerability rather than to warfarin's specific genetic relationship.

**Clopidogrel and Tacrolimus** are `VALIDATED_HIGH_INTRINSIC` — their actionability prior alone already saturates the decision matrix (CYP2C19/CYP3A5 status is directly actionable regardless of routine labs), so they resolve to HIGH PRIORITY under any Clinical Context value. A high baseline ADR risk cannot raise them further; it is surfaced only via `contextual_modifier` as a monitoring consideration, never folded into `rationale`.

---

## 5. Clinical Context Variables

Three inputs refine (but never replace) the underlying genotype/phenotype rule and the PGx Triage decision matrix — two anchored to this individual patient's own clinical context, one an illustrative population-frequency prior:

### Tacrolimus: indication-aware TDM targets

The trough-level therapeutic drug monitoring (TDM) alert now depends on the selected **Indication / Clinical Context** (Kidney Transplant, Liver Transplant, or Other / Unspecified):

| Indication | Target trough range |
|------------|---------------------|
| Kidney Transplant | 5.0-15.0 ng/mL |
| Liver Transplant | 5.0-20.0 ng/mL |
| Unspecified | falls back to the Kidney Transplant range, rather than silently assuming a single universal target |

### G6PD (Primaquine / Rasburicase): reference-range-aware phenotype interpretation

G6PD enzyme-activity assays are not standardized across laboratories. The dashboard now accepts a **Local Laboratory Reference Range — Lower Limit of Normal (%)** input for the phenotype path; the deficiency cutoff uses that lab-specific value when supplied, falling back to a documented MVP default (10%) only when it is omitted.

### Population-Aware PGx Context (GenomeIndia Prototype)

Below the PGx Triage output, the dashboard renders a `Population-Aware PGx Context (GenomeIndia Prototype)` panel — a mock illustrating a third input into the integrated architecture: **CPIC (clinical actionability) + GenomeIndia (population-frequency context) + Patient Clinical Data (individual clinical context)**. For each MVP drug's actionable variant class (e.g. CYP2C19 loss-of-function alleles for Clopidogrel), it shows a placeholder pair of numbers — a mock GenomeIndia-cohort prior probability alongside a mock global-reference-cohort prior probability — to illustrate how a population allele-frequency prior would shift the *prior probability* of an actionable variant before any individual genotype is observed.

Every number in this panel is an illustrative placeholder, explicitly labeled as not sourced from an actual GenomeIndia data release. The panel always displays this exact safeguard disclaimer:

> Population-level frequencies act as contextual modifiers for prior probability; they cannot determine an individual's genotype and do not replace clinical prescribing guidelines.

This mockup never feeds into `triage_pgx_actionability()`'s decision matrix — it is presented purely as population-level context alongside the individual-patient-driven triage output, the same way the sidebar's "Live Clinical Literature & Similar Cases" panel previews a planned feature without being wired into any real computation.

---

## 6. Rule Provenance & Versioning

Per clinical reviewer feedback, `engine/rules.py` no longer asserts a single blanket "CPIC" label for every rule in the engine — not every rule traces to a CPIC guideline (the G6PD phenotype cutoff and the Tacrolimus TDM target ranges, for example, come from other sources). Instead, every matched rule carries its own granular provenance, defined in `RULE_PROVENANCE` and surfaced on every `evaluate_prescription()` call:

- `guideline_url` — a link to the specific guideline this rule was drawn from
- `evidence_date` — that guideline's publication date
- `rule_hash` — a short MD5 fingerprint of the rule's key, reasoning text, and recommendation, giving each individual evaluation its own lightweight version marker that changes whenever the rule's content changes

An unmatched evaluation (e.g. an unrecognized genotype) returns `None` for all three rather than fabricating provenance. The dashboard displays this per-rule provenance beneath the Decision Support Output, and the audit log records it in place of the old whole-engine constants whenever a specific rule was matched.

---

## 7. Evidence-Based Clinical Anchors

Every threshold and recommendation in the pipeline is traceable to a named, published source — nothing is inferred or fabricated:

| Guideline / Model | Used for |
|-----------|----------|
| KDIGO 2024 | Reduced-eGFR lab-abnormality flagging. |
| CDSCO / National Formulary of India (NFI) | Elevated-transaminase lab-abnormality flagging. |
| FDA Guidance | Severe drug-drug interaction (DDI) identification, and pediatric/weight-based dosing context. |
| ADATIP 9-Predictor Model (institutional) | Clinical Risk Assessment baseline ADR risk scoring. |
| GerontoNet ADR Risk Score (Onder et al., Arch Intern Med 2010) | The actual weighted Clinical Risk Assessment score — an orthogonal covariate in the PGx Triage decision matrix (Section 4), never an independent state-transition trigger. |
| GenomeIndia (Prototype) | Illustrative population-frequency priors in the mock Population-Aware PGx Context panel (Section 5) — never a determinant of PGx Actionability itself. |
| CPIC (per-rule provenance, see Section 6) | PGx Actionability priors in the Section 4 decision matrix, and the final genotype/phenotype-to-prescribing therapeutic recommendations once a PGx test has actually been ordered and resulted — no single blanket guideline label. |

This is the same "guideline lock" philosophy the rule engine has followed throughout this project: deterministic, source-cited logic instead of a model that could quietly drift from the evidence it's supposed to represent.

---

## 8. High-Value Drug Workflows (MVP Scope)

The triage layer's MVP scope is three drugs, chosen specifically because each demonstrates a different facet of the engine's nuance rather than repeating the same pattern three times:

### Clopidogrel (CYP2C19) — `VALIDATED_HIGH_INTRINSIC` plus DDI case
Always triages HIGH PRIORITY: an FDA boxed warning and CPIC guidance both treat CYP2C19 poor/intermediate metabolizer status as directly actionable for antiplatelet selection, so this relationship's actionability prior alone saturates the decision matrix. The drug-drug interaction check layers on top of that: prescribing clopidogrel alongside a strong CYP2C19 inhibitor such as omeprazole independently reduces clopidogrel activation — a pathway-intersecting condition that compounds, not replaces, the genetic risk. A High Baseline ADR Risk verdict never changes the priority state (already at the ceiling); it is reported only via `contextual_modifier`. Downstream, `evaluate_prescription()` maps the resulting CYP2C19 genotype (normal / intermediate / poor) to a specific antiplatelet recommendation, with its own guideline URL, evidence date, and rule hash.

### Tacrolimus (CYP3A5) — `VALIDATED_HIGH_INTRINSIC` plus indication-aware TDM case
Also always triages HIGH PRIORITY (narrow therapeutic index, approximately 1.5-2x starting-dose difference between CYP3A5 expresser/non-expresser genotypes per CPIC) — but a reduced eGFR or elevated transaminases (pathway-intersecting conditions) independently produce a strong clinical warning, distinct from the priority state itself, naming the exact value and threshold crossed, and framed as a lab abnormality requiring clinical correlation rather than an automatic nephrotoxicity/hepatic-impairment diagnosis. PGx sets the starting-dose baseline; lab-driven TDM and dose caution are mandatory pending that correlation (KDIGO 2024 for renal, NFI for hepatic). The TDM alert's own target trough range is indication-aware (Section 5).

### Warfarin (CYP2C9 and VKORC1) — `VALIDATED_LOW_INTRINSIC`, escalation requires pathway-intersecting context
The only one of the three whose actionability prior does not, by itself, saturate the decision matrix — Routine PT/INR-guided dose titration is often sufficient for warfarin management without upfront genetic testing, so the default state is CONSIDER. It resolves to HIGH PRIORITY only when Patient-Specific Clinical Context is `PATHWAY_INTERSECTING`: PT/INR above 1.2, Platelets below 150 x10³/µL (both reported as abnormal coagulation/CBC parameters, not a bleeding-risk diagnosis), or a severe drug-drug interaction (amiodarone or an NSAID) directly implicating warfarin's own pathway. A high Baseline ADR Risk verdict — from the Clinical Risk Assessment, however derived (GerontoNet score, ADATIP predictors, elderly age) — is an orthogonal covariate and **never** transitions this state on its own; it surfaces instead as a strong clinical warning alongside the CONSIDER output. A lab marked "Test Not Done / Unknown" never escalates on its own. Downstream, `evaluate_prescription()` combines a CYP2C9 diplotype and a VKORC1 genotype into a single sensitivity category (normal / increased / highly increased) — a simplified categorical form of CPIC's warfarin dosing framework, not the full multi-covariate pharmacogenetic equation.

**Scope note:** the five other drugs this prototype models (Carbamazepine, Allopurinol, Abacavir, Primaquine, Rasburicase) retain their existing direct genotype/phenotype-to-dosing rules in `engine/rules.py` (each with its own per-rule provenance), but do not yet have a PGx Triage pre-test model — requesting triage for them correctly returns LOW PRIORITY with an explicit "not modeled in current MVP scope" rationale, rather than a guess.

### Similar Cases Preview

Every screen keeps a permanent "Live Clinical Literature & Similar Cases (Prototype)" panel in the sidebar. This is a UI prototype only — it performs no web request, no literature search, and no scraping of any kind. It reactively reflects the currently entered age, requested drug, and ADR risk flag to preview what a live literature-matching feature would eventually surface, but the panel states plainly that its output is generated locally for demonstration and does not perform a live search.

---

## 9. Audit Trail

`storage/audit_logger.py` persists every clinician decision to SQLite (`decisions.db`), including the Clinical Risk Assessment verdict alongside the existing clinical-encounter metadata and provenance fields:

- `adr_risk_flag` — the exact High Baseline ADR Risk / Standard string computed by `calculate_adr_risk()` for that encounter.
- `guideline_version` / `evidence_source` — populated from the matched rule's own `evidence_date` / `guideline_url` when a specific rule was evaluated, falling back to coarse whole-engine constants only when no per-rule provenance is available.
- `rule_version` — populated from the matched rule's own `rule_hash` when available, falling back to the whole-engine `RULE_VERSION` otherwise.

Schema changes are strictly additive: `_get_connection()` never drops or rebuilds the `decisions` table. A database created under an older, narrower schema is brought up to date via `ALTER TABLE ADD COLUMN` for whatever columns it's missing, which preserves every existing row — there is no automatic destruction of audit data.

---

## 10. Execution Guide

PRISM-AIIMS is fully containerized and runs identically on Windows, macOS, and Linux. The recommended path is Docker Compose; a native (non-Docker) path is also provided for local development.

### Prerequisites

| OS | Install |
|----|---------|
| Windows 10/11 | [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) with the WSL2 backend enabled. Run all commands below from PowerShell, Command Prompt, or a WSL2 terminal. |
| macOS (Intel or Apple Silicon) | [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/). Run all commands below from Terminal. |
| Linux | Docker Engine plus the Compose plugin, e.g. on Ubuntu/Debian: `sudo apt-get update && sudo apt-get install docker.io docker-compose-plugin`. Add your user to the `docker` group (`sudo usermod -aG docker $USER`, then log out/in) to avoid needing `sudo` on every command. |

### Run with Docker Compose

```bash
git clone https://github.com/kgouthamt/PRISM-India.git
cd PRISM-India
docker compose up --build
```

This builds the image from the `python:3.11-slim` base, installs dependencies, and starts the Streamlit server on port 8501. The `storage/` directory is mounted as a volume, so the audit log (`decisions.db`) persists across container restarts. Open the dashboard at:

```
http://localhost:8501
```

Stop the application with:

```bash
docker compose down
```

### Running without Docker (local development)

Requires Python 3.11+. Virtual-environment activation syntax differs by shell:

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

`tests/` is a `unittest` suite of 136 tests covering every stage: `test_clinical.py` (renal/hepatic/coagulation lab-abnormality assessment from exact numeric labs including every threshold boundary, plus the exact GerontoNet score math and the composite `calculate_adr_risk` trigger logic), `test_ddi.py` (drug-drug interaction matching), `test_triage.py` (all three priority states across Clopidogrel, Tacrolimus, and Warfarin resolved via the `Testing Priority = f(Actionability, Context)` decision matrix — the lab-abnormality-driven "mandatory TDM" warnings without diagnostic overclaiming, the proof that baseline ADR risk is an orthogonal covariate that never independently transitions Warfarin's (or any drug's) priority state even at a maximal real GerontoNet/ADATIP score, and the requirement that every parameter being `None` never raises a `TypeError`), and `test_rules.py` (the downstream genotype/phenotype dosing engine, including Warfarin's combined CYP2C9 plus VKORC1 categorization, per-rule provenance, Tacrolimus's indication-aware TDM targets, and G6PD's reference-range-aware interpretation).

Run the full suite from the project root:

```bash
python -m unittest discover -s tests -t . -v
```

This exits 0 with `OK` when the suite passes, using only the Python standard library.

### End-to-end integration suite

`tests/test_final_integration.py` is a separate `pytest`-based suite driving the full Layer 2 (`calculate_adr_risk`) → Layer 3 (`triage_pgx_actionability`) pipeline through seven extreme patient profiles in one pass each -- a healthy baseline, a maximal GerontoNet score that must resolve to CONSIDER (not an independent HIGH PRIORITY escalation) for Warfarin, a maximal ADATIP score under the same constraint, a DDI collision, combined renal/hepatic lab warnings, a fully blank clinician submission (`None` labs and medications), and an out-of-scope drug -- asserting both `TypeError`/`KeyError`/state-routing correctness and the integrated decision-matrix architecture itself. It requires `pytest` (`pip install -r requirements-dev.txt`), which is deliberately kept out of the production `requirements.txt` used by the Docker image:

```bash
pip install -r requirements-dev.txt
pytest tests/test_final_integration.py -v
```

---

## Project Structure

```
PRISM-India/
├── app.py                     # Streamlit dashboard: Patient Baseline -> Clinical Risk Assessment -> PGx Triage -> Evaluation + Audit
├── engine/
│   ├── clinical.py             # Lab-abnormality assessment + calculate_gerontonet_score() + calculate_adr_risk()
│   ├── ddi.py                  # Drug-drug interaction checker (curated MVP subset), used within PGx Triage
│   ├── triage.py                # PGx Triage decision matrix: Testing Priority = f(Actionability, Context)
│   └── rules.py                 # Downstream genotype/phenotype -> dosing engine + per-rule provenance: evaluate_prescription()
├── storage/
│   └── audit_logger.py         # SQLite audit trail: log_decision(), get_all_logs() -- includes adr_risk_flag
├── abdm/
│   └── fhir_builder.py         # FHIR R4 Bundle generator: generate_fhir_bundle()
├── tests/
│   ├── test_clinical.py
│   ├── test_ddi.py
│   ├── test_triage.py
│   ├── test_rules.py
│   └── test_final_integration.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```
