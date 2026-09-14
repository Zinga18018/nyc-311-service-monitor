from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("NYC311_DATA_DIR", ROOT / "data/processed"))

st.set_page_config(page_title="NYC 311 Service Monitor", layout="wide")
st.title("NYC 311 Service Monitor")
st.caption("Request demand, observed open records, and time to recorded closure for explicit data cohorts.")

metrics = json.loads((DATA_DIR / "metrics.json").read_text(encoding="utf-8"))
provenance_path = DATA_DIR / "snapshot_provenance.json"
provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
legacy = provenance.get("snapshot_type") == "legacy_biased_sample" or "volume_cohort" not in metrics
if legacy:
    st.warning("Historical biased sample: earliest 350 closed records per day, with invalid and over-45-day durations removed. Daily counts also required a closed date. These charts cannot establish citywide demand, backlog, or service-level compliance.")
else:
    st.info("Counts cover loaded creation-date cohorts. Open means the latest observed status is not Closed. Closure times include only valid closed records; they do not measure time to first response.")
with st.expander("Data source and cohort details"):
    st.json(provenance)
daily = pd.read_csv(DATA_DIR / "daily_volume_forecast.csv", parse_dates=["created_day"])
complaints = pd.read_csv(DATA_DIR / "top_complaints.csv")
boroughs = pd.read_csv(DATA_DIR / "top_boroughs.csv")
agencies = pd.read_csv(DATA_DIR / "top_agencies.csv")

def display_number(value, suffix="", scale=1):
    return f"{float(value) * scale:.1f}{suffix}" if value is not None else "N/A"

top = st.columns(6)
top[0].metric("Rows analyzed", f"{int(metrics['rows_analyzed']):,}")
top[1].metric("Days", f"{int(metrics['days'])}")
top[2].metric("Median closure time", display_number(metrics['median_response_hours'], "h"))
top[3].metric("Closed within 48h", display_number(metrics['within_48h_rate'], "%", 100))
top[4].metric("Flagged days", f"{int(metrics['anomaly_days'])}")
top[5].metric("Observed open requests", str(metrics["open_requests"]) if "open_requests" in metrics else "Unavailable")
st.caption("The 48-hour percentage uses valid closed records as its denominator. It is not an all-request SLA rate.")

st.subheader("Daily Recorded Request Volume")
if legacy:
    st.caption("Legacy counts include only records with a closed date; anomaly calibration was retrospective.")
else:
    st.caption(f"Training days: {metrics.get('train_days_observed', 'N/A')}; holdout days: {metrics.get('holdout_days', 'N/A')}. The weekday baseline and anomaly calibration use training days only. Flags are exploratory.")
chart = daily.set_index("created_day")[["requests", "forecast_requests"]]
st.line_chart(chart)

anomalies = daily[daily["volume_anomaly"]]
if "evaluation_split" in daily:
    anomalies = anomalies[anomalies["evaluation_split"] == "holdout"]
if len(anomalies):
    st.warning(f"{len(anomalies)} volume anomaly days flagged by residual z-score.")
    st.dataframe(
        anomalies[["created_day", "requests", "forecast_requests", "volume_z_score"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.success("No volume anomaly days under the current threshold.")

left, middle, right = st.columns(3)
with left:
    st.subheader("Top complaint types")
    st.dataframe(complaints, use_container_width=True, hide_index=True)
with middle:
    st.subheader("Borough closure patterns")
    st.dataframe(boroughs, use_container_width=True, hide_index=True)
with right:
    st.subheader("Agency closure patterns")
    st.dataframe(agencies, use_container_width=True, hide_index=True)

st.subheader("Closure-Time Summaries by Complaint")
st.bar_chart(complaints.set_index("complaint_type")[["median_response_hours", "p90_response_hours"]])

st.subheader("Operational follow-up")
st.write("Use high observed open counts to choose queues for investigation. Review missing or inconsistent closure dates before comparing service speed. Compare similar complaint types and creation windows before recommending staffing changes.")
readout_path = DATA_DIR / "warehouse_operations_readout.json"
if readout_path.exists():
    readout = json.loads(readout_path.read_text(encoding="utf-8"))
    st.caption(readout["cohort"] + "; this may cover more dates than the charts above.")
    st.dataframe(readout["agencies"], use_container_width=True, hide_index=True)
