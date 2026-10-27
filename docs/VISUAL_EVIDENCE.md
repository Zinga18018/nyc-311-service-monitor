# README plot evidence

## Source and meaning

The figure reads only `outputs/synthetic_warehouse_demo.json` from base commit
`181ef39d82501edc1fae51f7039b5f81ae84119a`.

- Git blob: `52edbdec62fc01160edd458ec9c5dc472aa690e2`.
- SHA-256 of the actual committed LF bytes:
  `8971ebb9f9f9107d387b1cdefc019b7851df81db0d0d2d726e7cbd6aa7b8efaa`.
- Source fixture: `nyc311/demo.py::synthetic_rows`; six initial hand-authored records.
- Failure, reopen/resume, unchanged replay, update/backfill produce current-request
  counts **2, 6, 6, 8** and retained-version counts **2, 6, 6, 9**.

The bars are separate counts, not additive categories. The fourth checkpoint
adds two requests and changes one existing request. This demonstrates recovery
and replay behavior on a small engineering fixture. It is not NYC demand,
service performance, citywide backlog, throughput or a scale benchmark.

## Reproduce without fetching requests

The data check and six plot unit tests use only the Python standard library:

```sh
python -S scripts/plot_recovery_fixture.py --data-only
python -S -m unittest discover -s tests -p test_readme_plot.py -v
```

Optional rendering uses a separate dependency; it is not required by the app or
ordinary test discovery:

```sh
python -m pip install -r requirements-visuals.txt
python scripts/plot_recovery_fixture.py
python scripts/plot_recovery_fixture.py --check
```

The first command writes `docs/images/recovery-fixture.svg`; `--check` rerenders
in memory and compares exact bytes. Matplotlib 3.10.8, DejaVu Sans, a fixed SVG
hash salt and omitted date metadata make this deterministic in the checked
environment. `--png path.png --png-width 390` produces an optional local QA
render of the same figure. PNG previews are not required repository assets.

The script rejects a changed source hash, including changed line endings. Use
the source's committed LF bytes for this frozen illustration; review any source
update before deliberately changing the pinned hash and regenerating the plot.
It never imports the ingestion code or runs the live API.

## Historical hash discrepancy—not repaired by this change

The five hashes in the existing
[legacy snapshot provenance](../data/processed/snapshot_provenance.json) match
**CRLF re-encodings** of the stored files, not their committed LF bytes. The
numerical content is the same under that conversion. This was verified for
`metrics.json`, `daily_volume_forecast.csv`, `top_complaints.csv`,
`top_boroughs.csv` and `top_agencies.csv`. Both the legacy artifacts and their
historical provenance files remain unchanged. The new figure uses the actual
committed-byte SHA-256 shown above, not those historical hashes.

## Checks performed for the README change

- Four checkpoint values, synthetic provenance, source hash and accessible SVG
  checked by six standard-library tests.
- Exact rerender repeated successfully; changed source and changed SVG rejected.
- Native-width and 390-pixel PNGs inspected for labels, spacing and clipping.
- Existing analysis/warehouse tests: 20 passed. The offline demo reproduced all
  recorded fields except its current timestamp.
- Dashboard tests were **not verified locally**: Streamlit and PyArrow were absent.
  Full discovery therefore fails at the dashboard-module import; this is not a
  full-suite pass. No live ingestion, browser, deployment or scale test was run.

