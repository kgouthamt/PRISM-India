# PRISM-AIIMS
### Cost-Conscious Pre-Test Triage Engine and Clinical Decision Support System
**Team ID:** DENDRITE-PE-XD-018

---

## 1. Executive Summary

PRISM-AIIMS is not a post-test genotype lookup dictionary — a system that sits idle until a genetic test result arrives and only then evaluates it. That framing accepts an expensive assumption: that the test was worth ordering in the first place, and that baseline patient state was already accounted for. Pharmacogenomic panels are not free, not instant, and not always necessary — in a resource-constrained health system, ordering one for every patient on every drug is neither clinically nor economically defensible.

This revision returns the application to a **strictly separated 3-Layer architecture**, in which each layer is an independent module boundary: Layer *N* consumes only the outputs Layer *N-1* explicitly exposes to it, never Layer *N-1*'s internal state. Every computation in this document is described in state-machine, boolean-logic, and probabilistic terms — a layer's output is a value of a defined state space, a covariate is either dependent or orthogonal to another variable, and a "decoupled" module is, precisely, a pure function of its own stated input alone.

1. **Layer 1: Clinical Details** — Demographics, Vitals, and Laboratory Data. Every laboratory parameter is captured as a strict three-valued logical state — `True` (Abnormal), `False` (Normal), or `None` (Missing Data) — not a numeric reading compared against a threshold inside the engine. Marking a parameter `True` immediately transitions it to its `ABNORMAL -> FLAG` state.
2. **Layer 2: ADR Risk Prediction** — the ADATIP 9-Predictor Model and the **actual, validated GerontoNet ADR Risk Score** are evaluated as **isolated execution contexts**: two statistically independent predictor sets over the same patient, each rendering its own verdict, with neither computation reading the other's internal state.
3. **Layer 3: Pharmacogenomics** — a single boolean routing variable, `Genotyping Results: {Available, Not Available}`, replaces the previous three-way diagnostic-data radio. `Available` routes to the standard CPIC allele pathway lookup (a specific dosage recommendation); `Not Available` resolves the **integrated decision matrix** `Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)` to a CPIC pre-test recommendation (`Required` / `Recommended` / `Not Indicated`), then separately renders a mock, ethnicity-keyed GenomeIndia population-priority lookup that is a pure function of ethnicity alone and is never combined with any other layer's output.
4. **Reporting and Audit** — an integrated summary report at the foot of the interface aggregates all three layers' outputs into one view, with a single pair of clinician **Accept** / **Override** controls that push the final decision to the Audit Log.

### This revision: a strictly separated 3-Layer architecture, with two independent decoupling guarantees

A prior revision organized the interface around a linear top-to-bottom workflow ("Patient Baseline & Vitals" → "Clinical Risk Assessment" → "PGx Triage") in which laboratory inputs lived inside the PGx Triage section itself, and a three-way radio (Genotype Data / Phenotype-TDM Data / Run Triage) governed Layer 3's routing. This revision instead enforces the layer boundary explicitly:

- **Layer 1 now owns all laboratory data.** eGFR, ALT/AST, Platelets, and PT/INR are collected once, in Layer 1, as `True`/`False`/`None` state flags — never a numeric reading — and that same three-valued state is what Layer 3's decision matrix consumes.
- **Layer 2 renders two independent verdicts, not one.** `calculate_adr_risk()` now exposes `adatip_isolated_verdict` and `gerontonet_isolated_verdict` as two separately computed, separately rendered outputs — "ADR in acute vulnerable patient:" and "ADR in chronic fragility:" — in addition to the pre-existing composite `high_baseline_adr_risk` boolean that Layer 3's orthogonal-covariate model still consumes.
- **Layer 3's routing is now a single boolean**, `Genotyping Results: {Available, Not Available}`, and its `Not Available` path now renders two structurally distinct outputs in sequence: first, a deterministic `Required`/`Recommended`/`Not Indicated` projection of the resolved Testing Priority state; second, an entirely decoupled mock GenomeIndia ethnicity lookup.
- **CRITICAL DECOUPLING.** The GenomeIndia population-priority output is a pure function of ethnicity alone. It is never integrated, multiplied, or combined with Layer 1 or Layer 2 outputs, and it is never read by `_resolve_priority_state` or returned inside `triage_pgx_actionability`'s result — it is an independent, population-based recommendation, full stop.
- **A single integrated Reporting and Audit surface.** Accept/Override no longer live inline inside Layer 3's Path A container; they now live once, at the bottom of the page, beneath a summary that lists every layer's output — including the GenomeIndia priority, reported without being merged into anything else.

