from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyc311.analysis import MonitorConfig, build_analysis, write_outputs


ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"


def build_url(start: date, end: date, limit: int = 350) -> str:
    query = {
        "$limit": limit,
        "$select": "created_date,closed_date,agency,complaint_type,borough,status",
        "$where": (
            f"created_date >= '{start.isoformat()}T00:00:00' AND "
            f"created_date < '{end.isoformat()}T00:00:00' AND closed_date IS NOT NULL"
        ),
        "$order": "created_date",
    }
    return f"{ENDPOINT}?{urlencode(query)}"


def fetch_stratified_daily_sample() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    current = date(2024, 1, 1)
    stop = date(2024, 4, 1)
    while current < stop:
        next_day = current + timedelta(days=1)
        frame = pd.read_csv(build_url(current, next_day))
        frames.append(frame)
        current = next_day
    return pd.concat(frames, ignore_index=True)


def fetch_daily_counts() -> pd.DataFrame:
    query = {
        "$select": "date_trunc_ymd(created_date) as created_day, count(*) as requests",
        "$where": (
            "created_date >= '2024-01-01T00:00:00' AND "
            "created_date < '2024-04-01T00:00:00' AND closed_date IS NOT NULL"
        ),
        "$group": "date_trunc_ymd(created_date)",
        "$order": "date_trunc_ymd(created_date)",
    }
    url = f"{ENDPOINT}?{urlencode(query)}"
    counts = pd.read_csv(url)
    counts["created_day"] = pd.to_datetime(counts["created_day"]).dt.date.astype(str)
    counts["requests"] = counts["requests"].astype(int)
    return counts


def main() -> None:
    print(f"fetching NYC 311 sample from {ENDPOINT}")
    frame = fetch_stratified_daily_sample()
    daily_counts = fetch_daily_counts()
    print(f"downloaded_rows={len(frame)}")
    print(f"daily_count_days={len(daily_counts)}")

    result = build_analysis(frame, MonitorConfig(train_days=70), daily_counts=daily_counts)
    write_outputs(result, Path("data/processed"))
    write_outputs(result, Path("outputs"))

    metrics = result["summary"]
    print(f"rows_analyzed={metrics['rows_analyzed']}")
    print(f"days={metrics['days']}")
    print(f"median_response_hours={metrics['median_response_hours']}")
    print(f"forecast_mape={metrics['forecast_mape']}")
    print(f"anomaly_days={metrics['anomaly_days']}")


if __name__ == "__main__":
    main()
