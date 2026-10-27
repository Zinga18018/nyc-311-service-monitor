"""Standard-library checks for the optional README plot; no Matplotlib import."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/plot_recovery_fixture.py"
SPEC = importlib.util.spec_from_file_location("readme_plot", SCRIPT)
PLOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLOT)


class ReadmePlotTests(unittest.TestCase):
    def test_source_hash_matches_pinned_committed_bytes(self):
        self.assertEqual(hashlib.sha256(PLOT.SOURCE.read_bytes()).hexdigest(), PLOT.SOURCE_SHA256)

    def test_recorded_values_and_identity_are_validated(self):
        record = PLOT.checked_data()
        self.assertEqual(record["initial_fixture_records"], 6)

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_bytes(PLOT.SOURCE.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "source bytes changed"):
                PLOT.checked_data(path)

    def test_empty_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            path.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                PLOT.checked_data(path)

    def test_svg_has_accessible_pinned_source_and_no_scripts(self):
        root = ET.fromstring(PLOT.OUTPUT.read_bytes())
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        self.assertEqual(root.attrib["role"], "img")
        self.assertEqual(root.attrib["aria-labelledby"], "title desc")
        self.assertIsNotNone(root.find("svg:title", namespace))
        self.assertIn(PLOT.SOURCE_SHA256, root.find("svg:desc", namespace).text)
        self.assertEqual(root.findall(".//svg:script", namespace), [])
        self.assertEqual(root.findall(".//svg:image", namespace), [])

    def test_data_check_needs_only_standard_library(self):
        result = subprocess.run([sys.executable, "-S", str(SCRIPT), "--data-only"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS:", result.stdout)


if __name__ == "__main__":
    unittest.main()

