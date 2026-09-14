# Metric dictionary and decision guide

All new dashboard metrics cover records loaded for the selected **creation-date
window**, with inclusive start and exclusive end. The warehouse readout covers
all stored windows and is separately labeled. Source dates are floating local
wall times; durations are not adjusted for daylight-saving changes.

| Metric | Definition and denominator | What it supports |
|---|---|---|
| Requests | Count of current unique request IDs in the loaded creation cohort, all statuses | Compare recorded demand across loaded days/queues |
| Observed open requests | Count whose latest observed status is not Closed, including unknown status | Select queues to investigate; unknown statuses need review |
| Closed requests | Count whose latest observed status is Closed | Explain status composition, even when closure dates are unreliable |
| Valid closed requests | Closed status and a known closure date at or after creation | Denominator for all closure-duration summaries |
| Median / p90 closure hours | Median / 90th percentile of valid closed durations; no upper trimming | Describe the closed cohort's center and long tail |
| Mean closure hours | SQL average over valid closed durations | SQL readout summary; not interchangeable with the dashboard median |
| Closed within 48h rate | Valid closed durations <=48 hours / valid closed requests | Compare an explicit conditional closure metric; not an all-request SLA |
| Quality-flagged requests | Records with a closure/status inconsistency or unknown status | Identify data issues before drawing service conclusions |
| Forecast MAE | Mean absolute request-count error on holdout days | Interpret error in request units |
| Forecast MAPE | Mean absolute percentage error on holdout days with positive actual demand | Relative error; zero-demand exclusions are separately counted |
| Flagged days | Holdout days beyond the configured absolute residual score threshold | Exploratory investigation queue; not proven incident detection |

No valid closed records means closure statistics are **null / N/A**, not zero.
Open rows never enter the closed-within-48h denominator. Closed records with bad
timestamps remain in volume and status counts but are excluded from duration
metrics and receive quality flags in staging. Unknown status is conservatively
counted as not closed and explicitly flagged. A nonclosed status with a closed
date is also flagged; status drives the open classification.

The internal columns response_hours, median_response_hours, and within_48h_rate
remain for compatibility with the stored files. Their meaning in this revision
is **recorded closure duration**, not time to first response.

## Warehouse layers

| Layer | Grain | Update behavior |
|---|---|---|
| ingestion_runs | One explicit source/window attempt | Status, query metadata, current cursor and committed row/page counts |
| ingestion_pages | One committed page in one run | Creation day, incoming cursor, received rows and observation time |
| raw_request_versions | Request ID + SHA-256 of canonical original payload | Insert once per distinct observed version |
| raw_observations | Run + page + request ID | Records which source version was observed in each committed page |
| stg_requests | One latest observed request ID | Upsert changed dates/status/dimensions; retain quality flags |
| mart_daily_operations | Creation day | SQL view over current staging rows |
| mart_agency_operations | Agency | SQL view with all-request and closed-duration denominators |

The raw version, page ledger, stage row, observation, and restart cursor commit
together. A page error rolls back all of them. Earlier pages remain durable.
Observations can increase on an unchanged refresh while current row and raw
version counts remain stable. Raw versions are observation history, not a
complete source change-data-capture stream.

## Forecast and uncertainty

The training window contains up to the configured number of initial days, leaving
up to seven days aside when the available window is short. The output records
each row's evaluation_split and the actual train/holdout counts. Weekday means
and residual median/scale use training data only. Unseen weekdays fall back to
the training mean. With no holdout, MAE/MAPE are null. A zero-demand holdout day
still enters MAE; its percentage error is undefined and excluded from MAPE.

The residual score uses median absolute deviation, then training standard
deviation if MAD is zero, then a one-request scale if both are zero. This fallback
is explicit but is not a calibrated probability. No confidence intervals,
incident labels, prospective validation, or forecast superiority are claimed.

## Decision example from the synthetic demonstration

The initial SQL readout has three NYPD fixture records: two open and one closed
with an invalid duration. Its closure mean and 48-hour rate are null. The useful
action is to investigate open work and the date inconsistency; it would be wrong
to interpret the null as excellent service speed or a zero closure rate.

The DEP fixture has two valid durations (2 and 1,200 hours) and one closed record
without a closure date. Its mean is 601 hours and its conditional 48-hour rate is
1/2. Keeping the long-duration record exposes the tail that the former 45-day
filter hid. These are **hand-authored examples, not findings about either agency**.

For real recommendations, first reconcile source coverage and freshness, compare
like complaint types and creation cohorts, and inspect status/date quality.
An agency's larger open count can reflect demand or complaint mix; it does not
by itself establish understaffing or poorer performance.
