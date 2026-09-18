"""Pharmacogenomic (PGx) Testing-Priority Triage for the PRISM-AIIMS
pre-test decision pipeline (Layer 3: Pharmacogenomics, Path B).

Combines Layer 1 (engine.clinical: lab-abnormality state assessment) and
the DDI engine (engine.ddi: drug-drug interaction lookup) outputs into a
single pre-test recommendation: is a pharmacogenomic test for this drug
actually likely to change management, *before* any genetic result exists?
This is deliberately independent of engine.rules, which handles the
downstream genotype/phenotype -> dosing decision *after* a PGx test result
already exists (Layer 3, Path A) -- this module answers "should we test at
all," engine.rules answers "given the test result, what do we do."

CONCEPTUAL MODEL

    Testing Priority = f(PGx Actionability, Patient-Specific Clinical Context)

`PGx Actionability` is a categorical prior describing how strong and
well-validated a drug's genotype-to-management relationship is (per CPIC
and related guidance), independent of any single patient:

    ACTIONABILITY_NOT_MODELED    -- no validated relationship is encoded
                                     for this drug in the current scope.
    ACTIONABILITY_VALIDATED_LOW  -- a validated relationship exists, but an
                                     established non-genetic monitoring
                                     pathway (e.g. routine INR titration for
                                     Warfarin) already achieves comparable
                                     safety in the typical case, so the
                                     relationship alone is not sufficient to
                                     maximize testing priority.
    ACTIONABILITY_VALIDATED_HIGH -- a validated relationship whose intrinsic
                                     weight already saturates the decision
                                     matrix on its own (efficacy-critical or
                                     narrow-therapeutic-index), independent
                                     of clinical context.

`Patient-Specific Clinical Context` is a boolean state describing whether a
condition specific to *this drug's own* metabolic or pharmacodynamic
pathway is present for *this* patient. Every lab input into this state is a
raw numeric reading (or `None` for missing data) that this module passes
directly into engine.clinical's `assess_*` functions, which evaluate it
against a named conditional threshold to resolve a three-valued
Abnormal/Normal/Unknown status; this module itself never performs the
threshold comparison, it only reads the resolved status string back.

    CONTEXT_NEUTRAL              -- no pathway-specific abnormal state is
                                     flagged.
    CONTEXT_PATHWAY_INTERSECTING -- a severe drug-drug interaction, or an
                                     abnormal-flagged lab state, directly
                                     implicating this drug's own pathway is
                                     present (e.g. a severe CYP-mediated
                                     interaction, or an abnormal-flagged
                                     coagulation state for Warfarin).

The two inputs are resolved against a fixed decision matrix
(`_PRIORITY_STATE_MATRIX`) to a single output state -- this is an explicit
state machine, not an additive score, so the same (actionability, context)
pair always resolves to the same priority state.

Baseline ADR risk from Layer 2 (`engine.clinical.calculate_adr_risk`) is
modeled as an orthogonal covariate, not as a value of Clinical Context: it
raises the prior probability of an adverse event *in general*, but it is
statistically independent of whether *this drug's* specific pathway is
implicated for *this* patient. Consequently it can never place Clinical
Context into CONTEXT_PATHWAY_INTERSECTING, and it never transitions the
priority state on its own. The covariate is still surfaced, structurally
separate from `triage`/`rationale`, as `contextual_modifier` -- see
`_contextual_modifier_output`.

Output triage states, and their downstream projection onto CPIC's own
pre-test testing vocabulary (see `resolve_cpic_testing_recommendation`):
    HIGH PRIORITY   -- a validated actionable relationship exists AND
                       patient/drug context makes genotype information
                       particularly relevant right now.        -> Required
    CONSIDER        -- actionable PGx information may be useful, but
                       clinical context does not establish a strong need
                       for immediate testing.                  -> Recommended
    LOW PRIORITY    -- no sufficiently actionable PGx relationship is
                       identified for the current decision, or genotype is
                       unlikely to alter management.            -> Not Indicated

DECOUPLED MODULE: mock GenomeIndia population context

`genomeindia_population_priority`, below, is a second, entirely separate
isolated execution context: an ethnicity-keyed lookup returning a mock
population-level allele-frequency priority (High/Medium/Low). Its output is
a pure function of ethnicity alone -- an independent variable in the
strict probabilistic sense. It is never read by `_resolve_priority_state`,
never combined or multiplied with any Layer 1 or Layer 2 output, and never
appears inside the `triage_pgx_actionability` return value; a caller (the
UI layer) invokes it separately and renders it as a structurally isolated
result.
"""

