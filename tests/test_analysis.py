import unittest

import pandas as pd

from nyc311.analysis import MonitorConfig, build_analysis, clean_requests


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


if __name__ == "__main__":
    unittest.main()
