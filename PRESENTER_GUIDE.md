# PRISM-AIIMS — Presenter's Guide

*A comprehensive, non-technical-audience-safe handover explaining exactly how PRISM-AIIMS computes its recommendations — every threshold, every weight, every logic gate, stated precisely.*

---

## 1. Executive Summary & Pitch

**PRISM-AIIMS is a Cost-Conscious Pre-Test Triage Engine and Clinical Decision Support System.**

Its job is to answer one question, computationally, before a rupee is spent on a genetic test: *given this patient's baseline clinical state and the drug being considered, what is the probability that a genetic test result would actually change the prescribing decision?*

It does this by integrating two independent sources of evidence into a single output:

1. **Clinical vulnerability** — a quantitative assessment of how fragile this specific patient is right now, computed from objective lab values and two validated risk-scoring instruments.
2. **Genomic guideline actionability** — a categorical prior, anchored to CPIC (Clinical Pharmacogenetics Implementation Consortium) guidance, describing how strong the published evidence is that a drug's outcome depends on genotype.

These two inputs are combined through a deterministic decision function — not a guess, not a black box — to output exactly one of three states: **HIGH PRIORITY**, **CONSIDER**, or **LOW PRIORITY**. Every number that feeds that function is either a lab value the clinician typed in, or a checkbox they ticked. Nothing is inferred beyond what the guidelines specify.

**The one-line pitch:** *"PRISM-AIIMS computes testing priority as a function of two independent variables — how vulnerable the patient is, and how actionable the drug's genetics are — so genetic testing budget is spent exactly where the probability of changing management is highest."*

---

## 2. Deep Dive: Layer 1 — Patient Baseline & Vitals

Layer 1 collects the patient's demographic and physiological baseline, plus (further into the workflow, when no genetic result exists yet) four objective lab values. Each lab value is compared against a fixed numeric threshold. Crossing a threshold sets a boolean flag — it never asserts a diagnosis. This distinction is deliberate and load-bearing: a lab value crossing a cutoff is a **fact**; whether that fact constitutes a **diagnosis** is a judgment the system explicitly leaves to the clinician.

| Lab value | Threshold (boolean condition) | Why it is used | Guideline anchor | System output |
|---|---|---|---|---|
| **eGFR** (estimated Glomerular Filtration Rate) | `eGFR < 60 mL/min/1.73m²` | eGFR is the standard proxy for renal clearance capacity. Below this cutoff, a drug's clearance rate can no longer be assumed normal, independent of genotype. | **KDIGO 2024** (Kidney Disease: Improving Global Outcomes) | `renal_function_status = "REDUCED"` — explicitly labeled as a lab abnormality requiring clinical correlation, never as a nephrotoxicity diagnosis. |
| **ALT/AST** (Alanine/Aspartate Aminotransferase) | `ALT/AST > 40 U/L` | ALT/AST are the standard proxy for hepatic metabolic capacity. Above this cutoff, hepatic drug metabolism can no longer be assumed normal. | **NFI** (National Formulary of India / CDSCO) | `transaminase_status = "ELEVATED"` — a laboratory abnormality, never an automatic hepatic-impairment diagnosis. |
| **Platelets** | `Platelets < 150 ×10³/µL` | Below this cutoff, baseline coagulation capacity is reduced before any anticoagulant is even started. | Routine Coagulation/CBC reference range | `coagulation_cbc_status = "ABNORMAL"` |
| **PT/INR** (Prothrombin Time / International Normalized Ratio) | `INR > 1.2` | Above this cutoff, the coagulation cascade is already sensitized — directly relevant for any drug (like Warfarin) that acts on that same pathway. | Routine Coagulation/CBC reference range | `coagulation_cbc_status = "ABNORMAL"` |

**A boolean-logic note on missing data:** every one of these four checks accepts `None` (a clinician marking "Test Not Done / Unknown") as a valid input. `None` is never coerced to a "normal" value and never sets the abnormality flag — the condition `value < threshold` is only ever evaluated when `value` is an actual number. Absence of data is mathematically distinct from a normal result.

---

## 3. Deep Dive: Layer 2 — Clinical Risk Assessment

Layer 2 answers a different question than Layer 1: not "is one lab abnormal," but "how vulnerable is this patient, in aggregate, to any adverse drug reaction (ADR), independent of which drug is being considered." It computes this using two independent, published instruments.

### 3.1 The ADATIP 9-Predictor Model — a 9-dimensional boolean vector

ADATIP evaluates nine independent binary predictors of **acute** vulnerability — conditions and exposures present at the moment of admission. Formally, this is a boolean vector `V = [v₁, v₂, ..., v₉] ∈ {0,1}⁹`:

