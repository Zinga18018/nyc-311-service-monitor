# Verification record — September 14, 2026

## Verified locally

Command: `python -m unittest discover -s tests -v`

Observed result: **22 tests passed** on Windows, Python 3.11.15. The retained
[test output](../outputs/test_run_20260914.txt) includes the exact test names.
Packages used for this run: pandas 2.3.3, NumPy 2.4.6, Streamlit 1.63.0,
PyArrow 19.0.1. This is a tested environment record, not a complete dependency lock.

The tests check:

- Paging past the per-page limit, equal-time text-ID ordering, and all-status queries.
- Replay without duplicate current facts or duplicate unchanged source versions.
- Open-to-closed updates while preserving prior raw versions.
- Rollback of raw/staging/page/checkpoint changes when failure occurs within a page.
- Network failure after a committed page, followed by a successful resume.
- Resume metadata mismatches and nonadvancing pages failing explicitly.
- Open/invalid/long-running records and closed-only denominator calculations.
- Empty completed windows, zero-demand dates, null metrics, and aggregate-only days.
- Holdout observations not changing training anomaly calibration.
- Dashboard warnings for historical biased outputs, and N/A rendering for an all-open cohort.

Command: `python scripts/demo_warehouse.py`

The [actual demonstration output](../outputs/synthetic_warehouse_demo.json)
records six initial synthetic requests. Failure leaves two committed requests;
reopening and resuming reaches six. Unchanged replay stays at six. A closure
update, historical late record, and new-day record yield eight current requests
and nine raw versions. The script asserts these outcomes before reporting success.

## Limited live verification

The [API smoke record](../outputs/live_api_smoke.json) stores two consecutive
pages of two IDs each, checked on September 14. They have no overlap. The live
source required a text comparison for unique_key; the query and cursor now
preserve that type and ordering.

This check verifies query execution and cursor advancement across four records.
It does **not** verify a complete day, source-count reconciliation, open-request
coverage, changed-record capture, citywide backlog, or the dashboard's forecast.
The new pipeline has not rebuilt the historical published aggregates.

## Preserved historical evidence

The old aggregate CSV/JSON files were not recalculated or relabeled as fresh
results. Added [processed-data provenance](../data/processed/snapshot_provenance.json)
and [output provenance](../outputs/snapshot_provenance.json) describe the old
closed-only filter, earliest-record cap, long-duration removal, and retrospective
anomaly calibration, and record SHA-256 hashes of the retained artifacts.

## Boundaries

Streamlit tests execute the app through its testing interface; they are not a
browser screenshot/visual audit. The warehouse demo is not scale, concurrency,
or production resilience testing. The client has no source snapshot isolation,
deletion capture, automatic scheduling, or point-in-time backlog snapshots.
GitHub Actions is configured for Python 3.11 and 3.12, but a hosted result is not
claimed until a run is observed after publication.

On this Windows host, application control blocked the PyArrow 25.0.1 compute
module. Installing the older official 19.0.1 package in the project environment
allowed imports and dashboard tests; no application-control policy was changed.
