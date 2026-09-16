"""SQLite-backed audit trail for clinical pharmacogenomic decisions.

Schema changes are additive only: _get_connection() never drops or rebuilds the
`decisions` table. A table created under an older, narrower schema is brought
up to date via ALTER TABLE ADD COLUMN for whatever columns it's missing, which
preserves every existing row -- there is no automatic destruction of audit data.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "decisions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    timestamp_utc TEXT,
    patient_id TEXT,
    drug TEXT,
    test_type TEXT,
    test_result TEXT,
    recommendation_given TEXT,
    clinician_decision TEXT,
    override_reason TEXT,
    clinician_id TEXT,
    institution TEXT,
    encounter_id TEXT,
    assay_lab TEXT,
    specimen_date TEXT,
    result_verification_status TEXT,
    guideline_version TEXT,
    rule_version TEXT,
    evidence_source TEXT,
    software_version TEXT,
    adr_risk_flag TEXT
)
"""

# Every column CREATE TABLE can add for a brand-new database. `id` is the
# primary key and is never touched by migration; every other column here is
# safe to add to an existing table via ALTER TABLE ADD COLUMN if missing,
# which is how a table created under an older/narrower schema catches up.
_MIGRATABLE_COLUMNS = [
    "timestamp", "timestamp_utc", "patient_id", "drug", "test_type", "test_result",
    "recommendation_given", "clinician_decision", "override_reason",
    "clinician_id", "institution", "encounter_id", "assay_lab", "specimen_date",
    "result_verification_status", "guideline_version", "rule_version",
    "evidence_source", "software_version", "adr_risk_flag",
]


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)

    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
    for column in _MIGRATABLE_COLUMNS:
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {column} TEXT")
    conn.commit()

    return conn


def log_decision(
    patient_id: str,
    drug: str,
    test_type: str,
    test_result: str,
    recommendation_given: str,
    clinician_decision: str,
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
    adr_risk_flag: str = None,
) -> None:
    """Persist one clinician decision. clinician_decision is ACCEPTED or OVERRIDDEN.

    The keyword-only arguments are structured clinical-encounter metadata
    (clinician_id..result_verification_status), system provenance fields
    (guideline_version..software_version), and the Layer 2 baseline ADR risk
    verdict (adr_risk_flag, e.g. engine.clinical.ADR_RISK_HIGH or
    ADR_RISK_STANDARD); all are optional so callers that only need the
    original core fields keep working unchanged.
    """
    conn = _get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO decisions
                (timestamp, timestamp_utc, patient_id, drug, test_type, test_result,
                 recommendation_given, clinician_decision, override_reason,
                 clinician_id, institution, encounter_id, assay_lab, specimen_date,
                 result_verification_status, guideline_version, rule_version,
                 evidence_source, software_version, adr_risk_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                patient_id,
                drug,
                test_type,
                test_result,
                recommendation_given,
                clinician_decision,
                override_reason,
                clinician_id,
                institution,
                encounter_id,
                assay_lab,
                specimen_date,
                result_verification_status,
                guideline_version,
                rule_version,
                evidence_source,
                software_version,
                adr_risk_flag,
            ),
        )
    conn.close()


def get_all_logs() -> pd.DataFrame:
    """Return every logged decision as a DataFrame, most recent first."""
    conn = _get_connection()
    df = pd.read_sql_query("SELECT * FROM decisions ORDER BY id DESC", conn)
    conn.close()
    return df
