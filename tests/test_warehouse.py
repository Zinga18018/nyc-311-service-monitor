import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nyc311.demo import fixture_fetcher, run_demo, synthetic_rows, warehouse_counts
from nyc311.warehouse import connect, ingest_window, normalize_request, open_cohort_days
from scripts.fetch_and_build import build_url


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "test.sqlite")
        self.start, self.end = date(2024, 1, 1), date(2024, 1, 3)
        self.args = dict(source="synthetic://unit-test", provenance="synthetic", page_size=2)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def load(self, rows=None, **kwargs):
        return ingest_window(self.connection, fixture_fetcher(rows if rows is not None else synthetic_rows()),
                             self.start, self.end, **self.args, **kwargs)

    def test_paginates_past_daily_limit_and_keeps_open_and_long_closures(self):
        self.load()
        counts = warehouse_counts(self.connection)
        self.assertEqual(counts, dict(current_requests=6, raw_versions=6, open_requests=2, valid_closed_requests=2))
        self.assertEqual(self.connection.execute("SELECT response_hours FROM stg_requests WHERE unique_key='103'").fetchone()[0], 1200)
        daily = self.connection.execute("SELECT * FROM mart_daily_operations WHERE created_day='2024-01-01'").fetchone()
        self.assertEqual((daily["requests"], daily["open_requests"], daily["valid_closed_requests"]), (4, 1, 2))
        self.assertEqual(daily["closed_within_48h_rate"], .5)

    def test_replay_does_not_duplicate_facts_or_versions(self):
        self.load()
        self.load()
        self.assertEqual(warehouse_counts(self.connection)["raw_versions"], 6)
        self.assertEqual(warehouse_counts(self.connection)["current_requests"], 6)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0], 12)

    def test_changed_status_updates_fact_and_preserves_raw_history(self):
        rows = synthetic_rows()
        self.load(rows)
        rows[1].update(status="Closed", closed_date="2024-01-03T09:00:00")
        self.load(rows)
        self.assertEqual(warehouse_counts(self.connection)["raw_versions"], 7)
        self.assertEqual(warehouse_counts(self.connection)["open_requests"], 1)
        self.assertEqual(open_cohort_days(self.connection), [date(2024, 1, 2)])

    def test_page_failure_rolls_back_raw_stage_and_checkpoint_then_resumes(self):
        calls = 0
        def fail():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated crash")
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            self.load(before_checkpoint=fail)
        run = self.connection.execute("SELECT * FROM ingestion_runs").fetchone()
        self.assertEqual((run["status"], run["pages_committed"], run["rows_observed"]), ("failed", 1, 2))
        self.assertEqual(warehouse_counts(self.connection)["raw_versions"], 2)
        self.assertEqual(warehouse_counts(self.connection)["current_requests"], 2)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0], 1)
        self.load(resume_run=run["run_id"])
        self.assertEqual(warehouse_counts(self.connection)["current_requests"], 6)

    def test_source_failure_keeps_checkpoint_for_resume(self):
        calls = 0
        fetch = fixture_fetcher(synthetic_rows())
        def interrupted(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ConnectionError("source unavailable")
            return fetch(*args)
        with self.assertRaises(ConnectionError):
            ingest_window(self.connection, interrupted, self.start, self.end, **self.args)
        run = self.connection.execute("SELECT * FROM ingestion_runs").fetchone()
        self.assertEqual(run["cursor_key"], "102")
        self.load(resume_run=run["run_id"])
        self.assertEqual(warehouse_counts(self.connection)["current_requests"], 6)

    def test_completed_resume_is_noop_and_changed_metadata_rejected(self):
        run = self.load()
        before = self.connection.total_changes
        self.load(resume_run=run)
        self.assertEqual(self.connection.total_changes, before)
        with self.assertRaisesRegex(ValueError, "changed"):
            ingest_window(self.connection, fixture_fetcher([]), self.start, date(2024, 1, 4), resume_run=run, **self.args)

    def test_nonadvancing_source_fails_instead_of_looping(self):
        rows = synthetic_rows()[:2]
        with self.assertRaisesRegex(ValueError, "advance cursor"):
            ingest_window(self.connection, lambda *args: rows, self.start, self.end, **self.args)
        self.assertEqual(warehouse_counts(self.connection)["current_requests"], 2)

    def test_query_keeps_all_statuses_and_uses_unique_key_tiebreaker(self):
        query = parse_qs(urlparse(build_url(self.start, self.end, 2, ("2024-01-01T09:00:00", "102"))).query)
        self.assertNotIn("closed_date", query["$where"][0])
        self.assertIn("unique_key > '102'", query["$where"][0])
        self.assertEqual(query["$order"], ["created_date ASC, unique_key ASC"])
        self.assertIn("unique_key", query["$select"][0])

    def test_bad_closure_flagged_without_losing_demand_record(self):
        row = synthetic_rows()[0]
        row["closed_date"] = "invalid"
        normalized = normalize_request(row)
        self.assertEqual(normalized["quality_issue"], "invalid_closed_date")
        self.assertIsNone(normalized["response_hours"])
        self.assertEqual(normalized["is_open"], 0)

    def test_tied_timestamps_use_source_text_key_order(self):
        rows = [{**synthetic_rows()[0], "unique_key": key} for key in ("2", "10", "9")]
        self.load(rows)
        keys = [row[0] for row in self.connection.execute(
            "SELECT unique_key FROM raw_observations ORDER BY page_number, unique_key")]
        self.assertEqual(keys, ["10", "2", "9"])

    def test_synthetic_end_to_end_backfill_and_recovery_proof(self):
        report = run_demo()
        self.assertTrue(report["assertions_passed"])
        self.assertEqual(report["after_late_record_backfill_and_closure_refresh"]["current_requests"], 8)


if __name__ == "__main__":
    unittest.main()
