-- Queue for an analyst to investigate; comparisons need complaint-mix context.
-- Loaded cohorts only. Open count is latest observed status, not historical backlog.
SELECT agency, requests, open_requests, valid_closed_requests,
       quality_flagged_requests,
       ROUND(mean_closure_hours, 2) AS mean_closure_hours,
       ROUND(closed_within_48h_rate, 4) AS closed_within_48h_rate
FROM mart_agency_operations
ORDER BY open_requests DESC, quality_flagged_requests DESC, agency;