| # | Predictor (vᵢ) | Boolean domain |
|---|---|---|
| 1 | Age ≥ 65 years | `{True, False}` (derived from Layer 1's Age field) |
| 2 | Chronic lung disease | `{True, False}` |
| 3 | Presenting complaint: respiratory disorder | `{True, False}` |
| 4 | Presenting complaint: bleeding disorder | `{True, False}` |
| 5 | Presenting complaint: GI disorder | `{True, False}` |
| 6 | Syncope on hospital admission | `{True, False}` |
| 7 | On antithrombotics | `{True, False}` |
| 8 | On diuretics | `{True, False}` |
| 9 | On RAAS drugs (ACE inhibitors / ARBs) | `{True, False}` |

The model's predicate function counts how many of the nine are simultaneously `True` — `count(V) = Σvᵢ` — and evaluates a single threshold condition: **`count(V) ≥ 2`**. In plain terms, ADATIP is checking for *intersections*: no single acute predictor is treated as sufficient on its own, but any two co-occurring acute predictors (for example, syncope **and** being on RAAS drugs at the same time) cross the threshold and set the model's contribution to `True`. This is why it is best understood as a boolean matrix scan for intersecting risk conditions, not a single-variable check.

### 3.2 The GerontoNet Risk Score — a weighted linear sum

GerontoNet evaluates **chronic** fragility — comorbidities, medication burden, and prior ADR history — using a real, published, weighted point system (Onder et al., *Arch Intern Med*, 2010). Unlike ADATIP, this is not a simple count: each variable carries its own explicit point weight, and the final score is a weighted sum:

| Variable | Condition | Point weight |
|---|---|---|
| Comorbid conditions | `≥ 4 comorbid conditions` present | **+1** |
| Heart failure | present | **+1** |
| Liver disease | present | **+1** |
| Renal failure | present | **+1** |
| Concurrent drug count | `5 ≤ num_drugs ≤ 7` | **+1** |
| Concurrent drug count | `num_drugs ≥ 8` | **+4** (this band replaces, not adds to, the 5–7 band) |
| Previous ADR history | present | **+2** |

The total score is bounded: `0 ≤ total_score ≤ 10` (the maximum obtains when every variable above is simultaneously true and drug count is ≥ 8: 1+1+1+1+4+2 = 10).

**The threshold, stated explicitly:** `risk_category = "High Risk"` **if and only if** `total_score ≥ 4`; otherwise `risk_category = "Low Risk"`. Crossing this threshold sets a single boolean output — `high_baseline_adr_risk = True` — which is the one value that leaves Layer 2 and enters Layer 3. Below the threshold, the same variable is `False`.

**A worked example that is worth stating on stage, because it demonstrates the model is not naive:** *Previous ADR history* is worth 2 points — the single largest individual weight in the table — but 2 points alone does **not** cross the ≥ 4 threshold. A patient with a prior ADR and nothing else scores `total_score = 2`, which resolves to `"Low Risk"`. The score only crosses into `"High Risk"` once a *second* contributing condition is also present (for example, Previous ADR history + Heart failure = 2 + 1 = 3, still below threshold; + Liver disease as well = 2 + 1 + 1 = 4, now at threshold). This is the real, validated mathematics of the instrument, not a shortcut — a single strong predictor is deliberately insufficient on its own.

The composite Layer 2 output, `high_baseline_adr_risk`, is set to `True` if **either** ADATIP's `count(V) ≥ 2` **or** GerontoNet's `total_score ≥ 4` holds (a small third condition — both Allergy history and Family history present together — also contributes, using the same ≥2-of-2 logic as ADATIP, since no published weighting exists for that pair). This is a **logical OR** across three independent sub-checks, not a single formula.

---

## 4. Deep Dive: Layer 3 — PGx Triage & Decision Matrix

Layer 3 answers the actual business question: should a genetic test be ordered for *this drug*, for *this patient*, *now*? It is computed as a deterministic function of two independent inputs:

```
Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)
```

### 4.1 PGx Actionability — a categorical prior per drug

This is a fixed, per-drug classification anchored to CPIC guidance, independent of any individual patient:

| Actionability state | Meaning | Applies to |
|---|---|---|
| `NOT_MODELED` | No validated genotype-drug relationship is encoded for this drug. | Any drug outside the current MVP scope (e.g. Ibuprofen) |
| `VALIDATED_LOW_INTRINSIC` | A validated relationship exists, but an established non-genetic monitoring pathway (routine blood testing) already achieves comparable safety in most cases. | Warfarin |
| `VALIDATED_HIGH_INTRINSIC` | A validated relationship whose evidence weight is strong enough, on its own, to justify testing regardless of anything else about the patient. | Clopidogrel, Tacrolimus |

### 4.2 Patient-Specific Clinical Context — a boolean state

This is a per-encounter boolean: does a condition specific to *this drug's own* biological pathway exist for *this* patient, right now?

- `NEUTRAL` — no such condition detected.
- `PATHWAY_INTERSECTING` — a severe drug-drug interaction, or an extreme lab value, that directly implicates the drug's own mechanism (for example, an abnormal INR sitting directly on Warfarin's own anticoagulation pathway, or a severe CYP-mediated drug interaction for Clopidogrel).

