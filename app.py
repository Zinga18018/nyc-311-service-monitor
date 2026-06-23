from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


DATA_DIR = Path("data/processed")

st.set_page_config(page_title="NYC 311 Service Monitor", layout="wide")
st.title("NYC 311 Service Monitor")
st.caption("Response-time and demand-monitoring view built from NYC Open Data 311 service requests.")

metrics = pd.read_json(DATA_DIR / "metrics.json", typ="series")
daily = pd.read_csv(DATA_DIR / "daily_volume_forecast.csv", parse_dates=["created_day"])
complaints = pd.read_csv(DATA_DIR / "top_complaints.csv")
boroughs = pd.read_csv(DATA_DIR / "top_boroughs.csv")
agencies = pd.read_csv(DATA_DIR / "top_agencies.csv")

top = st.columns(5)
top[0].metric("Rows analyzed", f"{int(metrics['rows_analyzed']):,}")
top[1].metric("Days", f"{int(metrics['days'])}")
top[2].metric("Median response", f"{float(metrics['median_response_hours']):.1f}h")
top[3].metric("Within 48h", f"{float(metrics['within_48h_rate']) * 100:.1f}%")
top[4].metric("Anomaly days", f"{int(metrics['anomaly_days'])}")

st.subheader("Daily Request Volume")
chart = daily.set_index("created_day")[["requests", "forecast_requests"]]
st.line_chart(chart)

anomalies = daily[daily["volume_anomaly"]]
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
    st.subheader("Borough response")
    st.dataframe(boroughs, use_container_width=True, hide_index=True)
with right:
    st.subheader("Agency response")
    st.dataframe(agencies, use_container_width=True, hide_index=True)

st.subheader("Response-Time Distribution")
st.bar_chart(complaints.set_index("complaint_type")[["median_response_hours", "p90_response_hours"]])
