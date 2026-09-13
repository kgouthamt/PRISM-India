"""Deterministic pharmacogenomic rule engine based on CPIC guidelines."""

DRUG_GENE_MAP = {
    "clopidogrel": "CYP2C19",
    "carbamazepine": "HLA-B*15:02",
    "allopurinol": "HLA-B*58:01",
    "abacavir": "HLA-B*57:01",
}


def _result(risk, reason, recommendation=None, gene=None):
    return {"risk": risk, "reason": reason, "recommendation": recommendation, "gene": gene}


def evaluate_prescription(drug: str, genotype: str) -> dict:
    """Evaluate a requested drug against a patient's genotype/allele status.

    `genotype` is the CYP2C19 diplotype (e.g. "*1/*2") for clopidogrel, or the
    HLA allele status ("Positive"/"Negative") for the other three drugs.
    """
    drug_key = (drug or "").strip().lower()
    genotype_key = (genotype or "").strip()
    gene = DRUG_GENE_MAP.get(drug_key)

    if gene is None:
        return _result(
            "UNKNOWN",
            "No actionable guidance -> No automated prescribing recommendation",
        )

    if drug_key == "clopidogrel":
        if "*2" in genotype_key or "*3" in genotype_key:
            return _result(
                "HIGH",
                "Reduced clopidogrel activation (CYP2C19 loss-of-function allele)",
                "Recommend alternative antiplatelet: Prasugrel",
                gene,
            )
        if genotype_key == "*1/*1":
            return _result("SAFE", "Normal CYP2C19 metabolizer; standard clopidogrel dosing expected to be effective", gene=gene)
        return _result(
            "UNKNOWN",
            "No actionable guidance -> No automated prescribing recommendation",
            gene=gene,
        )

    # Remaining drugs are governed by a binary HLA allele carrier status.
    status = genotype_key.lower()
    if status == "positive":
        if drug_key == "carbamazepine":
            return _result(
                "HIGH",
                "Risk of Stevens-Johnson Syndrome / toxic epidermal necrolysis",
                "Avoid carbamazepine",
                gene,
            )
        if drug_key == "allopurinol":
            return _result(
                "HIGH",
                "Risk of severe cutaneous adverse reactions (SJS/TEN, DRESS)",
                "Recommend alternative: Febuxostat",
                gene,
            )
        if drug_key == "abacavir":
            return _result(
                "HIGH",
                "Risk of abacavir hypersensitivity reaction",
                "Avoid abacavir",
                gene,
            )

    if status == "negative" or genotype_key == "*1/*1":
        return _result("SAFE", f"{gene} allele not detected; no CPIC contraindication for {drug.title()}", gene=gene)

    return _result(
        "UNKNOWN",
        "No actionable guidance -> No automated prescribing recommendation",
        gene=gene,
    )