from engine.clinical import (
    ALT_AST_THRESHOLD,
    EGFR_THRESHOLD,
    assess_age_weight_context,
    assess_bleeding_risk_labs,
    assess_hepatic_function,
    assess_renal_function,
)
from engine.ddi import check_drug_interactions

TRIAGE_HIGH = "HIGH PRIORITY"
TRIAGE_CONSIDER = "CONSIDER"
TRIAGE_LOW = "LOW PRIORITY"

# --- PGx Actionability priors ----------------------------------------------
ACTIONABILITY_NOT_MODELED = "NOT_MODELED"
ACTIONABILITY_VALIDATED_LOW = "VALIDATED_LOW_INTRINSIC"
ACTIONABILITY_VALIDATED_HIGH = "VALIDATED_HIGH_INTRINSIC"

# --- Patient-Specific Clinical Context states ------------------------------
CONTEXT_NEUTRAL = "NEUTRAL"
CONTEXT_PATHWAY_INTERSECTING = "PATHWAY_INTERSECTING"

# Testing Priority = f(Actionability, Context): a deterministic state
# machine, not an additive score. Every (actionability, context) pair that
# is reachable in this module has an explicit row; an unmodeled drug is
# handled separately in _resolve_priority_state, below the matrix.
_PRIORITY_STATE_MATRIX = {
    (ACTIONABILITY_VALIDATED_HIGH, CONTEXT_NEUTRAL): TRIAGE_HIGH,
    (ACTIONABILITY_VALIDATED_HIGH, CONTEXT_PATHWAY_INTERSECTING): TRIAGE_HIGH,
    (ACTIONABILITY_VALIDATED_LOW, CONTEXT_NEUTRAL): TRIAGE_CONSIDER,
    (ACTIONABILITY_VALIDATED_LOW, CONTEXT_PATHWAY_INTERSECTING): TRIAGE_HIGH,
}

# --- CPIC pre-test testing recommendation (Layer 3, Path B, first output) --
# A deterministic projection of the already-resolved Testing Priority state
# onto CPIC's own two-valued pre-test vocabulary (Required / Recommended),
# extended with a third state, Not Indicated, for LOW PRIORITY -- a case
# CPIC guidance itself does not separately name. This carries no
# information the state machine above did not already produce; it is a
# relabeling, not a second independent computation.
CPIC_TESTING_REQUIRED = "Required"
CPIC_TESTING_RECOMMENDED = "Recommended"
CPIC_TESTING_NOT_INDICATED = "Not Indicated"

_CPIC_TESTING_STATE_MAP = {
    TRIAGE_HIGH: CPIC_TESTING_REQUIRED,
    TRIAGE_CONSIDER: CPIC_TESTING_RECOMMENDED,
    TRIAGE_LOW: CPIC_TESTING_NOT_INDICATED,
}

# --- Mock GenomeIndia population context (Layer 3, Path B, second output) --
# Illustrative placeholder priorities only -- NOT derived from an actual
# GenomeIndia data release. Keyed by ethnicity rather than by drug: each
# entry models, for demonstration purposes only, a broad pre-test priority
# category a population-level allele-frequency prior might suggest for a
# given population group, independent of any specific drug.
GENOMEINDIA_PRIORITY_HIGH = "High Priority"
GENOMEINDIA_PRIORITY_MEDIUM = "Medium Priority"
GENOMEINDIA_PRIORITY_LOW = "Low Priority"

ETHNICITY_OPTIONS = [
    "Indo-Aryan",
    "Dravidian",
    "Tibeto-Burman",
    "Austroasiatic",
    "Other / Unknown",
]

GENOMEINDIA_ETHNICITY_PRIORS = {
    "Indo-Aryan": GENOMEINDIA_PRIORITY_HIGH,
    "Dravidian": GENOMEINDIA_PRIORITY_MEDIUM,
    "Tibeto-Burman": GENOMEINDIA_PRIORITY_MEDIUM,
    "Austroasiatic": GENOMEINDIA_PRIORITY_LOW,
    "Other / Unknown": GENOMEINDIA_PRIORITY_LOW,
}