An earlier revision of this prototype had also accumulated several clinical oversimplifications flagged by medical reviewers, which remain corrected in this revision:

- **Lab abnormalities no longer masquerade as diagnoses.** An abnormal-flagged eGFR is never reported as "universally high nephrotoxicity risk"; an abnormal-flagged ALT/AST is never reported as "hepatic impairment"; abnormal-flagged platelets/PT-INR are never reported as "universally high bleeding risk." Each is reported as exactly what it is — a flagged lab abnormality requiring clinical correlation — never an automatic diagnosis.
- **The GerontoNet ADR Risk Score is the actual, published, weighted score** (0-10 points, High Risk only at 4+), not a derived "2-or-more-predictors" binary heuristic.
- **Tacrolimus TDM targets are indication-aware** (Kidney vs. Liver Transplant), and **G6PD phenotype interpretation is reference-range aware** (the ordering lab's own lower limit of normal, not a single universal cutoff).
- **The DDI database is explicitly labeled as a curated MVP subset**, not a comprehensive interaction checker.
- **There is no single blanket "CPIC" label** describing every rule in the engine. Each individual rule carries its own `guideline_url`, `evidence_date`, and a short `rule_hash` fingerprint.

### The Workflow

The dashboard follows this exact sequence on one screen, top to bottom:

1. **Layer 1: Clinical Details** — Demographics (Name, Patient ID, Age), Vitals (Weight, Pulse Rate, Blood Pressure, Respiratory Rate, SpO2, Temperature), and Laboratory Data (eGFR, ALT/AST, Platelets, PT/INR), each captured as an independent `Abnormal`/`Normal`/`Missing Data` selector. Selecting `Abnormal` immediately renders an `ABNORMAL → FLAG` indicator inline.
2. **Layer 2: ADR Risk Prediction** — checkboxes and numeric inputs for the ADATIP 9-Predictor Model, the actual GerontoNet Risk Score, and a General Clinical History section, evaluated reactively; two independent banners — "ADR in acute vulnerable patient:" and "ADR in chronic fragility:" — each resolve to `High Risk` or `Baseline Standard` on their own. Below both banners, a Web Search mockup issues three independent literature queries — `ADR Risk`, `Family Risk`, `Allergic Risk` — each with its own mock case-report count and a real PubMed search link.
3. **Layer 3: Pharmacogenomics** — the drug being requested, current medications (with a disclaimer that the DDI database is a curated MVP subset), and a single boolean routing question, `Genotyping Results: {Available, Not Available}`.
   - **Path A — Available.** The standard CPIC allele pathway lookup: the exact test result (Genotype or Phenotype/TDM), drug-specific clinical-context inputs (Tacrolimus's transplant indication; G6PD's local lab reference range), an Evaluate action, and the specific dosage recommendation (`engine/rules.py`) — including that specific rule's own provenance.
   - **Path B — Not Available.** The Testing-Priority decision matrix (`engine/triage.py`) resolves against Layer 1's lab flags, DDIs, and Layer 2's baseline ADR risk verdict, first outputting the CPIC pre-test recommendation (`Required` / `Recommended` / `Not Indicated`); separately, an Ethnicity dropdown drives a mock, fully decoupled GenomeIndia population-priority lookup (`High Priority` / `Medium Priority` / `Low Priority`).
4. **Reporting and Audit** — a single integrated summary of all three layers' outputs, followed by one pair of **Accept** / **Override** controls that log the encounter to the Audit Log and (on Path A) generate the FHIR bundle.

The sidebar carries a permanent "Live Clinical Literature & Similar Cases" panel — a UI prototype, clearly labeled and non-functional, previewing a planned literature-search feature, distinct from Layer 2's own Web Search mockup.

---

## 2. Layer 1: Clinical Details

Objective intake data, collected before any risk scoring runs:

| Group | Fields |
|-------|--------|
| Demographics | Patient Name, Patient ID, Age |
| Vitals | Weight (kg), Pulse Rate, Blood Pressure (systolic/diastolic), Respiratory Rate, SpO2, Temperature |
| Laboratory Data | eGFR, ALT/AST, Platelets, PT/INR — each a three-valued state |

Age and Weight feed forward into Layer 2 (the ADATIP age predictor) and into `assess_age_weight_context()` (pediatric/low-body-weight dosing flags, FDA-anchored).

**Every laboratory parameter is a strict three-valued logical state, not a numeric quantity compared against a threshold at runtime.** A clinician reduces a lab reading to exactly one of `True` (Abnormal), `False` (Normal), or `None` (Missing Data) at the point of entry; the engine that consumes it never re-derives that state from a raw number, and it never treats a missing state as evidence for either of the other two. Marking a parameter `True` immediately transitions its status field to its abnormal state — `ABNORMAL -> FLAG` — with no intermediate comparison step:

| Parameter | Reference threshold cited for the clinician's own judgment | Abnormal (`True`) status | Reported as |
|-----------|--------------------------------------------------------------|---------------------------|-------------|
| eGFR | < 60 mL/min/1.73m² (KDIGO 2024) | `renal_function_status = "REDUCED"` | "Reduced eGFR flagged as abnormal; requires clinical correlation for renal dose adjustment." |
| ALT/AST | > 40 U/L (CDSCO / National Formulary of India) | `transaminase_status = "ELEVATED"` | "Elevated transaminases flagged as abnormal; laboratory abnormality." |
| Platelets | < 150 x10³/µL | `coagulation_cbc_status = "ABNORMAL"` | "Abnormal coagulation/CBC parameters." |
| PT/INR | > 1.2 | `coagulation_cbc_status = "ABNORMAL"` | "Abnormal coagulation/CBC parameters." |

The functions that compute these (`assess_renal_function`, `assess_hepatic_function`, `assess_bleeding_risk_labs` in `engine/clinical.py`) are pure state-transition functions over `egfr_abnormal`, `alt_ast_abnormal`, `platelets_abnormal`, and `pt_inr_abnormal` — each `True`/`False`/`None` — returning `renal_function_status` (REDUCED/NORMAL/UNKNOWN), `transaminase_status` (ELEVATED/NORMAL/UNKNOWN), and `coagulation_cbc_status` (ABNORMAL/NORMAL/UNKNOWN) respectively. Selecting "Missing Data" for a lab passes `None` for that parameter — a skipped test is never silently treated as a normal result.

---

## 3. Layer 2: ADR Risk Prediction

`calculate_adr_risk()` (`engine/clinical.py`) evaluates systemic patient vulnerability using two **isolated execution contexts** — independent predictor sets whose computations never read each other's internal state — plus a clinician-reported general history layered on top.

### ADATIP 9-Predictor Model (acute presentation) — an isolated execution context

An institutional model capturing acute-presentation risk factors, all 9 predictors implemented. No published point-weighted formula was available for this model, so it uses a "2 or more predictors present" heuristic:

| Predictor | Type |
|-----------|------|
| Age (≥ 65 years) | derived from Layer 1 |
| Chronic lung disease | checkbox |
| Primary presenting complaints of respiratory disorders | checkbox |
| Primary presenting complaints of bleeding disorders | checkbox |
| Primary presenting complaints of GI disorders | checkbox |
| Syncope on hospital admission | checkbox |
| Antithrombotics | checkbox |
| Diuretics | checkbox |
| RAAS drugs | checkbox |

Its independent verdict, `adatip_isolated_verdict`, is rendered as:

> **ADR in acute vulnerable patient:** High Risk / Baseline Standard

### GerontoNet ADR Risk Score (chronic fragility and polypharmacy) — an isolated execution context

Published clinical score: Onder G, et al. "Development and validation of a score to assess risk of adverse drug reactions among in-hospital patients 65 years or older: the GerontoNet ADR risk score." Arch Intern Med. 2010.

`calculate_gerontonet_score()` computes the real weighted point total (0-10), independently of the ADATIP predictor set above:

| Criterion | Points |
|-----------|--------|
| ≥ 4 comorbid conditions | +1 |
| Heart failure | +1 |
| Liver disease | +1 |
| Renal failure | +1 |
| 5-7 concurrent drugs | +1 |
| ≥ 8 concurrent drugs | +4 (supersedes the 5-7 band) |
| Previous history of ADR | +2 |

The result is classified **High Risk only if the total score is 4 or more** — otherwise Low Risk; a single strong predictor (e.g. Previous ADR history alone, worth 2 points) is **not**, on its own, enough to reach High Risk under the real score. Its independent verdict, `gerontonet_isolated_verdict`, is rendered as:

> **ADR in chronic fragility:** High Risk / Baseline Standard

Both verdicts use the identical two-valued vocabulary (`High Risk` / `Baseline Standard`) deliberately — neither UI output implies it carries more, or less, information than the other; they are two independent variables over the same patient, not a ranked pair.

### General clinical history (clinician-reported)

A dedicated section capturing history that contributes only to the composite verdict below, never to either isolated model verdict:

| Field | Effect |
|-------|--------|
| Previous ADR history | feeds the GerontoNet score above (+2 points) |
| Allergy history | contributes to a 2-of-2 secondary heuristic with Family history |
| Family history | contributes to the same 2-of-2 secondary heuristic |

### Composite trigger logic (consumed by Layer 3's orthogonal covariate)

`calculate_adr_risk()` still returns a single composite **High Baseline ADR Risk** boolean if **any** of the following hold, otherwise **Standard** — this is the value Layer 3 consumes as its orthogonal covariate (Section 4), distinct from the two isolated verdicts above:

- the GerontoNet ADR Risk Score is High Risk (total score ≥ 4), **or**
- **2 or more** ADATIP predictors are present, **or**
- **both** Allergy history and Family history are present.

The result dict — `{"high_baseline_adr_risk", "adr_risk_flag", "adatip_trigger_count", "adatip_isolated_verdict", "gerontonet_score", "gerontonet_isolated_verdict", "general_history_trigger_count", "reasons", "source"}` — is what crosses into Layer 3 and the audit log.

### Web Search mockup

Below the two isolated verdicts, a mock literature-search panel issues three independent queries, each keyed to its own boolean input variable rather than a single combined flag:

| Query | Input variable |
|-------|-----------------|
| `ADR Risk` | ADATIP's own isolated verdict |
| `Family Risk` | Family history checkbox |
| `Allergic Risk` | Allergy history checkbox |

Each query line links to a real PubMed search for that term; the displayed case count is an illustrative placeholder, not the output of a server-side search PRISM-AIIMS itself performs.

---

## 4. Layer 3: Pharmacogenomics

Layer 3 begins with a single boolean routing variable:

> **Genotyping Results:** `Available` / `Not Available`

### Path A — Available: the standard CPIC allele pathway lookup

When a PGx result already exists, the dashboard goes straight to interpreting it — the exact test result (Genotype, or Phenotype/TDM, selectable within this path), drug-specific clinical-context inputs, and `evaluate_prescription()` (`engine/rules.py`), producing the specific dosage recommendation and its own rule provenance (Section 6).

### Path B — Not Available: the Testing-Priority decision matrix, then two sequential outputs

`triage_pgx_actionability()` (`engine/triage.py`) resolves:

```
Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)
```

`PGx Actionability` is a categorical prior — anchored to CPIC and related guidance — describing how strong and well-validated a drug's genotype-to-management relationship is, independent of any one patient:

| Actionability state | Meaning |
|---|---|
| `NOT_MODELED` | No validated relationship is encoded for this drug in the current MVP scope. |
| `VALIDATED_LOW_INTRINSIC` | A validated relationship exists, but an established non-genetic monitoring pathway already achieves comparable safety in the typical case (Warfarin: routine PT/INR titration). |
| `VALIDATED_HIGH_INTRINSIC` | A validated relationship whose intrinsic weight already saturates the decision matrix on its own — efficacy-critical or narrow-therapeutic-index (Clopidogrel, Tacrolimus). |

`Patient-Specific Clinical Context` is a boolean state describing whether a condition specific to *this drug's own* metabolic or pharmacodynamic pathway is present for *this* patient: `NEUTRAL`, or `PATHWAY_INTERSECTING` (a severe drug-drug interaction, or an abnormal-flagged lab state directly implicating the drug's own pathway — driven entirely by Layer 1's `True`/`False`/`None` flags, never a raw numeric reading).

These two inputs resolve against a fixed decision matrix (`_PRIORITY_STATE_MATRIX` — an explicit state machine, not an additive score) to exactly one output state, which is then projected onto CPIC's own pre-test testing vocabulary:

| Testing Priority state | Meaning | CPIC Pre-Test Recommendation |
|-------|---------|-------------------------------|
| 🔴 HIGH PRIORITY | A validated actionable PGx relationship exists **and** patient/drug context makes genotype information particularly relevant. | **Required** |
| 🟡 CONSIDER | Actionable PGx information may be useful, but clinical context does not establish a strong need for immediate testing. | **Recommended** |
| 🟢 LOW PRIORITY | No sufficiently actionable PGx relationship is identified, or genotype is unlikely to alter management. | **Not Indicated** |

`resolve_cpic_testing_recommendation()` is this deterministic projection: it carries no information the state machine did not already produce, and CPIC guidance itself does not separately name a LOW-PRIORITY-equivalent state, so `Not Indicated` is this MVP's own extension for that case.

#### Baseline ADR risk is an orthogonal covariate, not a value of Clinical Context

A patient's baseline ADR risk (Layer 2's composite `high_baseline_adr_risk`) makes them generally **fragile** — but that is statistically independent of whether *this specific drug's* pathway is implicated, so it can never place Clinical Context into `PATHWAY_INTERSECTING`, and it **never transitions the priority state for any drug**. It is instead reported as its own structurally separate field, `contextual_modifier` — `{"high_baseline_adr_risk", "state_transition_applied", "note"}` — with `state_transition_applied` always `False` by construction.

