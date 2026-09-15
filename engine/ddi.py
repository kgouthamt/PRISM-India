"""Tier 2 of the PRISM-India pre-test triage pipeline: drug-drug interactions.

A small, deterministic lookup of clinically significant interactions for the
three high-value drugs this prototype models (Clopidogrel, Warfarin,
Tacrolimus), anchored to FDA drug labeling for severe DDIs.
"""

FDA_LABEL_SOURCE = "FDA Drug Label"

DDI_TABLE = {
    "clopidogrel": [
        {
            "interacting_drugs": {"omeprazole", "esomeprazole"},
            "severity": "MAJOR",
            "mechanism": "Strong CYP2C19 inhibition reduces clopidogrel activation",
            "recommendation": "Avoid concomitant strong CYP2C19-inhibiting PPIs; "
                               "consider pantoprazole if acid suppression is required",
            "source": f"{FDA_LABEL_SOURCE} (Clopidogrel boxed warning)",
        },
        {
            "interacting_drugs": {"fluconazole", "fluoxetine", "fluvoxamine"},
            "severity": "MODERATE",
            "mechanism": "Moderate CYP2C19 inhibition may reduce clopidogrel activation",
            "recommendation": "Monitor for reduced antiplatelet effect; consider "
                               "an alternative agent if feasible",
            "source": FDA_LABEL_SOURCE,
        },
    ],
    "warfarin": [
        {
            "interacting_drugs": {"amiodarone"},
            "severity": "MAJOR",
            "mechanism": "CYP2C9/3A4 inhibition significantly increases warfarin "
                          "exposure and INR",
            "recommendation": "Reduce warfarin dose empirically (~30-50%) and "
                               "increase INR monitoring frequency",
            "source": FDA_LABEL_SOURCE,
        },
        {
            "interacting_drugs": {"ibuprofen", "naproxen", "diclofenac", "aspirin"},
            "severity": "MAJOR",
            "mechanism": "Additive bleeding risk via antiplatelet effect and "
                          "GI mucosal injury",
            "recommendation": "Avoid concurrent NSAID use if possible; if "
                               "unavoidable, use gastroprotection and monitor "
                               "closely for bleeding",
            "source": FDA_LABEL_SOURCE,
        },
    ],
    "tacrolimus": [
        {
            "interacting_drugs": {"ketoconazole", "itraconazole", "fluconazole", "voriconazole"},
            "severity": "MAJOR",
            "mechanism": "Strong/moderate CYP3A4 inhibition markedly increases "
                          "tacrolimus exposure",
            "recommendation": "Empirically reduce tacrolimus dose and monitor "
                               "trough levels closely",
            "source": FDA_LABEL_SOURCE,
        },
        {
            "interacting_drugs": {"rifampin", "phenytoin", "carbamazepine"},
            "severity": "MAJOR",
            "mechanism": "CYP3A4 induction markedly decreases tacrolimus exposure",
            "recommendation": "Anticipate the need for a substantially higher "
                               "tacrolimus dose; monitor trough levels closely",
            "source": FDA_LABEL_SOURCE,
        },
    ],
}

# Every interacting drug across the table, for building a structured UI picklist.
ALL_INTERACTING_DRUGS = sorted(
    {drug for entries in DDI_TABLE.values() for entry in entries for drug in entry["interacting_drugs"]}
)


def check_drug_interactions(drug: str, concurrent_medications: list = None) -> list:
    """Return every known interaction between `drug` and the patient's
    concurrent medications (case-insensitive match).

    Each finding is a JSON-serializable dict: interacting_drugs and
    matched_medications are plain lists, not sets.
    """
    drug_key = (drug or "").strip().lower()
    meds = {m.strip().lower() for m in (concurrent_medications or []) if m and m.strip()}

    findings = []
    for entry in DDI_TABLE.get(drug_key, []):
        matched = entry["interacting_drugs"] & meds
        if matched:
            findings.append({
                "interacting_drugs": sorted(entry["interacting_drugs"]),
                "matched_medications": sorted(matched),
                "severity": entry["severity"],
                "mechanism": entry["mechanism"],
                "recommendation": entry["recommendation"],
                "source": entry["source"],
            })
    return findings