def resolve_cpic_testing_recommendation(triage_state: str) -> str:
    """Project a Testing Priority state onto CPIC's Required/Recommended/
    Not Indicated vocabulary. See the module docstring's state-mapping
    table. An unrecognized state defaults to Not Indicated rather than
    fabricating a stronger recommendation than the state machine resolved.
    """
    return _CPIC_TESTING_STATE_MAP.get(triage_state, CPIC_TESTING_NOT_INDICATED)


def genomeindia_population_priority(ethnicity: str) -> dict:
    """A mock, ethnicity-keyed GenomeIndia population allele-frequency
    lookup -- an isolated execution context whose return value is a
    function of `ethnicity` alone.

    CRITICAL DECOUPLING: this output must never be integrated, multiplied,
    or combined with Layer 1 (lab-abnormality flags) or Layer 2 (baseline
    ADR risk) outputs, and must never be passed into
    `_resolve_priority_state` or read by `triage_pgx_actionability`. It
    serves as an independent, population-based recommendation only; no
    function in this module consumes its return value.

    Returns {"ethnicity", "genomeindia_priority", "source"}. Every priority
    value is illustrative only -- not sourced from an actual GenomeIndia
    data release, and never a substitute for an individual genotype result.
    """
    priority = GENOMEINDIA_ETHNICITY_PRIORS.get(ethnicity, GENOMEINDIA_PRIORITY_LOW)
    return {
        "ethnicity": ethnicity,
        "genomeindia_priority": priority,
        "source": "GenomeIndia (Prototype, illustrative only)",
    }


def _resolve_priority_state(actionability: str, context: str) -> str:
    """Look up Testing Priority = f(Actionability, Context) in the decision
    matrix above. ACTIONABILITY_NOT_MODELED has no row in the matrix (no
    context value can make an unmodeled relationship actionable) and
    resolves directly to LOW PRIORITY.
    """
    if actionability == ACTIONABILITY_NOT_MODELED:
        return TRIAGE_LOW
    return _PRIORITY_STATE_MATRIX[(actionability, context)]


def _contextual_modifier_output(high_baseline_adr_risk: bool, actionability: str) -> dict:
    """Report Layer 2's baseline ADR risk verdict as an orthogonal
    contextual modifier -- see the module docstring's covariate discussion.
    Kept structurally separate from `triage`/`rationale`/`warnings` so a
    general vulnerability signal is never conflated with this drug's own
    PGx actionability state. `state_transition_applied` is always False:
    by construction, this covariate never transitions the priority state.
    """
    if not high_baseline_adr_risk:
        note = "Baseline ADR risk is at its standard/reference state; no contextual modifier is active."
    elif actionability == ACTIONABILITY_VALIDATED_HIGH:
        note = (
            "Baseline ADR risk is elevated (an orthogonal Layer 2 covariate). "
            "This drug's actionability prior already saturates the decision "
            "matrix, so the priority state is unaffected; the elevated "
            "baseline risk is retained here as an auxiliary variable for "
            "post-test monitoring."
        )
    else:
        note = (
            "Baseline ADR risk is elevated (an orthogonal Layer 2 covariate). "
            "It raises the general prior probability of an adverse event, "
            "but is not itself a pathway-intersecting condition for this "
            "drug, so per the decision matrix it does not transition the "
            "priority state. It is surfaced as a clinical warning below for "
            "independent consideration."
        )

    return {
        "high_baseline_adr_risk": high_baseline_adr_risk,
        "state_transition_applied": False,
        "note": note,
    }