#### Second output — GenomeIndia population context: an isolated, decoupled module

After the CPIC Required/Recommended/Not Indicated output, Layer 3 (Path B) renders an **Ethnicity** dropdown and a mock GenomeIndia population-priority lookup, `genomeindia_population_priority(ethnicity)`:

```python
def genomeindia_population_priority(ethnicity: str) -> dict:
    priority = GENOMEINDIA_ETHNICITY_PRIORS.get(ethnicity, GENOMEINDIA_PRIORITY_LOW)
    return {"ethnicity": ethnicity, "genomeindia_priority": priority, "source": ...}
```

**CRITICAL DECOUPLING.** This function's return value is a pure function of `ethnicity` alone:

- it is **never integrated, multiplied, or combined** with Layer 1 (lab-abnormality flags) or Layer 2 (baseline ADR risk) outputs;
- it is **never read by `_resolve_priority_state`**, and it never appears inside `triage_pgx_actionability`'s return value — no function in `engine/triage.py` consumes it;
- it serves as an **independent, population-based recommendation only**, resolving to `High Priority`, `Medium Priority`, or `Low Priority` for demonstration purposes, never sourced from an actual GenomeIndia data release, and never a substitute for an individual genotype result.

The Integration Test suite (`tests/test_final_integration.py`, `test_case_8`) asserts this decoupling directly: the same Warfarin clinical profile resolves to the identical Testing Priority state regardless of which ethnicity's GenomeIndia priority is looked up alongside it.

