import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from nyc311.analysis import MonitorConfig, build_analysis, clean_requests, daily_volume, flag_anomalies, weekly_baseline_forecast, write_outputs
from nyc311.demo import synthetic_rows


class AnalysisTests(unittest.TestCase):
    def sample(self) -> pd.DataFrame:
        rows = []
        for day in range(1, 22):
            for index in range(5 + (day % 4)):
                rows.append(
                    {
                        "created_date": f"2024-01-{day:02d}T08:00:00",
                        "closed_date": f"2024-01-{day:02d}T{10 + (index % 8):02d}:00:00",
                        "agency": "DEP" if index % 2 else "NYPD",
                        "complaint_type": "Noise" if index % 2 else "Water",
                        "borough": "BROOKLYN" if day % 2 else "QUEENS",
                        "status": "Closed",
                    }
                )
        return pd.DataFrame(rows)

    def test_clean_requests_adds_response_hours(self):
        clean = clean_requests(self.sample())

        self.assertIn("response_hours", clean.columns)
        self.assertGreater(len(clean), 100)
        self.assertTrue((clean["response_hours"] >= 0).all())

    def test_build_analysis_outputs_core_tables(self):
        result = build_analysis(self.sample(), MonitorConfig(train_days=10))

        self.assertIn("summary", result)
        self.assertIn("daily", result)
        self.assertIn("top_complaints", result)
        self.assertGreater(result["summary"]["rows_analyzed"], 100)
        self.assertGreaterEqual(result["summary"]["days"], 20)

    def test_open_and_invalid_closures_keep_volume_and_long_tail_is_retained(self):
        result = build_analysis(pd.DataFrame(synthetic_rows()))
        summary = result["summary"]
        self.assertEqual(summary["rows_analyzed"], 6)
        self.assertEqual(summary["open_requests"], 2)
        self.assertEqual(summary["valid_closed_requests"], 2)
        self.assertEqual(summary["closed_without_valid_duration"], 2)
        self.assertEqual(summary["median_response_hours"], 601)
        self.assertEqual(summary["within_48h_rate"], .5)
        self.assertEqual(result["daily"]["requests"].tolist(), [4, 2])

    def test_all_open_window_has_null_closure_metrics(self):
        frame = pd.DataFrame([synthetic_rows()[1]])
        result = build_analysis(frame)
        self.assertIsNone(result["summary"]["within_48h_rate"])
        self.assertIsNone(result["summary"]["median_response_hours"])
        with tempfile.TemporaryDirectory() as directory:
            write_outputs(result, Path(directory))
            metrics = json.loads((Path(directory) / "metrics.json").read_text())
            self.assertIsNone(metrics["p90_response_hours"])

    def test_complete_calendar_keeps_zero_demand_days(self):
        result = build_analysis(pd.DataFrame(synthetic_rows()), start=date(2024, 1, 1), end=date(2024, 1, 4))
        self.assertEqual(result["daily"]["requests"].tolist(), [4, 2, 0])
        self.assertEqual(result["summary"]["mape_excluded_zero_demand_days"], 1)

    def test_empty_completed_window_is_valid_without_nan_json(self):
        frame = pd.DataFrame(columns=self.sample().columns)
        result = build_analysis(frame, start=date(2024, 1, 1), end=date(2024, 1, 4))
        self.assertEqual(result["summary"]["rows_analyzed"], 0)
        self.assertEqual(result["daily"]["requests"].tolist(), [0, 0, 0])
        json.dumps(result["summary"], allow_nan=False)

    def test_aggregate_only_days_are_not_dropped(self):
        clean = clean_requests(pd.DataFrame([synthetic_rows()[0]]))
        counts = pd.DataFrame({"created_day": ["2024-01-01", "2024-01-02"], "requests": [10, 30]})
        daily = daily_volume(clean, counts)
        self.assertEqual(daily["requests"].tolist(), [10, 30])

    def test_unknown_aggregate_day_is_not_filled_as_zero(self):
        clean = clean_requests(pd.DataFrame(synthetic_rows()))
        counts = pd.DataFrame({"created_day": ["2024-01-01"], "requests": [10]})
        with self.assertRaisesRegex(ValueError, "cover every observed day"):
            daily_volume(clean, counts)

    def test_holdout_spike_cannot_change_training_calibration(self):
        daily = pd.DataFrame({"created_day": pd.date_range("2024-01-01", periods=21),
                              "requests": [10 + index % 3 for index in range(21)]})
        daily["weekday"] = daily["created_day"].dt.day_name()
        forecast = weekly_baseline_forecast(daily, 14)
        original = flag_anomalies(forecast, 3)
        changed = forecast.copy()
        changed.loc[20, "requests"] = 1_000_000
        rescored = flag_anomalies(changed, 3)
        pd.testing.assert_series_equal(original.loc[:19, "volume_z_score"], rescored.loc[:19, "volume_z_score"])
        self.assertEqual((forecast["evaluation_split"] == "holdout").sum(), 7)


if __name__ == "__main__":
    unittest.main()
