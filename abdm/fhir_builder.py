"""Build FHIR R4 bundles for PRISM-India decisions.

This is an FHIR R4 / ABDM-aligned interoperability prototype: it emits
standard FHIR resource shapes (DiagnosticReport, MedicationRequest) that a
FHIR-consuming EHR or ABDM Health Information Exchange can ingest, and it
carries India's digital health stack in mind, but it has not been certified
or validated against ABDM's formal FHIR profiles -- so it is not described as
"ABDM-compliant".
"""

import uuid
from datetime import datetime, timezone

_EXTENSION_BASE = "http://prism-india.org/fhir/StructureDefinition"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extension(name: str, value: str) -> dict:
    return {"url": f"{_EXTENSION_BASE}/{name}", "valueString": value}


def generate_fhir_bundle(
    patient_id: str,
    drug: str,
    test_type: str,
    test_result: str,
    recommendation_given: str,
    decision: str,
    override_reason: str = None,
    *,
    clinician_id: str = None,
    institution: str = None,
    encounter_id: str = None,
    assay_lab: str = None,
    specimen_date: str = None,
    result_verification_status: str = None,
    guideline_version: str = None,
    rule_version: str = None,
    evidence_source: str = None,
    software_version: str = None,
) -> dict:
    """Build a FHIR Bundle with a DiagnosticReport and a MedicationRequest.

    `test_type` is "Genotype" or "Phenotype" and `test_result` is the raw lab
    value behind the recommendation. `decision` is ACCEPTED or OVERRIDDEN,
    matching storage.audit_logger. The keyword-only arguments are structured
    clinical-encounter metadata and system provenance fields; each is placed
    on a native FHIR field where one exists (performer, requester, encounter,
    specimen) and as a local extension where FHIR has no matching field.
    """
    timestamp = _now_iso()
    patient_reference = {"reference": f"Patient/{patient_id}", "display": patient_id}
    practitioner_reference = (
        {"reference": f"Practitioner/{clinician_id}", "display": clinician_id}
        if clinician_id else None
    )

    diagnostic_report = {
        "resourceType": "DiagnosticReport",
        "id": f"diagnostic-report-{patient_id}",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "51961-2",
                    "display": "Pharmacogenomic analysis panel",
                }
            ],
            "text": "Pharmacogenomic / Phenotypic Test Report",
        },
        "subject": patient_reference,
        "effectiveDateTime": timestamp,
        "issued": timestamp,
        "extension": [
            _extension("test-type", test_type),
            _extension("test-result", test_result),
            *([_extension("assay-lab", assay_lab)] if assay_lab else []),
            *([_extension("result-verification-status", result_verification_status)]
              if result_verification_status else []),
        ],
        "conclusion": (
            f"{test_type} result: {test_result}. "
            f"PRISM-India recommendation for {drug}: {recommendation_given}"
        ),
    }
    if practitioner_reference:
        diagnostic_report["performer"] = [practitioner_reference]
    if specimen_date:
        diagnostic_report["specimen"] = [{"display": f"Specimen collected {specimen_date}"}]

    medication_request = {
        "resourceType": "MedicationRequest",
        "id": f"medication-request-{patient_id}",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"text": drug},
        "subject": patient_reference,
        "authoredOn": timestamp,
        "extension": [
            _extension("clinician-decision", decision),
        ],
        "note": (
            [{"text": override_reason}]
            if decision == "OVERRIDDEN" and override_reason
            else []
        ),
    }
    if practitioner_reference:
        medication_request["requester"] = practitioner_reference
    if encounter_id:
        medication_request["encounter"] = {"reference": f"Encounter/{encounter_id}"}

    bundle_extension = [
        *([_extension("institution", institution)] if institution else []),
        *([_extension("guideline-version", guideline_version)] if guideline_version else []),
        *([_extension("rule-version", rule_version)] if rule_version else []),
        *([_extension("evidence-source", evidence_source)] if evidence_source else []),
        *([_extension("software-version", software_version)] if software_version else []),
    ]

    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": timestamp,
        "entry": [
            {
                "fullUrl": f"urn:uuid:{diagnostic_report['id']}",
                "resource": diagnostic_report,
            },
            {
                "fullUrl": f"urn:uuid:{medication_request['id']}",
                "resource": medication_request,
            },
        ],
    }
    if bundle_extension:
        bundle["extension"] = bundle_extension

    return bundle
