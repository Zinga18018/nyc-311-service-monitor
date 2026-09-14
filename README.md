# NYC 311 Service Monitor

[See the workflow flowchart and code walkthrough](WORKFLOW.md)

This is a Streamlit data science app built on NYC Open Data 311 service
requests. It looks at request volume, response time, top complaint types,
borough/agency patterns, and unusual demand spikes.

I built it because it is a practical city-operations problem: when do requests
spike, which issues dominate, and how quickly are they handled?

## Data source

- Dataset: NYC Open Data, 311 Service Requests from 2020 to Present
- API endpoint: `https://data.cityofnewyork.us/resource/erm2-nwe9.csv`
- Window used for the checked sample: January 1, 2024 through March 31, 2024

The repo stores processed aggregate outputs. The fetch script can rebuild them
from the public API.

## What the app shows

- Daily request volume with a weekly baseline forecast.
- Volume anomaly days from forecast residuals.
- Median and p90 response time.
- Share of sampled requests closed within 48 hours.
- Top complaint types, boroughs, and agencies by request count and response time.

## Verified build snapshot

Generated with:

```powershell
python scripts\fetch_and_build.py
```

Observed output:

```text
downloaded_rows=31850
daily_count_days=91
rows_analyzed=30626
days=91
median_response_hours=1.42
forecast_mape=0.058
anomaly_days=4
```

From `outputs/metrics.json`:

- Rows analyzed after cleaning: `30,626`
- True daily-count window: `91` days
- Agencies: `14`
- Complaint types: `117`
- Median response time: `1.42` hours
- p90 response time: `67.82` hours
- Within-48-hour closure rate: `86.37%`
- Weekly-baseline forecast MAPE: `5.8%`
- Volume anomaly days: `4`

## Run locally

```powershell
pip install -r requirements.txt
python scripts\fetch_and_build.py
streamlit run app.py
```

## Test

```powershell
python -m unittest discover -s tests
```

Current local result:

```text
Ran 2 tests
OK
```

## Resume-safe wording

> Built a Streamlit service-operations monitor using NYC 311 Open Data, analyzing
> 30,626 cleaned service requests and 91 days of true daily request counts for
> response-time patterns, top complaint types, borough/agency summaries, weekly
> baseline forecasting, and anomaly flags.

Avoid claiming this is a production city system. It is a public-data portfolio
project.