---

## 5. Clinical Context Variables

Two inputs refine (but never replace) the underlying genotype/phenotype rule, both anchored to this individual patient's own clinical context:

### Tacrolimus: indication-aware TDM targets

The trough-level therapeutic drug monitoring (TDM) alert depends on the selected **Indication / Clinical Context** (Kidney Transplant, Liver Transplant, or Other / Unspecified):

| Indication | Target trough range |
|------------|---------------------|
| Kidney Transplant | 5.0-15.0 ng/mL |
| Liver Transplant | 5.0-20.0 ng/mL |
| Unspecified | falls back to the Kidney Transplant range, rather than silently assuming a single universal target |

### G6PD (Primaquine / Rasburicase): reference-range-aware phenotype interpretation

G6PD enzyme-activity assays are not standardized across laboratories. Path A's Phenotype path accepts a **Local Laboratory Reference Range — Lower Limit of Normal (%)** input; the deficiency cutoff uses that lab-specific value when supplied, falling back to a documented MVP default (10%) only when it is omitted.

---

## 6. Rule Provenance & Versioning

Per clinical reviewer feedback, `engine/rules.py` does not assert a single blanket "CPIC" label for every rule in the engine — not every rule traces to a CPIC guideline (the G6PD phenotype cutoff and the Tacrolimus TDM target ranges, for example, come from other sources). Instead, every matched rule carries its own granular provenance, defined in `RULE_PROVENANCE` and surfaced on every `evaluate_prescription()` call:

