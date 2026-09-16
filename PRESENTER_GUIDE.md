# PRISM-AIIMS — Presenter's Guide

*A plain-English handover for anyone pitching PRISM-AIIMS on stage — no coding background required.*

---

## 1. The Elevator Pitch

**PRISM-AIIMS is a Cost-Conscious Pre-Test Triage and Decision Support tool.**

In simple terms: before a hospital spends time and money on a genetic test, PRISM-AIIMS first checks how much that test would actually matter for this specific patient.

Genetic tests are expensive, slow, and not always necessary. Right now, many hospitals either order them for everyone (wasteful) or skip them entirely (risky). PRISM-AIIMS closes that gap by calculating the patient's risk **first**, using information doctors already have on hand — age, basic lab results, medical history — and only then telling the clinician whether a genetic test is worth ordering for the drug in question.

**The one-line version:** *"PRISM-AIIMS stops hospitals from guessing — it calculates a patient's risk first, so genetic testing money is spent only where it will actually change the treatment decision."*

---

## 2. How the Background Logic Works (The 3 Layers)

Think of PRISM-AIIMS as a **decision tree with three checkpoints**, each one narrowing the question a little further. A patient's information flows through all three, one after another, before the tool gives its final recommendation.

### Layer 1 — Patient Baseline & Vitals *(the foundation)*

This is where the patient's basic health picture is entered: name, age, weight, and vital signs (pulse, blood pressure, temperature, and so on).

Where it gets clinically useful is the **exact lab numbers** — specifically:

- **eGFR** — a standard measurement of how well the kidneys are filtering.
- **LFTs (Liver Function Tests)** — standard blood markers that show how the liver is coping.

PRISM-AIIMS doesn't guess at organ health — it reads the actual number the lab reported and compares it to a recognized medical threshold. If a number falls outside the normal range, the system flags it plainly as **"this number is abnormal and needs a doctor's judgment"** — it never jumps ahead and declares a disease on its own. That distinction matters: a lab abnormality is a fact; a diagnosis is a doctor's call.

### Layer 2 — Clinical Risk Assessment *(the vulnerability calculator)*

This layer answers one question: **"How fragile is this patient overall, independent of any drug?"**

It does this with simple addition, using two respected, published medical scoring systems side by side:

- **The ADATIP 9-Predictor** looks at *acute* danger signs — essentially, "what brought this patient into the hospital today?" Things like fainting (syncope), arriving with a bleeding or breathing complaint, or already being on blood thinners, diuretics, or heart medications.
- **The GerontoNet Score** looks at *chronic* fragility — the patient's age, how many medications they're already taking, whether they've had a bad drug reaction before, and whether they have ongoing heart, liver, or kidney conditions.

Each risk factor present adds points. Once the combined score crosses a set threshold, PRISM-AIIMS flags the patient as **"High Baseline ADR Risk"** (ADR = Adverse Drug Reaction) — meaning this patient, generally speaking, is more likely to have a bad reaction to *any* medication, not just the one being considered.

This flag is a **vulnerability score**, not a verdict — it gets carried forward into the next layer, where it's weighed against the specific drug in question.

### Layer 3 — PGx Triage *(the final decision tree)*

This is where everything comes together. Layer 3 takes:

- the **drug being requested**,
- any **dangerous combinations** with medications the patient is already on, and
- the **risk flags** raised in Layers 1 and 2,

and runs them through a strict decision tree that outputs exactly one of three recommendations:

- 🔴 **HIGH PRIORITY** — a genetic test is strongly recommended before prescribing.
- 🟡 **CONSIDER** — genetic information could help, but routine monitoring is often enough on its own.
- 🟢 **LOW PRIORITY** — a genetic test is unlikely to change what the doctor would do anyway.

For some drugs, a "High Baseline ADR Risk" flag from Layer 2 is enough, on its own, to push the recommendation up a level — from CONSIDER to HIGH PRIORITY. That escalation is exactly what Demo 3 below shows in action.

---

## 3. The Evidence (What the Judges Want to Know)

Every number and rule inside PRISM-AIIMS is borrowed from a real, published medical source — nothing is invented or guessed. If a judge asks "how do you know these thresholds are correct?", here is the list to point to:

