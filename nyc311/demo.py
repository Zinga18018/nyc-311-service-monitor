"""Hand-authored synthetic records; no NYC measurements or API calls."""
from __future__ import annotations

import copy
import json
import tempfile
from datetime import date, datetime
from pathlib import Path

from nyc311.warehouse import connect, ingest_window, operations_readout, utc_now


def synthetic_rows() -> list[dict]:
    rows = []
    definitions = [
        (101, "2024-01-01T08:00:00", "2024-01-01T10:00:00", "Closed", "DEP"),
        (102, "2024-01-01T09:00:00", None, "Open", "NYPD"),
        (103, "2024-01-01T10:00:00", "2024-02-20T10:00:00", "Closed", "DEP"),
        (104, "2024-01-01T11:00:00", "2024-01-01T10:00:00", "Closed", "NYPD"),
        (105, "2024-01-02T08:00:00", None, "Closed", "DEP"),
        (106, "2024-01-02T08:00:00", None, "In Progress", "NYPD"),
    ]
    for key, created, closed, status, agency in definitions:
        rows.append(dict(unique_key=str(key), created_date=created, closed_date=closed,
                         status=status, agency=agency, complaint_type="Synthetic issue", borough="QUEENS"))
    return rows


def fixture_fetcher(rows: list[dict]):
    def fetch(start, end, cursor, limit):
        ordered = sorted(rows, key=lambda row: (datetime.fromisoformat(row["created_date"]), row["unique_key"]))
        selected = [row for row in ordered if start <= datetime.fromisoformat(row["created_date"]).date() < end]
        if cursor:
            selected = [row for row in selected if (datetime.fromisoformat(row["created_date"]), row["unique_key"]) >
                        (datetime.fromisoformat(cursor[0]), cursor[1])]
        return copy.deepcopy(selected[:limit])
    return fetch


def warehouse_counts(connection) -> dict:
    return {
        "current_requests": connection.execute("SELECT COUNT(*) FROM stg_requests").fetchone()[0],
        "raw_versions": connection.execute("SELECT COUNT(*) FROM raw_request_versions").fetchone()[0],
        "open_requests": connection.execute("SELECT COALESCE(SUM(is_open),0) FROM stg_requests").fetchone()[0],
        "valid_closed_requests": connection.execute("SELECT COUNT(response_hours) FROM stg_requests").fetchone()[0],
    }


def run_demo() -> dict:
    rows = synthetic_rows()
    fetch = fixture_fetcher(rows)
    start, end = date(2024, 1, 1), date(2024, 1, 3)
    args = dict(source="synthetic://six-request-fixture", provenance="hand-authored synthetic test data", page_size=2)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "demo.sqlite"
        connection = connect(path)
        attempts = 0
        def fail_second_page():
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError("injected failure after page writes, before checkpoint")
        try:
            ingest_window(connection, fetch, start, end, before_checkpoint=fail_second_page, **args)
        except RuntimeError:
            pass
        failed_run = dict(connection.execute("SELECT * FROM ingestion_runs").fetchone())
        after_failure = warehouse_counts(connection)
        assert failed_run["status"] == "failed" and failed_run["rows_observed"] == 2
        assert after_failure["current_requests"] == after_failure["raw_versions"] == 2
        connection.close()
        connection = connect(path)  # Recovery also exercises reopening durable storage.
        run_id = ingest_window(connection, fetch, start, end, resume_run=failed_run["run_id"], **args)
        after_resume = warehouse_counts(connection)
        assert after_resume == dict(current_requests=6, raw_versions=6, open_requests=2, valid_closed_requests=2)
        first_operations = operations_readout(connection)
        ingest_window(connection, fetch, start, end, **args)
        after_replay = warehouse_counts(connection)
        assert after_replay == after_resume
        rows[1].update(status="Closed", closed_date="2024-01-03T09:00:00")
        rows.append({**rows[0], "unique_key": "107", "created_date": "2024-01-01T12:00:00", "closed_date": None, "status": "Open"})
        rows.append({**rows[0], "unique_key": "108", "created_date": "2024-01-03T08:00:00", "closed_date": None, "status": "Open"})
        ingest_window(connection, fetch, start, date(2024, 1, 4), **args)
        after_backfill = warehouse_counts(connection)
        assert after_backfill == dict(current_requests=8, raw_versions=9, open_requests=3, valid_closed_requests=3)
        report = {
            "generated_at": utc_now(), "provenance": "synthetic_only; no live API calls",
            "fixture": "nyc311/demo.py::synthetic_rows", "initial_fixture_records": 6,
            "injected_failure": "second page, after SQL writes and before checkpoint",
            "after_failure": after_failure, "after_reopen_and_resume": after_resume,
            "after_unchanged_replay": after_replay,
            "after_late_record_backfill_and_closure_refresh": after_backfill,
            "initial_sql_operations": first_operations, "final_sql_operations": operations_readout(connection),
            "assertions_passed": True,
            "source_query_metadata": json.loads(connection.execute(
                "SELECT metadata_json FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()[0]),
            "limitations": ["Small engineering fixture, not NYC findings or load testing.",
                            "Latest observed open counts, not historical backlog snapshots.",
                            "Remote snapshot isolation, deletion capture and automatic scheduling are not implemented."],
        }
        connection.close()
    return report