def _clopidogrel_triage(concurrent_medications, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("clopidogrel", concurrent_medications)
    actionability = ACTIONABILITY_VALIDATED_HIGH
    context = CONTEXT_PATHWAY_INTERSECTING if ddi_findings else CONTEXT_NEUTRAL
    triage = _resolve_priority_state(actionability, context)

    rationale = [
        "CYP2C19 poor/intermediate metabolizer status changes first-line "
        "antiplatelet selection and carries an FDA boxed warning for reduced "
        "effectiveness; this relationship's actionability prior saturates "
        "the decision matrix regardless of clinical context.",
    ]
    warnings = []
    if ddi_findings:
        warnings.append(
            "Concurrent CYP2C19-inhibiting medication further reduces expected "
            "clopidogrel activation, compounding any poor/intermediate "
            "metabolizer risk -- a pathway-intersecting condition."
        )
    return {
        "triage": triage,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [],
        "contextual_modifier": _contextual_modifier_output(high_baseline_adr_risk, actionability),
    }


def _tacrolimus_triage(concurrent_medications, egfr=None, alt_ast=None, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("tacrolimus", concurrent_medications)
    renal = assess_renal_function(egfr)
    hepatic = assess_hepatic_function(alt_ast)

    actionability = ACTIONABILITY_VALIDATED_HIGH
    pathway_intersecting = bool(ddi_findings) or renal["renal_function_status"] == "REDUCED" or hepatic["transaminase_status"] == "ELEVATED"
    context = CONTEXT_PATHWAY_INTERSECTING if pathway_intersecting else CONTEXT_NEUTRAL
    triage = _resolve_priority_state(actionability, context)

    rationale = [
        "CYP3A5 expresser status changes the tacrolimus starting dose by "
        "~1.5-2x per CPIC; this relationship's actionability prior sets the "
        "starting-dose baseline regardless of routine labs.",
    ]
    warnings = []
    if renal["renal_function_status"] == "REDUCED":
        warnings.append(
            renal["detail"] + " This is a pathway-intersecting condition; "
            "lab-driven therapeutic drug monitoring (TDM) is mandatory "
            "regardless of genotype."
        )
    if hepatic["transaminase_status"] == "ELEVATED":
        warnings.append(
            hepatic["detail"] + " This is a pathway-intersecting condition; "
            "lab-driven TDM and empirical dose caution are mandatory "
            "pending clinical correlation."
        )
    if ddi_findings:
        warnings.append(
            "Concurrent CYP3A4 modulator identified -- a pathway-intersecting "
            "condition; expect altered tacrolimus exposure regardless of "
            "genotype, so TDM is mandatory."
        )

    return {
        "triage": triage,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [renal, hepatic],
        "contextual_modifier": _contextual_modifier_output(high_baseline_adr_risk, actionability),
    }


def _warfarin_triage(concurrent_medications, platelets=None, pt_inr=None, high_baseline_adr_risk=False):
    ddi_findings = check_drug_interactions("warfarin", concurrent_medications)
    coagulation = assess_bleeding_risk_labs(platelets, pt_inr)

    severe_ddi = any(finding["severity"] == "MAJOR" for finding in ddi_findings)
    abnormal_coagulation = coagulation["coagulation_cbc_status"] == "ABNORMAL"
    pathway_intersecting = severe_ddi or abnormal_coagulation

    actionability = ACTIONABILITY_VALIDATED_LOW
    context = CONTEXT_PATHWAY_INTERSECTING if pathway_intersecting else CONTEXT_NEUTRAL
    triage = _resolve_priority_state(actionability, context)

    rationale = [
        "Routine PT/INR monitoring and dose titration already achieves "
        "comparable safety for most patients, so this relationship's "
        "actionability prior alone does not saturate the decision matrix "
        "-- a pathway-intersecting clinical context is required to raise "
        "testing priority.",
    ]
    warnings = []
    if abnormal_coagulation:
        warnings.append(
            "Abnormal coagulation/CBC parameters (" + "; ".join(coagulation["flags"]) +
            ") are a pathway-intersecting condition for warfarin's own "
            "anticoagulation mechanism and require clinical correlation."
        )
    if severe_ddi:
        warnings.append(
            "A severe drug-drug interaction is present (e.g. amiodarone or "
            "an NSAID), directly implicating warfarin's own metabolic/"
            "pharmacodynamic pathway; this independently elevates bleeding "
            "risk and warrants closer management regardless of genotype."
        )
    if high_baseline_adr_risk:
        warnings.append(
            "Baseline ADR risk is elevated for this patient (an orthogonal "
            "Layer 2 covariate). This raises the general prior probability "
            "of an adverse event but is not, by itself, a pathway-"
            "intersecting condition for warfarin's CYP2C9/VKORC1 "
            "relationship, so the testing-priority state remains "
            "unchanged; increased vigilance and closer monitoring are "
            "still clinically warranted."
        )

    return {
        "triage": triage,
        "rationale": rationale,
        "warnings": warnings,
        "ddi_findings": ddi_findings,
        "clinical_findings": [coagulation],
        "contextual_modifier": _contextual_modifier_output(high_baseline_adr_risk, actionability),
    }


def triage_pgx_actionability(
    drug: str,
    concurrent_medications: list = None,
    *,
    age: float = None,
    weight: float = None,
    egfr: float = None,
    alt_ast: float = None,
    platelets: float = None,
    pt_inr: float = None,
    high_baseline_adr_risk: bool = False,
) -> dict:
    """Pre-test triage: should a PGx test even be ordered for this drug?

    Implements Testing Priority = f(PGx Actionability, Patient-Specific
    Clinical Context) -- see the module docstring for the full decision-
    matrix definition. Every clinical-context lab parameter (`egfr`,
    `alt_ast`, `platelets`, `pt_inr`, each in its stated unit, or `None`
    for missing data) is a raw numeric reading, passed straight into
    engine.clinical's `assess_*` functions, which evaluate it against a
    named conditional threshold; this function never performs that
    comparison itself, it only reads back the resolved Abnormal/Normal/
    Unknown status. `age` (years) and `weight` (kg) remain objective
    numeric inputs used only for the pediatric/low-weight dosing context,
    unrelated to the lab-abnormality state machine. `high_baseline_adr_risk`
    is the single boolean verdict
    already computed by Layer 2's engine.clinical.calculate_adr_risk() --
    this function never receives or reasons about the raw subjective
    predictor checkboxes behind it, and that covariate never transitions
    the priority state on its own for any drug (see
    `_contextual_modifier_output`).

    Returns {"triage", "rationale", "warnings", "ddi_findings",
    "clinical_findings", "contextual_modifier", "cpic_testing_recommendation"}.
    `warnings` (distinct from `rationale`) carries strong, context-driven
    safety flags -- e.g. Tacrolimus's mandatory-TDM warning on an
    abnormal-flagged renal/hepatic state, or Warfarin's elevated-baseline-
    ADR-risk warning that does not itself change the priority state.
    `contextual_modifier` is kept structurally separate from
    `triage`/`rationale`: it reports the patient's baseline ADR risk status
    without conflating general vulnerability with this drug's own PGx
    actionability state. `cpic_testing_recommendation` is the deterministic
    Required/Recommended/Not Indicated projection of `triage` (see
    `resolve_cpic_testing_recommendation`). A drug outside this triage's
    MVP scope (Clopidogrel, Tacrolimus, Warfarin) resolves to
    ACTIONABILITY_NOT_MODELED and returns LOW PRIORITY with an explanatory
    rationale, rather than a fabricated assessment. The mock GenomeIndia
    population-context lookup (`genomeindia_population_priority`) is
    deliberately absent from this return value -- it is an isolated
    execution context the caller invokes separately; see the module
    docstring's CRITICAL DECOUPLING note.
    """
    drug_key = (drug or "").strip().lower()
    age_weight = assess_age_weight_context(age, weight)

    if drug_key == "clopidogrel":
        result = _clopidogrel_triage(concurrent_medications, high_baseline_adr_risk=high_baseline_adr_risk)
    elif drug_key == "tacrolimus":
        result = _tacrolimus_triage(
            concurrent_medications, egfr=egfr, alt_ast=alt_ast,
            high_baseline_adr_risk=high_baseline_adr_risk,
        )
    elif drug_key == "warfarin":
        result = _warfarin_triage(
            concurrent_medications, platelets=platelets, pt_inr=pt_inr,
            high_baseline_adr_risk=high_baseline_adr_risk,
        )
    else:
        actionability = ACTIONABILITY_NOT_MODELED
        result = {
            "triage": _resolve_priority_state(actionability, CONTEXT_NEUTRAL),
            "rationale": ["No validated PGx relationship is encoded for this drug in the current MVP scope."],
            "warnings": [],
            "ddi_findings": [],
            "clinical_findings": [],
            "contextual_modifier": _contextual_modifier_output(high_baseline_adr_risk, actionability),
        }

    if age_weight["flags"]:
        result["rationale"] = result["rationale"] + age_weight["flags"]
    result["clinical_findings"] = result["clinical_findings"] + [age_weight]
    result["cpic_testing_recommendation"] = resolve_cpic_testing_recommendation(result["triage"])
    return result