### 4.3 The Decision Matrix

The two inputs above resolve, via a fixed lookup table (a **state machine**, not an additive score), to exactly one of three outputs:

| Actionability | Context | → Testing Priority |
|---|---|---|
| `VALIDATED_HIGH_INTRINSIC` | `NEUTRAL` | 🔴 **HIGH PRIORITY** |
| `VALIDATED_HIGH_INTRINSIC` | `PATHWAY_INTERSECTING` | 🔴 **HIGH PRIORITY** |
| `VALIDATED_LOW_INTRINSIC` | `NEUTRAL` | 🟡 **CONSIDER** |
| `VALIDATED_LOW_INTRINSIC` | `PATHWAY_INTERSECTING` | 🔴 **HIGH PRIORITY** |
| `NOT_MODELED` | (any) | 🟢 **LOW PRIORITY** |

Reading this table directly: a drug with `VALIDATED_HIGH_INTRINSIC` actionability (Clopidogrel, Tacrolimus) is **always** HIGH PRIORITY — its row is HIGH regardless of context. A drug with `VALIDATED_LOW_INTRINSIC` actionability (Warfarin) starts at CONSIDER and only moves to HIGH PRIORITY when a pathway-intersecting condition is actually present. An unmodeled drug is always LOW PRIORITY.

### 4.4 The Clinical Safeguard — why Layer 2 cannot force the outcome