- `guideline_url` — a link to the specific guideline this rule was drawn from
- `evidence_date` — that guideline's publication date
- `rule_hash` — a short MD5 fingerprint of the rule's key, reasoning text, and recommendation

An unmatched evaluation (e.g. an unrecognized genotype) returns `None` for all three rather than fabricating provenance. The dashboard displays this per-rule provenance beneath the Decision Support Output, and the audit log records it in place of the old whole-engine constants whenever a specific rule was matched.

---

## 7. Evidence-Based Clinical Anchors

Every threshold and recommendation in the pipeline is traceable to a named, published source — nothing is inferred or fabricated:

| Guideline / Model | Used for |
|-----------|----------|
| KDIGO 2024 | Renal-function abnormality reference threshold cited when a clinician flags eGFR as Abnormal. |
| CDSCO / National Formulary of India (NFI) | Hepatic-transaminase abnormality reference threshold cited when a clinician flags ALT/AST as Abnormal. |
| FDA Guidance | Severe drug-drug interaction (DDI) identification, and pediatric/weight-based dosing context. |
| ADATIP 9-Predictor Model (institutional) | Layer 2's independent acute-presentation isolated verdict. |
| GerontoNet ADR Risk Score (Onder et al., Arch Intern Med 2010) | Layer 2's independent chronic-fragility isolated verdict; also an orthogonal covariate in the Layer 3 decision matrix, never an independent state-transition trigger. |
| GenomeIndia (Prototype) | The Layer 3, Path B ethnicity-keyed population-priority lookup — an isolated, decoupled module, never a determinant of PGx Actionability itself. |
| CPIC (per-rule provenance, see Section 6) | PGx Actionability priors in the Layer 3 decision matrix, the Required/Recommended/Not Indicated projection, and the final genotype/phenotype-to-prescribing therapeutic recommendations once a PGx test has actually been ordered and resulted. |

