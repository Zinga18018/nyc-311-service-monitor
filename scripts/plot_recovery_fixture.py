"""Plot recorded synthetic recovery counts, without ingestion or live API calls."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/synthetic_warehouse_demo.json"
OUTPUT = ROOT / "docs/images/recovery-fixture.svg"
SOURCE_SHA256 = "8971ebb9f9f9107d387b1cdefc019b7851df81db0d0d2d726e7cbd6aa7b8efaa"
CHECKPOINTS = [
    ("after_failure", "After failure"),
    ("after_reopen_and_resume", "Reopen +\nresume"),
    ("after_unchanged_replay", "Unchanged\nreplay"),
    ("after_late_record_backfill_and_closure_refresh", "Update +\nbackfill"),
]


def checked_data(source=SOURCE):
    raw = Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Recorded source bytes changed (including line endings); review before updating the plot.")
    result = json.loads(raw)
    if result["provenance"] != "synthetic_only; no live API calls" or not result["assertions_passed"]:
        raise ValueError("Expected verified synthetic fixture evidence.")
    if result["initial_fixture_records"] != 6 or result["fixture"] != "nyc311/demo.py::synthetic_rows":
        raise ValueError("Unexpected fixture identity.")
    rows = [result[key] for key, _ in CHECKPOINTS]
    counts = [[row[column] for row in rows] for column in ("current_requests", "raw_versions")]
    if counts != [[2, 6, 6, 8], [2, 6, 6, 9]]:
        raise ValueError("Unexpected recovery checkpoints.")
    if any(type(value) is not int or value < 0 for row in rows for value in row.values()):
        raise ValueError("Expected nonnegative integer fixture counts.")
    return result


def render(png=None, png_width=1024):
    result = checked_data()
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "nyc311-plot-mpl"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if matplotlib.__version__ != "3.10.8":
        raise RuntimeError("Install requirements-visuals.txt for exact plot reproduction.")
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11,
                         "svg.fonttype": "none", "svg.hashsalt": "nyc311-recovery-fixture-v1",
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.spines.left": False}):
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        fig.subplots_adjust(left=.26, right=.96, bottom=.14, top=.79)
        fig.suptitle("Synthetic warehouse recovery", fontsize=13, y=.97)
        for offset, column, label, color in [
            (-.17, "current_requests", "Current requests", "#32648e"),
            (.17, "raw_versions", "Raw versions", "#ae612d"),
        ]:
            values = [result[key][column] for key, _ in CHECKPOINTS]
            bars = ax.barh([i + offset for i in range(4)], values, height=.29,
                           label=label, color=color, zorder=3)
            ax.bar_label(bars, padding=4, fontsize=11)
        ax.set_yticks(range(4), [label for _, label in CHECKPOINTS])
        ax.invert_yaxis()
        ax.tick_params(axis="y", length=0, pad=10)
        ax.set(xlim=(0, 10), xticks=[0, 2, 4, 6, 8, 10], xlabel="Recorded count")
        ax.grid(axis="x", color="#e5e5e5", linewidth=.7)
        ax.set_axisbelow(True)
        ax.legend(loc="lower left", bbox_to_anchor=(-.04, 1.01), ncol=2,
                  frameon=False, fontsize=10, handlelength=1.3, columnspacing=1.2)
        buf = io.StringIO()
        fig.savefig(buf, format="svg", metadata={"Date": None}, facecolor="white")
        if png:
            Path(png).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(png, dpi=png_width / 6.6, facecolor="white")
        plt.close(fig)
    svg = buf.getvalue().replace('<svg ', '<svg role="img" aria-labelledby="title desc" ', 1)
    match = re.search(r"<svg\b[^>]*>", svg)
    description = ('<title id="title">Synthetic warehouse recovery checkpoints</title>'
                   '<desc id="desc">Failure, resume, unchanged replay, and update plus backfill '
                   'produce current-request counts 2, 6, 6, 8 and raw-version counts 2, 6, 6, 9. '
                   'Six initial synthetic records, then two additions and one changed record. '
                   'Not NYC service performance, backlog or load testing. '
                   'Source SHA-256: ' + SOURCE_SHA256 + '.</desc>')
    svg = svg[:match.end()] + description + svg[match.end():]
    ET.fromstring(svg)
    return svg.encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare an exact rerender to the checked-in SVG")
    parser.add_argument("--data-only", action="store_true", help="Check pinned source and counts using only the standard library")
    parser.add_argument("--png", type=Path, help="Optional local QA render; not needed by the README")
    parser.add_argument("--png-width", type=int, default=1024)
    args = parser.parse_args()
    if args.png_width < 1:
        parser.error("--png-width must be positive")
    if args.data_only:
        checked_data()
        print("PASS: exact source hash, synthetic identity and four recovery checkpoints")
        return
    svg = render(args.png, args.png_width)
    if args.check:
        if OUTPUT.read_bytes() != svg:
            raise ValueError("Checked-in SVG differs from an exact rerender.")
        print("PASS: pinned fixture and byte-identical Matplotlib SVG")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(svg)
        print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