This is the single most important design decision in PRISM-AIIMS, and the one most worth stating carefully to a technical judge: **`high_baseline_adr_risk` (Layer 2's output) is never an input to the Context variable above.** It is treated as a statistically **orthogonal covariate** — a value that is correlated with general adverse-event probability, but *independent* of whether this particular drug's pathway is implicated for this patient.

Concretely: even a patient scoring the maximum possible GerontoNet risk, or tripping every ADATIP predictor, being prescribed Warfarin with entirely normal labs and no drug interaction, will still resolve to `Context = NEUTRAL`, and the decision matrix still outputs **CONSIDER**, not HIGH PRIORITY. The elevated risk is never discarded, however — it is surfaced as a separate, explicit field:

```
contextual_modifier = {
    "high_baseline_adr_risk": True,
    "state_transition_applied": False,   # always False, by construction
    "note": "..."
}
```

`state_transition_applied` is hard-coded to `False` for this covariate — it is architecturally incapable of moving the state, no matter how extreme the underlying score. For Warfarin specifically, a high baseline ADR risk is additionally surfaced as a strong, dedicated clinical warning displayed alongside the CONSIDER output — so the elevated risk is visible and actionable for the clinician, without misrepresenting it as a reason a genetic test is now mandatory. The validated drug-gene relationship remains the primary determinant of Testing Priority at all times; general clinical fragility is a *modifier of context*, never a *substitute* for genomic actionability.

---

## 5. Deep Dive: The Population-Aware Module (GenomeIndia)

Below the Layer 3 output, the dashboard displays a panel titled **"Population-Aware PGx Context (GenomeIndia Prototype)"**. Its purpose is to illustrate a third, independent axis of context: population-level allele-frequency data.

**The core statistical idea:** an individual's genotype is unknown until a test is actually run. Before that test exists, the best available estimate of the probability that a given patient carries an actionable variant is the **prior probability** — the base rate of that variant within a reference population. A population genomics initiative like GenomeIndia can, in principle, supply an India-specific prior that differs from a global reference cohort's prior, because allele frequencies for genes like *CYP2C19*, *CYP3A5*, and *VKORC1* are known to vary meaningfully by ancestry.

The panel shows this explicitly as a side-by-side prior-probability comparison for each modeled drug's actionable variant class:

| Drug | Variant class | Mock GenomeIndia prior | Mock global reference prior |
|---|---|---|---|
| Clopidogrel | CYP2C19 loss-of-function alleles (*2 / *3) | 35% | 30% |
| Tacrolimus | CYP3A5 expresser allele (*1) | 55% | 35% |
| Warfarin | VKORC1 sensitivity allele (-1639A) | 72% | 40% |

**Every number in that table is an illustrative placeholder** — the panel states outright, in a caption, that it is not sourced from an actual GenomeIndia data release. This is a prototype demonstrating a computational concept, not a live data integration, and the guide must never be presented as though it were.

**The safeguard disclaimer, shown verbatim on the panel at all times:**

> *"Population-level frequencies act as contextual modifiers for prior probability; they cannot determine an individual's genotype and do not replace clinical prescribing guidelines."*

This is a Bayesian distinction worth making explicit on stage: a population prior shifts your *expectation* before you have evidence about a specific individual; it is never a *substitute* for that individual's own test result, and it never feeds back into the Layer 3 decision matrix computation itself — it is presented purely as adjunct context alongside the triage output.

---

## 6. Presentation Demo Script

All three demos run on the **Clinical Dashboard** tab. Note for the presenter: the dashboard renders HIGH PRIORITY / CONSIDER / LOW PRIORITY as color-coded panels (red / amber / green) with the state name spelled out in text — that is the on-screen equivalent of the 🔴 🟡 🟢 shorthand used in this guide and in casual conversation with the judges.

### Demo 1 — The Definitive Case (Clopidogrel)

**What you are proving:** a `VALIDATED_HIGH_INTRINSIC` drug resolves to HIGH PRIORITY unconditionally, and the drug-drug interaction check still fires independently on top of that.

1. Under **Pharmacogenomic (PGx) Triage**, set **Drug Requested** to **Clopidogrel**.
2. In **Current Medications**, type **Omeprazole**.
3. Select **"None of the above (Run Triage)"**, then click **Run Triage**.

**What to say:** "Clopidogrel's CYP2C19 relationship is classified `VALIDATED_HIGH_INTRINSIC` under CPIC guidance — look at the decision matrix: that row is HIGH PRIORITY no matter what the context is. But watch the Drug-Drug Interaction section below the rationale — the system has independently detected that Omeprazole is a documented CYP2C19 inhibitor and flagged it as its own finding. Two independent checks, agreeing, on one screen."

### Demo 2 — The Modifier Case (Warfarin, healthy inputs)

**What you are proving:** a `VALIDATED_LOW_INTRINSIC` drug does not over-alert when no pathway-intersecting context exists.

1. Set **Drug Requested** to **Warfarin**. Leave **Current Medications** blank.
2. Select **"None of the above (Run Triage)"**.
3. Leave all four lab values at their defaults (eGFR 90, ALT/AST 25, Platelets 250, PT/INR 1.0 — all inside normal range).
4. Click **Run Triage**.

**What to say:** "With normal labs and no drug interaction, Warfarin's Context variable evaluates to NEUTRAL. Look up the decision matrix: `VALIDATED_LOW_INTRINSIC` × `NEUTRAL` resolves to CONSIDER — not HIGH PRIORITY. That's correct: routine INR monitoring already manages most Warfarin patients safely, so the system isn't recommending an unnecessary test."

### Demo 3 — The Escalation Case (Warfarin + extreme clinical vulnerability)

**What you are proving:** this is the centerpiece. It demonstrates the Clinical Safeguard from Section 4.4 directly — that even an extreme Layer 2 vulnerability score does **not** override Layer 3's decision matrix, exactly as the architecture requires.

1. Under **Clinical Risk Assessment → GerontoNet Risk Score**, set **Number of concurrent drugs** to **8**.
2. Under **General Clinical History**, check **Previous ADR history**.
3. Point at the **GerontoNet ADR Risk Score** metric: it now reads **6 / 10**, and the **GerontoNet Risk Category** reads **High Risk**. Do the arithmetic out loud: `≥8 drugs = +4`, `Previous ADR history = +2`, total `= 6`, which is above the threshold of 4.
4. Confirm **Drug Requested** is still **Warfarin**, labs are still at their normal defaults, and **Current Medications** is still blank. Click **Run Triage** again.

**What to say:** "Now watch closely — this is the safeguard, not a bug. The GerontoNet score just hit 6 out of 10, well over the High Risk threshold of 4, and `high_baseline_adr_risk` is now `True`. But look at the output: it is *still* CONSIDER, not HIGH PRIORITY. Why? Because nothing about Warfarin's own biological pathway has changed — the labs are normal, there's no drug interaction. What *has* changed is that a bold clinical warning has now appeared, explicitly telling the clinician this patient carries elevated baseline risk and needs closer monitoring — the system surfaces the danger without misattributing it to Warfarin's genetics specifically. That's the architecture doing exactly what it's designed to do: general vulnerability is a contextual modifier, never a substitute for the validated drug-gene relationship."

---

*End of guide. Every field name, threshold, and button label above matches the running dashboard exactly — keep this document open on a second screen during the live walkthrough.*
