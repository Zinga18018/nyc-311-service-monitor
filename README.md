# NYC 311 Service Monitor

A service-operations dashboard with a local SQLite warehouse: collect public
requests, retain source versions, update changed records, and separate demand,
observed open requests, and time to recorded closure.

[Workflow and code map](WORKFLOW.md) | [Metric dictionary](docs/METRICS.md) |
[Verification evidence](docs/VERIFICATION.md)

## What changed

The original fetch selected only closed records and kept the earliest 350 per
day. The original analysis also removed durations over 45 days. Those choices
biased closure summaries and could not measure all-request demand or backlog.

The new path:

- Pages through each requested creation day, ordered by creation time and the
  source's text request ID. There is no daily total-row cap or closed-date filter.
- Stores immutable raw versions and observation history, then upserts one current
  row per request ID. Replaying a window does not duplicate current requests.
- Commits page data, query cursor, and checkpoint in one SQLite transaction.
  A failed run can resume after the last committed page.
- Supports overlapping incremental refreshes, explicit historical backfills,
  and refreshes of older loaded days containing open requests.
- Exposes daily and agency SQL marts, a metric dictionary, and an investigation
  readout. Open records stay in demand counts; only valid closed records enter
  closure-duration statistics. Long durations are retained.
- Fits the weekday forecast and anomaly calibration on training days only.
  Holdout days, zero-demand exclusions, and denominators are explicit.

## What has actually been verified

The [offline demonstration](outputs/synthetic_warehouse_demo.json) uses **six
hand-authored synthetic records**. It injects a failure after SQL writes but
before the second checkpoint, closes and reopens the database, resumes, replays,
and backfills changed/new records.

| Checkpoint | Current requests | Raw versions |
|---|---:|---:|
| After injected failure | 2 | 2 |
| After reopen and resume | 6 | 6 |
| After unchanged replay | 6 | 6 |
| After closure update plus two new records | 8 | 9 |

**22 local tests passed** on Python 3.11.15, including warehouse recovery, source
pagination, closure denominators, training-only anomaly calibration, and the
Streamlit legacy warning/all-open dashboard paths. This is engineering fixture
evidence, not a scale benchmark or a city service result.

A separate [live query smoke check](outputs/live_api_smoke.json) fetched **four
records across two pages**. It verified the source's text-ID cursor and no overlap
between those two pages. **A full live window has not been loaded or verified with
the new pipeline.** GitHub Actions are configured; a passing hosted run is not
claimed by this local report.

## Historical dashboard data

The committed `data/processed` and original aggregate `outputs` files are retained
as a **legacy biased sample**. The stored metrics report 30,626 cleaned records
and 91 creation days. They are not new pipeline results. Their provenance files
record the earlier filters, limitations, and hashes of the unchanged artifacts.
The default dashboard visibly warns about this and shows backlog as unavailable.

Do not use its old 86.37% figure as an all-request SLA rate, its closure duration
as time to first response, or its old forecast MAPE as validation of this revision.

## Run locally

Use Python 3.11 or 3.12. Install the dependencies in a virtual environment:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/demo_warehouse.py
streamlit run app.py
```

On the verified Windows host, PyArrow 25.0.1 was blocked by application control;
PyArrow 19.0.1 imported successfully and was used for dashboard tests. If that
same environment issue occurs, use the tested version in your project environment:

```powershell
python -m pip install pyarrow==19.0.1
```

Load an explicit creation window; the end date is exclusive. The source may rate
limit requests. `SOCRATA_APP_TOKEN` is optional and is read from the environment.

```powershell
python scripts/fetch_and_build.py --start 2024-01-01 --end 2024-01-03 --output data/refreshed
$env:NYC311_DATA_DIR = "data/refreshed"
streamlit run app.py
```

An overlapping next load upserts existing IDs and adds new ones. `--refresh-open`
also refreshes older loaded creation days with open records:

```powershell
python scripts/fetch_and_build.py --start 2024-01-02 --end 2024-01-04 --refresh-open --output data/refreshed
```

For a historical backfill, run the desired older range again. After a failure,
reuse the printed run ID and **that run's exact start/end/page-size**:

```powershell
python scripts/fetch_and_build.py --start 2024-01-01 --end 2024-01-03 --page-size 1000 --resume-run RUN_ID --output data/refreshed
```

If an optional older-open refresh fails, its printed run has its own one-day
window. Resume that window, then rerun the intended reporting window. A completed
run ID is a no-op; use a new run (omit `--resume-run`) to observe later changes.

## Limits and next evidence

This is a single-operator local pipeline. The public source can change while
pages are read; it offers no snapshot isolation through this client. There is no
source deletion capture. Late historical inserts and updates to already closed
requests need explicit backfills; open-cohort refresh alone cannot find them.
Repeated source windows can contain records observed at different times. Open
counts describe latest observed statuses in loaded cohorts, not historical
point-in-time or citywide backlog. Local wall-clock closure differences do not
correct for daylight-saving transitions.

The next evidence step is a bounded real-window load with independent source
count reconciliation, later refresh comparison, and documented runtime/failure
behavior. Scheduling, managed deployment, alert-quality evaluation, and citywide
coverage remain future work.

## Resume-safe description

> Built a NYC 311 operations monitor with SQLite raw/staging/SQL mart layers,
> idempotent request upserts, resumable page checkpoints, and historical backfills;
> verified rollback, recovery, and status updates with synthetic tests and made
> request-volume and closure-time cohorts explicit.

Source: [NYC Open Data API documentation](https://dev.socrata.com/foundry/data.cityofnewyork.us/erm2-nwe9).
