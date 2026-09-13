"""Build ABDM-compliant FHIR R4 bundles for PRISM-India decisions."""

import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_fhir_bundle(
    patient_id: str,
    drug: str,
    test_type: str,
    test_result: str,
    recommendation_given: str,
    decision: str,
    override_reason: str = None,
) -> dict:
    """Build a FHIR Bundle with a DiagnosticReport and a MedicationRequest.

    `test_type` is "Genotype" or "Phenotype" and `test_result` is the raw lab
    value behind the recommendation. `decision` is ACCEPTED or OVERRIDDEN,
    matching storage.audit_logger.
    """
    timestamp = _now_iso()
    patient_reference = {"reference": f"Patient/{patient_id}", "display": patient_id}

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
            {
                "url": "http://prism-india.org/fhir/StructureDefinition/test-type",
                "valueString": test_type,
            },
            {
                "url": "http://prism-india.org/fhir/StructureDefinition/test-result",
                "valueString": test_result,
            },
        ],
        "conclusion": (
            f"{test_type} result: {test_result}. "
            f"PRISM-India recommendation for {drug}: {recommendation_given}"
        ),
    }

    medication_request = {
        "resourceType": "MedicationRequest",
        "id": f"medication-request-{patient_id}",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"text": drug},
        "subject": patient_reference,
        "authoredOn": timestamp,
        "extension": [
            {
                "url": "http://prism-india.org/fhir/StructureDefinition/clinician-decision",
                "valueString": decision,
            }
        ],
        "note": (
            [{"text": override_reason}]
            if decision == "OVERRIDDEN" and override_reason
            else []
        ),
    }

    return {
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
