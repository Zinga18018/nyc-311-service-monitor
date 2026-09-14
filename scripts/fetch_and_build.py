from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyc311.analysis import MonitorConfig, build_analysis, write_outputs
from nyc311.warehouse import Cursor, connect, ingest_window, open_cohort_days, operations_readout

ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"


def build_url(start: date, end: date, limit: int = 1000, cursor: Cursor = None) -> str:
    if start >= end or limit < 1:
        raise ValueError("require start < end and a positive page size")
    where = (
        f"created_date >= '{start.isoformat()}T00:00:00' AND "
        f"created_date < '{end.isoformat()}T00:00:00'"
    )
    if cursor is not None:
        created = datetime.fromisoformat(cursor[0]).isoformat()
        key = str(cursor[1])
        if not key.isascii() or not key.isdigit():
            raise ValueError("cursor unique_key must be numeric text")
        where += (
            f" AND (created_date > '{created}' OR "
            f"(created_date = '{created}' AND unique_key > '{key}'))"
        )
    query = {
        "$limit": limit,
        "$select": "unique_key,created_date,closed_date,agency,complaint_type,borough,status",
        "$where": where,
        "$order": "created_date ASC, unique_key ASC",
    }
    return f"{ENDPOINT}?{urlencode(query)}"


def fetch_page(start: date, end: date, cursor: Cursor, limit: int) -> list[dict]:
    headers = {"Accept": "application/json", "User-Agent": "nyc-311-service-monitor/2"}
    if os.environ.get("SOCRATA_APP_TOKEN"):
        headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
    request = Request(build_url(start, end, limit, cursor), headers=headers)
    with urlopen(request, timeout=60) as response:
        data = json.load(response)
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("source did not return a list of request records")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Load complete paginated creation-date cohorts into SQLite.")
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="inclusive creation date")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="exclusive creation date")
    parser.add_argument("--database", type=Path, default=ROOT / "data/warehouse/nyc311.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--train-days", type=int, default=70)
    parser.add_argument("--resume-run", help="resume the run ID shown after a failed load")
    parser.add_argument("--refresh-open", action="store_true", help="also refresh older loaded days with open requests")
    args = parser.parse_args()
    if args.start >= args.end or args.page_size < 1:
        parser.error("require start < end and a positive page size")
    connection = connect(args.database)
    try:
        run_id = ingest_window(
            connection, fetch_page, args.start, args.end, source=ENDPOINT,
            provenance="NYC Open Data live API", page_size=args.page_size,
            resume_run=args.resume_run,
        )
        refreshed = []
        if args.refresh_open:
            for day in open_cohort_days(connection):
                if args.start <= day < args.end:
                    continue
                refreshed.append(ingest_window(
                    connection, fetch_page, day, day + timedelta(days=1), source=ENDPOINT,
                    provenance="NYC Open Data live API", page_size=args.page_size,
                ))
        frame = pd.read_sql_query(
            "SELECT * FROM stg_requests WHERE created_date>=? AND created_date<? ORDER BY created_date, unique_key",
            connection, params=(args.start.isoformat(), args.end.isoformat()),
        )
        result = build_analysis(frame, MonitorConfig(train_days=args.train_days), start=args.start, end=args.end)
        run = dict(connection.execute("SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone())
        result["provenance"] = {
            "snapshot_type": "paginated_live_cohort", "run": run,
            "query_example_first_page": build_url(args.start, args.start + timedelta(days=1), args.page_size),
            "refreshed_open_cohort_run_ids": refreshed,
            "coverage_limitations": "No source snapshot isolation, deletion capture, or guaranteed detection of late historical inserts. Counts describe loaded current records in this creation window.",
        }
        write_outputs(result, args.output)
        (args.output / "warehouse_operations_readout.json").write_text(json.dumps({
            "cohort": "all loaded creation windows, latest observed statuses",
            "agencies": operations_readout(connection),
        }, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"run_id": run_id, "output": str(args.output), **result["summary"]}, indent=2))
    except Exception:
        failed = connection.execute(
            "SELECT run_id,metadata_json,error FROM ingestion_runs WHERE status='failed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if failed:
            print("Failed run: " + json.dumps(dict(failed)), file=sys.stderr)
            print("Resume with that run ID and its exact start/end/page-size. Already committed pages are retained.", file=sys.stderr)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