This is the same "guideline lock" philosophy the rule engine has followed throughout this project: deterministic, source-cited logic instead of a model that could quietly drift from the evidence it's supposed to represent.

---

## 8. High-Value Drug Workflows (MVP Scope)

The triage layer's MVP scope is three drugs, chosen specifically because each demonstrates a different facet of the engine's nuance rather than repeating the same pattern three times:

### Clopidogrel (CYP2C19) — `VALIDATED_HIGH_INTRINSIC` plus DDI case
Always triages HIGH PRIORITY / CPIC **Required**: an FDA boxed warning and CPIC guidance both treat CYP2C19 poor/intermediate metabolizer status as directly actionable for antiplatelet selection, so this relationship's actionability prior alone saturates the decision matrix. The drug-drug interaction check layers on top of that: prescribing clopidogrel alongside a strong CYP2C19 inhibitor such as omeprazole independently reduces clopidogrel activation — a pathway-intersecting condition that compounds, not replaces, the genetic risk. A High Baseline ADR Risk verdict never changes the priority state (already at the ceiling); it is reported only via `contextual_modifier`. Downstream, `evaluate_prescription()` maps the resulting CYP2C19 genotype (normal / intermediate / poor) to a specific antiplatelet recommendation, with its own guideline URL, evidence date, and rule hash.

