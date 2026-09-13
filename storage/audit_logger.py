"""SQLite-backed audit trail for clinical pharmacogenomic decisions."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "decisions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    patient_id TEXT,
    drug TEXT,
    test_type TEXT,
    test_result TEXT,
    recommendation_given TEXT,
    clinician_decision TEXT,
    override_reason TEXT
)
"""


_EXPECTED_COLUMNS = {
    "id", "timestamp", "patient_id", "drug", "test_type", "test_result",
    "recommendation_given", "clinician_decision", "override_reason",
}


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)

    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
    if existing_columns != _EXPECTED_COLUMNS:
        # A decisions.db created under an older schema (e.g. a bare `genotype`
        # column) can't be reconciled with ALTER TABLE alone; rebuild it. This
        # is a demo audit log, not a system of record, so dropping stale rows
        # on a schema change is an acceptable, zero-maintenance recovery path.
        conn.execute("DROP TABLE IF EXISTS decisions")
        conn.execute(_SCHEMA)

    return conn


def log_decision(
    patient_id: str,
    drug: str,
    test_type: str,
    test_result: str,
    recommendation_given: str,
    clinician_decision: str,
    override_reason: str = None,
) -> None:
    """Persist one clinician decision. clinician_decision is ACCEPTED or OVERRIDDEN."""
    conn = _get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO decisions
                (timestamp, patient_id, drug, test_type, test_result,
                 recommendation_given, clinician_decision, override_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                patient_id,
                drug,
                test_type,
                test_result,
                recommendation_given,
                clinician_decision,
                override_reason,
            ),
        )
    conn.close()


def get_all_logs() -> pd.DataFrame:
    """Return every logged decision as a DataFrame, most recent first."""
    conn = _get_connection()
    df = pd.read_sql_query("SELECT * FROM decisions ORDER BY id DESC", conn)
    conn.close()
    return df
