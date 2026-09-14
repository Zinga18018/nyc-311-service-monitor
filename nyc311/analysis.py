from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["created_date", "closed_date", "agency", "complaint_type", "borough", "status"]


@dataclass(frozen=True)
class MonitorConfig:
    train_days: int = 70
    anomaly_z_threshold: float = 3.0
    sla_hours: float = 48.0

    def __post_init__(self):
        if self.train_days < 1 or self.anomaly_z_threshold <= 0 or self.sla_hours != 48:
            raise ValueError("train_days and anomaly threshold must be positive; published metric uses 48 hours")


def clean_requests(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    clean = frame.copy()
    clean["created_date"] = pd.to_datetime(clean["created_date"], errors="coerce", format="mixed")
    clean["closed_date"] = pd.to_datetime(clean["closed_date"], errors="coerce", format="mixed")
    clean = clean.dropna(subset=["created_date"])
    for column in ["agency", "complaint_type", "borough", "status"]:
        clean[column] = clean[column].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    clean["is_open"] = clean["status"].str.casefold() != "closed"
    duration = (clean["closed_date"] - clean["created_date"]).dt.total_seconds() / 3600
    # Open records count toward demand; closure statistics need valid closed durations.
    clean["response_hours"] = duration.where(~clean["is_open"] & duration.ge(0))
    clean["created_day"] = clean["created_date"].dt.date.astype(str)
    clean["weekday"] = clean["created_date"].dt.day_name()
    return clean.reset_index(drop=True)


def percentile90(values: pd.Series) -> float:
    return float(values.quantile(.9)) if values.notna().any() else float("nan")


def closure_rate(values: pd.Series) -> float:
    valid = values.dropna()
    return float((valid <= 48).mean()) if len(valid) else float("nan")


def aggregate(clean: pd.DataFrame, group_column: str) -> pd.DataFrame:
    return clean.groupby(group_column).agg(
        requests=(group_column, "size"), open_requests=("is_open", "sum"),
        valid_closed_requests=("response_hours", "count"),
        median_response_hours=("response_hours", "median"),
        p90_response_hours=("response_hours", percentile90),
        within_48h_rate=("response_hours", closure_rate),
    ).reset_index()


def daily_volume(clean: pd.DataFrame, daily_counts: pd.DataFrame | None = None,
                 start: date | None = None, end: date | None = None) -> pd.DataFrame:
    daily = aggregate(clean, "created_day")
    daily["created_day"] = pd.to_datetime(daily["created_day"])
    if daily_counts is not None:
        counts = daily_counts.copy()
        counts["created_day"] = pd.to_datetime(counts["created_day"])
        if counts["created_day"].duplicated().any() or counts["requests"].isna().any() or (counts["requests"] < 0).any():
            raise ValueError("daily counts must have unique days and nonnegative known counts")
        daily = daily.drop(columns=["requests"]).merge(counts, on="created_day", how="outer")
        if daily["requests"].isna().any():
            raise ValueError("aggregate daily counts must cover every observed day")
    if (start is None) != (end is None):
        raise ValueError("supply both start and exclusive end")
    if start is not None and end is not None:
        if start >= end:
            raise ValueError("require start < end")
        calendar = pd.DataFrame({"created_day": pd.date_range(start, end, inclusive="left")})
        daily = calendar.merge(daily, on="created_day", how="left")
        if daily_counts is not None and daily["requests"].isna().any():
            raise ValueError("aggregate counts missing dates in requested calendar")
        for column in ("requests", "open_requests", "valid_closed_requests"):
            daily[column] = daily[column].fillna(0).astype(int)
    if daily.empty:
        raise ValueError("no dated requests; supply a completed window to include zero-demand days")
    daily["weekday"] = daily["created_day"].dt.day_name()
    return daily.sort_values("created_day").reset_index(drop=True)


def weekly_baseline_forecast(daily: pd.DataFrame, train_days: int) -> pd.DataFrame:
    ordered = daily.sort_values("created_day").reset_index(drop=True).copy()
    n_train = min(train_days, max(len(ordered) - 7, 1))
    train = ordered.iloc[:n_train]
    fallback = float(train["requests"].mean())
    weekday_means = train.groupby("weekday")["requests"].mean().to_dict()
    ordered["forecast_requests"] = ordered["weekday"].map(weekday_means).fillna(fallback)
    ordered["evaluation_split"] = np.where(ordered.index < n_train, "train", "holdout")
    ordered["absolute_pct_error"] = (
        (ordered["requests"] - ordered["forecast_requests"]).abs()
        / ordered["requests"].where(ordered["requests"] > 0)
    )
    return ordered


def flag_anomalies(forecast: pd.DataFrame, threshold: float) -> pd.DataFrame:
    scored = forecast.copy()
    residual = scored["requests"] - scored["forecast_requests"]
    calibration = residual[scored["evaluation_split"] == "train"]
    median = float(calibration.median())
    mad = float(np.median(np.abs(calibration - median)))
    scale = 1.4826 * mad if mad else float(calibration.std(ddof=0) or 1.0)
    scored["volume_z_score"] = (residual - median) / scale
    scored["volume_anomaly"] = scored["volume_z_score"].abs() >= threshold
    return scored


def top_table(clean: pd.DataFrame, group_column: str, limit: int = 8) -> pd.DataFrame:
    return aggregate(clean, group_column).sort_values(
        ["requests", group_column], ascending=[False, True]
    ).head(limit).reset_index(drop=True)


def finite_round(value: float, digits: int = 2) -> float | None:
    return round(float(value), digits) if pd.notna(value) and np.isfinite(value) else None


def build_analysis(frame: pd.DataFrame, config: MonitorConfig | None = None,
                   daily_counts: pd.DataFrame | None = None, *,
                   start: date | None = None, end: date | None = None) -> dict[str, Any]:
    config = config or MonitorConfig()
    clean = clean_requests(frame)
    if start is not None and end is not None:
        clean = clean[(clean["created_date"] >= pd.Timestamp(start)) &
                      (clean["created_date"] < pd.Timestamp(end))].copy()
    scored = flag_anomalies(weekly_baseline_forecast(
        daily_volume(clean, daily_counts, start, end), config.train_days
    ), config.anomaly_z_threshold)
    evaluation = scored[scored["evaluation_split"] == "holdout"]
    closed = clean["response_hours"].dropna()
    absolute_error = (evaluation["requests"] - evaluation["forecast_requests"]).abs()
    summary = {
        "rows_analyzed": int(len(clean)),
        "rows_dropped_invalid_created_date": int(pd.to_datetime(frame["created_date"], errors="coerce", format="mixed").isna().sum()),
        "volume_rows_source": "provided_aggregate_counts" if daily_counts is not None else "loaded_request_rows",
        "volume_cohort": "all statuses in loaded creation-date window",
        "closure_cohort": "status Closed with known nonnegative duration; no upper-duration trimming",
        "open_requests": int(clean["is_open"].sum()), "valid_closed_requests": int(len(closed)),
        "closed_without_valid_duration": int((~clean["is_open"] & clean["response_hours"].isna()).sum()),
        "date_min": str(scored["created_day"].min().date()), "date_max": str(scored["created_day"].max().date()),
        "days": int(len(scored)), "boroughs": int(clean["borough"].nunique()),
        "agencies": int(clean["agency"].nunique()), "complaint_types": int(clean["complaint_type"].nunique()),
        "median_response_hours": finite_round(closed.median()),
        "p90_response_hours": finite_round(closed.quantile(.9)),
        "within_48h_rate": finite_round(closure_rate(closed), 4),
        "train_days_observed": int((scored["evaluation_split"] == "train").sum()),
        "holdout_days": int(len(evaluation)),
        "forecast_mape": finite_round(evaluation["absolute_pct_error"].mean(), 4),
        "forecast_mae": finite_round(absolute_error.mean(), 4),
        "mape_excluded_zero_demand_days": int((evaluation["requests"] == 0).sum()),
        "anomaly_days": int(evaluation["volume_anomaly"].sum()),
        "anomaly_calibration": "training residuals only; exploratory threshold, not validated alert performance",
    }
    return {
        "config": asdict(config), "clean": clean, "daily": scored,
        "top_complaints": top_table(clean, "complaint_type"),
        "top_boroughs": top_table(clean, "borough"), "top_agencies": top_table(clean, "agency"),
        "summary": summary,
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in (("daily", "daily_volume_forecast"), ("top_complaints", "top_complaints"),
                          ("top_boroughs", "top_boroughs"), ("top_agencies", "top_agencies")):
        result[key].to_csv(output_dir / f"{filename}.csv", index=False)
    (output_dir / "metrics.json").write_text(json.dumps(result["summary"], indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "snapshot_provenance.json").write_text(json.dumps(
        result.get("provenance", {"snapshot_type": "caller_provided_records", "source_verified": False}),
        indent=2, allow_nan=False,
    ), encoding="utf-8")
