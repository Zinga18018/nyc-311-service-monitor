from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = [
    "created_date",
    "closed_date",
    "agency",
    "complaint_type",
    "borough",
    "status",
]


@dataclass(frozen=True)
class MonitorConfig:
    train_days: int = 70
    anomaly_z_threshold: float = 3.0
    sla_hours: float = 48.0


def clean_requests(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")

    clean = frame[REQUIRED_COLUMNS].copy()
    clean["created_date"] = pd.to_datetime(clean["created_date"], errors="coerce")
    clean["closed_date"] = pd.to_datetime(clean["closed_date"], errors="coerce")
    clean = clean.dropna(subset=["created_date", "closed_date"])
    clean = clean[clean["closed_date"] >= clean["created_date"]]

    clean["response_hours"] = (
        clean["closed_date"] - clean["created_date"]
    ).dt.total_seconds() / 3600.0
    clean = clean[clean["response_hours"].between(0, 24 * 45)]

    for column in ["agency", "complaint_type", "borough", "status"]:
        clean[column] = clean[column].fillna("Unknown").astype(str).str.strip()
        clean.loc[clean[column] == "", column] = "Unknown"

    clean["created_day"] = clean["created_date"].dt.date.astype(str)
    clean["weekday"] = clean["created_date"].dt.day_name()
    return clean.reset_index(drop=True)


def daily_volume(clean: pd.DataFrame, daily_counts: pd.DataFrame | None = None) -> pd.DataFrame:
    daily = (
        clean.groupby("created_day")
        .agg(
            requests=("created_day", "size"),
            median_response_hours=("response_hours", "median"),
            p90_response_hours=("response_hours", lambda values: float(np.percentile(values, 90))),
            within_48h_rate=("response_hours", lambda values: float((values <= 48).mean())),
        )
        .reset_index()
    )
    daily["created_day"] = pd.to_datetime(daily["created_day"])
    if daily_counts is not None:
        counts = daily_counts.copy()
        counts["created_day"] = pd.to_datetime(counts["created_day"])
        counts["requests"] = counts["requests"].astype(int)
        daily = daily.drop(columns=["requests"]).merge(counts, on="created_day", how="left")
        daily["requests"] = daily["requests"].fillna(0).astype(int)
    daily["weekday"] = daily["created_day"].dt.day_name()
    return daily.sort_values("created_day").reset_index(drop=True)


def weekly_baseline_forecast(daily: pd.DataFrame, train_days: int) -> pd.DataFrame:
    ordered = daily.sort_values("created_day").reset_index(drop=True).copy()
    train = ordered.head(min(train_days, max(len(ordered) - 7, 1))).copy()
    fallback = float(train["requests"].mean())
    weekday_means = train.groupby("weekday")["requests"].mean().to_dict()

    ordered["forecast_requests"] = ordered["weekday"].map(weekday_means).fillna(fallback)
    ordered["absolute_pct_error"] = (
        (ordered["requests"] - ordered["forecast_requests"]).abs()
        / ordered["requests"].clip(lower=1)
    )
    return ordered


def flag_anomalies(forecast: pd.DataFrame, threshold: float) -> pd.DataFrame:
    scored = forecast.copy()
    residual = scored["requests"] - scored["forecast_requests"]
    median = float(residual.median())
    mad = float(np.median(np.abs(residual - median)))
    scale = 1.4826 * mad if mad else float(residual.std(ddof=0) or 1.0)
    scored["volume_z_score"] = (residual - median) / scale
    scored["volume_anomaly"] = scored["volume_z_score"].abs() >= threshold
    return scored


def top_table(clean: pd.DataFrame, group_column: str, limit: int = 8) -> pd.DataFrame:
    table = (
        clean.groupby(group_column)
        .agg(
            requests=(group_column, "size"),
            median_response_hours=("response_hours", "median"),
            p90_response_hours=("response_hours", lambda values: float(np.percentile(values, 90))),
            within_48h_rate=("response_hours", lambda values: float((values <= 48).mean())),
        )
        .sort_values("requests", ascending=False)
        .head(limit)
        .reset_index()
    )
    return table


def build_analysis(
    frame: pd.DataFrame,
    config: MonitorConfig | None = None,
    daily_counts: pd.DataFrame | None = None,
) -> dict[str, Any]:
    config = config or MonitorConfig()
    clean = clean_requests(frame)
    daily = daily_volume(clean, daily_counts=daily_counts)
    forecast = weekly_baseline_forecast(daily, config.train_days)
    scored = flag_anomalies(forecast, config.anomaly_z_threshold)

    eval_start = min(config.train_days, max(len(scored) - 7, 0))
    eval_slice = scored.iloc[eval_start:].copy()
    mape = float(eval_slice["absolute_pct_error"].mean()) if len(eval_slice) else 0.0

    summary = {
        "rows_analyzed": int(len(clean)),
        "volume_rows_source": "api_daily_counts" if daily_counts is not None else "sample_rows",
        "date_min": str(clean["created_date"].min().date()),
        "date_max": str(clean["created_date"].max().date()),
        "days": int(scored["created_day"].nunique()),
        "boroughs": int(clean["borough"].nunique()),
        "agencies": int(clean["agency"].nunique()),
        "complaint_types": int(clean["complaint_type"].nunique()),
        "median_response_hours": round(float(clean["response_hours"].median()), 2),
        "p90_response_hours": round(float(np.percentile(clean["response_hours"], 90)), 2),
        "within_48h_rate": round(float((clean["response_hours"] <= config.sla_hours).mean()), 4),
        "forecast_mape": round(mape, 4),
        "anomaly_days": int(scored["volume_anomaly"].sum()),
    }

    return {
        "config": asdict(config),
        "clean": clean,
        "daily": scored,
        "top_complaints": top_table(clean, "complaint_type"),
        "top_boroughs": top_table(clean, "borough"),
        "top_agencies": top_table(clean, "agency"),
        "summary": summary,
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result["daily"].to_csv(output_dir / "daily_volume_forecast.csv", index=False)
    result["top_complaints"].to_csv(output_dir / "top_complaints.csv", index=False)
    result["top_boroughs"].to_csv(output_dir / "top_boroughs.csv", index=False)
    result["top_agencies"].to_csv(output_dir / "top_agencies.csv", index=False)
    (output_dir / "metrics.json").write_text(
        json.dumps(result["summary"], indent=2),
        encoding="utf-8",
    )