### Tacrolimus (CYP3A5) — `VALIDATED_HIGH_INTRINSIC` plus indication-aware TDM case
Also always triages HIGH PRIORITY / CPIC **Required** (narrow therapeutic index, approximately 1.5-2x starting-dose difference between CYP3A5 expresser/non-expresser genotypes per CPIC) — but an abnormal-flagged eGFR or ALT/AST (pathway-intersecting conditions) independently produce a strong clinical warning, distinct from the priority state itself, framed as a lab abnormality requiring clinical correlation rather than an automatic nephrotoxicity/hepatic-impairment diagnosis. PGx sets the starting-dose baseline; lab-driven TDM and dose caution are mandatory pending that correlation. The TDM alert's own target trough range is indication-aware (Section 5).

### Warfarin (CYP2C9 and VKORC1) — `VALIDATED_LOW_INTRINSIC`, escalation requires pathway-intersecting context
The only one of the three whose actionability prior does not, by itself, saturate the decision matrix — routine PT/INR-guided dose titration is often sufficient for warfarin management without upfront genetic testing, so the default state is CONSIDER / CPIC **Recommended**. It resolves to HIGH PRIORITY / **Required** only when Patient-Specific Clinical Context is `PATHWAY_INTERSECTING`: an abnormal-flagged PT/INR or Platelets state (reported as abnormal coagulation/CBC parameters, not a bleeding-risk diagnosis), or a severe drug-drug interaction (amiodarone or an NSAID) directly implicating warfarin's own pathway. A high Baseline ADR Risk verdict — from Layer 2, however derived (GerontoNet score, ADATIP predictors, elderly age) — is an orthogonal covariate and **never** transitions this state on its own; it surfaces instead as a strong clinical warning alongside the CONSIDER output. A lab left at "Missing Data" never escalates on its own. Downstream, `evaluate_prescription()` combines a CYP2C9 diplotype and a VKORC1 genotype into a single sensitivity category (normal / increased / highly increased) — a simplified categorical form of CPIC's warfarin dosing framework, not the full multi-covariate pharmacogenetic equation.

**Scope note:** the five other drugs this prototype models (Carbamazepine, Allopurinol, Abacavir, Primaquine, Rasburicase) retain their existing direct genotype/phenotype-to-dosing rules in `engine/rules.py` (each with its own per-rule provenance), but do not yet have a Path B Testing-Priority model — running triage for them correctly returns LOW PRIORITY / **Not Indicated** with an explicit "not modeled in current MVP scope" rationale, rather than a guess.

### Similar Cases Preview

Every screen keeps a permanent "Live Clinical Literature & Similar Cases (Prototype)" panel in the sidebar, distinct from Layer 2's own Web Search mockup. This is a UI prototype only — it performs no web request, no literature search, and no scraping of any kind. It reactively reflects the currently entered age, requested drug, and ADR risk flag to preview what a live literature-matching feature would eventually surface.

---

## 9. Reporting and Audit

At the foot of the interface, an **integrated summary report** aggregates all three layers' outputs into one view:

- Layer 1's four lab flags, each rendered as `ABNORMAL → FLAG`, `Normal`, or `Missing Data`.
- Layer 2's two isolated verdicts — "ADR in acute vulnerable patient" and "ADR in chronic fragility."
- Layer 3's outcome: either Path A's CPIC allele pathway outcome and dosage recommendation, or Path B's Testing Priority state and CPIC pre-test recommendation, followed by the GenomeIndia population priority reported separately, exactly as computed, never merged into the line above it.

