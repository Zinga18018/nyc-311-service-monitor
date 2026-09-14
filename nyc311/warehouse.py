"""Transactional, resumable daily ingestion; no network dependency in this module."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
Cursor = tuple[str, str] | None
PageFetcher = Callable[[date, date, Cursor, int], list[dict]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
    return connection


def normalize_request(row: dict) -> dict:
    """Preserve open/long-running records; flag unreliable closure durations."""
    key = str(row.get("unique_key", ""))
    if not key.isascii() or not key.isdigit():
        raise ValueError("unique_key must be a nonnegative numeric source ID")
    created = datetime.fromisoformat(str(row["created_date"]))
    if created.tzinfo is not None:
        raise ValueError("created_date must use source local wall time, without timezone")
    closed_raw = row.get("closed_date")
    closed, issue = None, None
    if closed_raw:
        try:
            closed = datetime.fromisoformat(str(closed_raw))
            if closed.tzinfo is not None:
                raise ValueError("unexpected timezone")
        except (ValueError, TypeError):
            issue = "invalid_closed_date"
            closed = None
    dimensions = {
        field: str(row.get(field) or "Unknown").strip() or "Unknown"
        for field in ("agency", "complaint_type", "borough", "status")
    }
    is_open = dimensions["status"].casefold() != "closed"
    hours = None
    if is_open:
        if closed is not None:
            issue = "nonclosed_status_with_closed_date"
        elif dimensions["status"] == "Unknown":
            issue = "unknown_status"
    elif closed is None:
        issue = issue or "closed_status_without_closed_date"
    elif closed < created:
        issue = "closed_before_created"
    else:
        hours = (closed - created).total_seconds() / 3600
    return {
        "unique_key": key, "created_date": created.isoformat(),
        "closed_date": closed.isoformat() if closed is not None else None,
        **dimensions, "is_open": int(is_open), "response_hours": hours,
        "quality_issue": issue,
    }


def ingest_window(
    connection: sqlite3.Connection,
    fetch_page: PageFetcher,
    start: date,
    end: date,
    *,
    source: str,
    provenance: str,
    page_size: int = 1000,
    resume_run: str | None = None,
    before_checkpoint: Callable[[], None] | None = None,
) -> str:
    """Checkpoint each page atomically with raw history and current-state upserts.

    A failed run is resumed with the same window, source and page size. A new
    run over an old window is a refresh/backfill, not a duplicate fact load.
    Source deletions and point-in-time source snapshots are not implemented.
    """
    if start >= end or page_size < 1:
        raise ValueError("require start < end and a positive page_size")
    metadata = json.dumps({
        "source": source, "provenance": provenance,
        "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
        "page_size": page_size,
        "cohort": "all statuses by created_date; no closed_date filter",
        "pagination": "daily keyset ordered by created_date, text unique_key; no total row cap",
        "snapshot_isolation": False,
    }, sort_keys=True)
    run_id = resume_run or str(uuid.uuid4())
    if resume_run:
        previous = connection.execute(
            "SELECT * FROM ingestion_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if previous is None or previous["metadata_json"] != metadata:
            raise ValueError("resume run missing or window/source/provenance/page size changed")
        if previous["status"] == "completed":
            return run_id
        with connection:
            connection.execute(
                "UPDATE ingestion_runs SET status='running', error=NULL WHERE run_id=?", (run_id,)
            )
    else:
        with connection:
            connection.execute(
                "INSERT INTO ingestion_runs (run_id,status,metadata_json,started_at,next_day) "
                "VALUES (?,'running',?,?,?)", (run_id, metadata, utc_now(), start.isoformat())
            )
    try:
        while True:
            run = connection.execute(
                "SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            day = date.fromisoformat(run["next_day"])
            if day >= end:
                with connection:
                    connection.execute(
                        "UPDATE ingestion_runs SET status='completed', finished_at=? WHERE run_id=?",
                        (utc_now(), run_id),
                    )
                return run_id
            cursor = (run["cursor_created"], run["cursor_key"]) if run["cursor_created"] else None
            page = fetch_page(day, day + timedelta(days=1), cursor, page_size)
            if len(page) > page_size:
                raise ValueError("source exceeded requested page size")
            staged = [normalize_request(row) for row in page]
            prior = (datetime.fromisoformat(cursor[0]), cursor[1]) if cursor else None
            for row in staged:
                point = (datetime.fromisoformat(row["created_date"]), row["unique_key"])
                if point[0].date() != day or (prior is not None and point <= prior):
                    raise ValueError("page must be strictly ordered, advance cursor, and remain in requested day")
                prior = point
            finished_day = len(page) < page_size
            observed_at, page_number = utc_now(), run["pages_committed"] + 1
            with connection:
                connection.execute(
                    "INSERT INTO ingestion_pages VALUES (?,?,?,?,?,?,?)",
                    (run_id, page_number, day.isoformat(), cursor[0] if cursor else None,
                     cursor[1] if cursor else None, len(page), observed_at),
                )
                for raw, row in zip(page, staged):
                    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    digest = hashlib.sha256(payload.encode()).hexdigest()
                    connection.execute(
                        "INSERT OR IGNORE INTO raw_request_versions VALUES (?,?,?,?)",
                        (row["unique_key"], digest, payload, observed_at),
                    )
                    connection.execute(
                        "INSERT INTO raw_observations VALUES (?,?,?,?,?)",
                        (run_id, page_number, row["unique_key"], digest, observed_at),
                    )
                    row.update(payload_sha256=digest, observed_at=observed_at)
                    columns = list(row)
                    connection.execute(
                        f"INSERT INTO stg_requests ({','.join(columns)}) VALUES "
                        f"({','.join('?' for _ in columns)}) ON CONFLICT(unique_key) DO UPDATE SET "
                        + ','.join(f"{column}=excluded.{column}" for column in columns if column != 'unique_key'),
                        list(row.values()),
                    )
                if before_checkpoint is not None:
                    before_checkpoint()
                connection.execute(
                    "UPDATE ingestion_runs SET next_day=?,cursor_created=?,cursor_key=?,"
                    "pages_committed=pages_committed+1,rows_observed=rows_observed+? WHERE run_id=?",
                    ((day + timedelta(days=1)).isoformat() if finished_day else day.isoformat(),
                     None if finished_day else staged[-1]["created_date"],
                     None if finished_day else staged[-1]["unique_key"], len(page), run_id),
                )
    except Exception as exc:
        with connection:
            connection.execute(
                "UPDATE ingestion_runs SET status='failed',error=? WHERE run_id=?",
                (f"{type(exc).__name__}: {exc}", run_id),
            )
        raise


def open_cohort_days(connection: sqlite3.Connection) -> list[date]:
    return [date.fromisoformat(row[0]) for row in connection.execute(
        "SELECT DISTINCT substr(created_date,1,10) FROM stg_requests WHERE is_open=1 ORDER BY 1"
    )]


def operations_readout(connection: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in connection.execute(
        (ROOT / "sql/operations_readout.sql").read_text(encoding="utf-8")
    )]