- **KDIGO** — the internationally recognized standard for staging kidney (renal) health.
- **NFI / CDSCO** — the National Formulary of India / Central Drugs Standard Control Organisation, used for tracking liver (hepatic) abnormalities.
- **FDA** — the U.S. Food and Drug Administration, used as the source for known dangerous drug-drug interactions.
- **GerontoNet** — a validated, published scoring system (a statistical regression model) built specifically to predict adverse drug reaction risk in older patients.
- **CPIC** — the Clinical Pharmacogenetics Implementation Consortium, the internationally recognized authority whose guidelines drive the final "what does this DNA result mean for dosing" rules.

**The pitch line for this section:** *"We didn't write our own rulebook. Every threshold in PRISM-AIIMS traces back to a named, published guideline that any clinician in the room would already recognize."*

---

## 4. Step-by-Step Demo Guide (How to Present It on Stage)

All three demos happen on the **Clinical Dashboard** tab. A quick note before you start: the app shows HIGH PRIORITY / CONSIDER / LOW PRIORITY as color-coded panels (red, amber, green) with the recommendation spelled out in the panel itself — that's the on-screen version of the 🔴 🟡 🟢 shorthand used in this guide.

### Demo 1 — The "Always Red" Case *(severe interaction + mandatory test)*

**What you're proving:** some drugs are simply too risky to guess on — and the system independently catches dangerous combinations on top of that.

1. In the **Pharmacogenomic (PGx) Triage** section, set **Drug Requested** to **Clopidogrel**.
2. In **Current Medications**, type **Omeprazole**.
3. Select **"None of the above (Run Triage)"** under Diagnostic Data Available.
4. Click **Run Triage**.

**What to say:** "Clopidogrel always comes back HIGH PRIORITY — CPIC guidance treats its genetic factor as too important to skip. But watch — the system has *also* independently caught that Omeprazole is a known severe interaction (an FDA-flagged combination) and calls it out as its own warning. Two separate safety checks, one screen."

### Demo 2 — The "Standard" Case *(routine monitoring is enough)*

**What you're proving:** PRISM-AIIMS doesn't over-alert — it only escalates when it's actually warranted.

1. Set **Drug Requested** to **Warfarin**.
2. Leave **Current Medications** blank.
3. Select **"None of the above (Run Triage)"**.
4. Leave the lab values at their normal defaults (eGFR 90, ALT/AST 25, Platelets 250, PT/INR 1.0).
5. Click **Run Triage**.

**What to say:** "For a healthy patient on Warfarin with nothing unusual in their labs or history, the system recommends CONSIDER, not HIGH PRIORITY. That's deliberate — routine blood testing (INR monitoring) is usually enough to manage Warfarin safely, so we don't push for an expensive genetic test the patient doesn't need."

### Demo 3 — The "Escalation" Case *(Layer 2 changes the outcome)*

**What you're proving:** this is the centerpiece — showing the scoring system in Layer 2 actively changing the final recommendation in Layer 3.

1. First, go up to **Patient Baseline & Vitals** and set **Age** to **70**. *(This step is essential — the escalation rule you're about to demonstrate specifically applies to older patients, matching the GerontoNet score's own focus on elderly fragility.)*
2. Scroll to **Clinical Risk Assessment**. Under the **GerontoNet Risk Score** panel, set **Number of concurrent drugs** to **8**.
3. Just below, in **General Clinical History**, check **Previous ADR history**.
4. Point out the **GerontoNet ADR Risk Score** panel — it now shows a score of **6 out of 10**, and the risk category has flipped to **High Risk**.
5. Scroll down to **Pharmacogenomic (PGx) Triage**, set **Drug Requested** to **Warfarin** (if it isn't already), select **"None of the above (Run Triage)"**, and click **Run Triage**.

**What to say:** "Watch what just happened. With the same drug, Warfarin, and the same normal lab results as Demo 2 — the only thing that changed is the patient's background risk profile. Eight or more medications is worth 4 points on the GerontoNet scale, a past bad reaction adds 2 more — that's 6 points, comfortably over our threshold of 4. Because this patient is also elderly, the system now says HIGH PRIORITY instead of CONSIDER. That's the whole point of PRISM-AIIMS: the recommendation isn't fixed to the drug alone, it adjusts to the real patient in front of the doctor."

---

*End of guide. Keep this document open on a second screen during the live walkthrough — every field name and button label above matches the dashboard exactly.*