A single pair of **Accept** / **Override** controls beneath this report is the one place either path's decision is pushed to the Audit Log — Path A's inline decision card and Path B's triage output both defer logging to this shared control, which calls the same `log_decision()` / `generate_fhir_bundle()` pipeline regardless of which path produced the recommendation being accepted or overridden.

`storage/audit_logger.py` persists every clinician decision to SQLite (`decisions.db`), including the Layer 2 composite `adr_risk_flag` alongside the existing clinical-encounter metadata and provenance fields. `guideline_version` / `evidence_source` / `rule_version` populate from the matched rule's own per-rule provenance when Path A produced the decision, falling back to coarse whole-engine constants for a Path B (pre-test triage) decision, which has no single matched rule.

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

`tests/` is a `unittest` suite of 155 tests covering every layer: `test_clinical.py` (the Layer 1 three-valued lab-abnormality state machine across every parameter, the exact GerontoNet score math, the composite `calculate_adr_risk` trigger logic, and the isolated ADATIP/GerontoNet verdict exposure), `test_ddi.py` (drug-drug interaction matching), `test_triage.py` (all three priority states across Clopidogrel, Tacrolimus, and Warfarin resolved via the `Testing Priority = f(Actionability, Context)` decision matrix over three-valued lab flags, the CPIC Required/Recommended/Not Indicated projection, the proof that baseline ADR risk is an orthogonal covariate that never independently transitions any drug's priority state even at a maximal real GerontoNet/ADATIP score, the CRITICAL DECOUPLING of the mock GenomeIndia ethnicity lookup from the triage pipeline, and the requirement that every parameter being `None` never raises a `TypeError`), and `test_rules.py` (the downstream genotype/phenotype dosing engine, including Warfarin's combined CYP2C9 plus VKORC1 categorization, per-rule provenance, Tacrolimus's indication-aware TDM targets, and G6PD's reference-range-aware interpretation).

Run the full suite from the project root:

```bash
python -m unittest discover -s tests -t . -v
```

This exits 0 with `OK` when the suite passes, using only the Python standard library.

### End-to-end integration suite

`tests/test_final_integration.py` is a separate `pytest`-based suite driving the full Layer 2 (`calculate_adr_risk`) → Layer 3 (`triage_pgx_actionability`) pipeline through eight extreme patient profiles in one pass each -- a healthy baseline, a maximal GerontoNet score that must resolve to CONSIDER (not an independent HIGH PRIORITY escalation) for Warfarin, a maximal ADATIP score under the same constraint, a DDI collision, combined renal/hepatic lab-flag warnings, a fully blank clinician submission (`None` labs and medications), an out-of-scope drug, and the CRITICAL DECOUPLING of the mock GenomeIndia ethnicity lookup across every population option -- asserting both `TypeError`/`KeyError`/state-routing correctness and the integrated decision-matrix architecture itself. It requires `pytest` (`pip install -r requirements-dev.txt`), which is deliberately kept out of the production `requirements.txt` used by the Docker image:

```bash
pip install -r requirements-dev.txt
pytest tests/test_final_integration.py -v
```

---

## Project Structure

```
PRISM-India/
├── app.py                     # Streamlit dashboard: Layer 1 -> Layer 2 -> Layer 3 -> Reporting and Audit
├── engine/
│   ├── clinical.py             # Layer 1 lab-abnormality state machine + isolated Layer 2 ADATIP/GerontoNet verdicts
│   ├── ddi.py                  # Drug-drug interaction checker (curated MVP subset), used within Layer 3, Path B
│   ├── triage.py                # Layer 3, Path B: Testing Priority = f(Actionability, Context); CPIC Required/Recommended projection; decoupled GenomeIndia lookup
│   └── rules.py                 # Layer 3, Path A: genotype/phenotype -> dosing engine + per-rule provenance: evaluate_prescription()
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
