import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from nyc311.analysis import build_analysis, write_outputs
from nyc311.demo import synthetic_rows

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_legacy_snapshot_displays_bias_warning_and_no_backlog_claim(self):
        with patch.dict(os.environ, {"NYC311_DATA_DIR": str(ROOT / "data/processed")}):
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Historical biased sample" in item.value for item in app.warning))
        open_metric = next(item for item in app.metric if item.label == "Observed open requests")
        self.assertEqual(open_metric.value, "Unavailable")

    def test_all_open_data_renders_null_closure_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            result = build_analysis(pd.DataFrame([synthetic_rows()[1]]))
            result["provenance"] = {"snapshot_type": "synthetic_only", "source": "unit test"}
            write_outputs(result, Path(directory))
            with patch.dict(os.environ, {"NYC311_DATA_DIR": directory}):
                app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            median = next(item for item in app.metric if item.label == "Median closure time")
            self.assertEqual(median.value, "N/A")
            self.assertTrue(any("loaded creation-date cohorts" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
