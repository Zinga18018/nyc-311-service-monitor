PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running', 'failed', 'completed')),
    metadata_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    next_day TEXT NOT NULL,
    cursor_created TEXT,
    cursor_key TEXT,
    pages_committed INTEGER NOT NULL DEFAULT 0,
    rows_observed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

-- Immutable versions retain original source values and change history.
CREATE TABLE IF NOT EXISTS ingestion_pages (
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    page_number INTEGER NOT NULL,
    creation_day TEXT NOT NULL,
    cursor_created_before TEXT,
    cursor_key_before TEXT,
    rows_received INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, page_number)
);

CREATE TABLE IF NOT EXISTS raw_request_versions (
    unique_key TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    PRIMARY KEY (unique_key, payload_sha256)
);
CREATE TABLE IF NOT EXISTS raw_observations (
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    page_number INTEGER NOT NULL,
    unique_key TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, page_number, unique_key),
    FOREIGN KEY (unique_key, payload_sha256)
        REFERENCES raw_request_versions(unique_key, payload_sha256)
);

-- Latest observed state, keyed by the source request ID.
CREATE TABLE IF NOT EXISTS stg_requests (
    unique_key TEXT PRIMARY KEY,
    created_date TEXT NOT NULL,
    closed_date TEXT,
    agency TEXT NOT NULL,
    complaint_type TEXT NOT NULL,
    borough TEXT NOT NULL,
    status TEXT NOT NULL,
    is_open INTEGER NOT NULL CHECK (is_open IN (0, 1)),
    response_hours REAL,
    quality_issue TEXT,
    payload_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    FOREIGN KEY (unique_key, payload_sha256)
        REFERENCES raw_request_versions(unique_key, payload_sha256)
);
CREATE INDEX IF NOT EXISTS idx_stg_created_date ON stg_requests(created_date);

CREATE VIEW IF NOT EXISTS mart_daily_operations AS
SELECT substr(created_date, 1, 10) AS created_day,
       COUNT(*) AS requests,
       SUM(is_open) AS open_requests,
       SUM(1 - is_open) AS closed_requests,
       COUNT(response_hours) AS valid_closed_requests,
       SUM(CASE WHEN quality_issue IS NOT NULL THEN 1 ELSE 0 END) AS quality_flagged_requests,
       AVG(response_hours) AS mean_closure_hours,
       SUM(CASE WHEN response_hours <= 48 THEN 1 ELSE 0 END) * 1.0 /
           NULLIF(COUNT(response_hours), 0) AS closed_within_48h_rate
FROM stg_requests GROUP BY substr(created_date, 1, 10);

CREATE VIEW IF NOT EXISTS mart_agency_operations AS
SELECT agency, COUNT(*) AS requests, SUM(is_open) AS open_requests,
       SUM(1 - is_open) AS closed_requests,
       COUNT(response_hours) AS valid_closed_requests,
       SUM(CASE WHEN quality_issue IS NOT NULL THEN 1 ELSE 0 END) AS quality_flagged_requests,
       AVG(response_hours) AS mean_closure_hours,
       SUM(CASE WHEN response_hours <= 48 THEN 1 ELSE 0 END) * 1.0 /
           NULLIF(COUNT(response_hours), 0) AS closed_within_48h_rate
FROM stg_requests GROUP BY agency;
