"""Independent re-derivation of headline counts from the originals.

Re-opens each ``data/original/<file>.xlsx`` without going through
:mod:`scripts.loader` (uses a simpler raw row count) and compares the result
to the cleaned wide CSV. Writes ``data/audit/reconcile.json`` and
``data/audit/reconcile.md``.

Mismatches are surfaced loudly; the script exits non-zero on any regression.
The Boulder County Clerk does not publish per-ballot-style counts in a
machine-readable format alongside the redacted CVRs, so the checks here are
intentionally weaker than a per-contest vote-total reconciliation: row counts,
redaction counts, and an upper bound on the city-ballot count (cannot exceed
the raw row count minus aggregates).

For a stronger reconciliation, point this script at the official Statement of
Votes XLSX once the County publishes per-precinct city ballot counts for the
year in question.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import AUDIT_DIR, ORIGINAL_DIR, PROCESSED_DIR, ensure_dirs
from .sources import SOURCES


def _independent_raw_row_count(path: Path) -> int:
    """Count ballot rows in the original XLSX without the parser.

    Reads with ``header=None`` and counts rows after the 4-row prelude.
    """
    raw = pd.read_excel(path, header=None)
    return max(0, len(raw) - 4)


def reconcile(verbose: bool = True) -> dict:
    ensure_dirs()
    summary_csv = PROCESSED_DIR / "_summary.csv"
    if not summary_csv.exists():
        raise SystemExit(
            "data/processed/_summary.csv not found; run `python -m scripts.clean`"
        )
    summary = pd.read_csv(summary_csv).set_index("election_key")

    rows: list[dict] = []
    has_regression = False
    for src in SOURCES:
        orig = ORIGINAL_DIR / src.filename
        if not orig.exists():
            rows.append({
                "election_key": src.election_key,
                "status":       "skip-no-original",
                "raw_row_count": None,
                "pipeline_n_raw_rows": None,
                "delta_raw": None,
                "n_sheets": None,
                "n_voters": None,
            })
            continue
        if verbose:
            print(f"  reconciling {src.election_key}...", flush=True)
        raw_count = _independent_raw_row_count(orig)
        pipeline_n_raw = int(summary.loc[src.election_key, "n_raw_rows"])
        delta = raw_count - pipeline_n_raw
        n_sheets = int(summary.loc[src.election_key, "n_sheets_after_redaction"])
        n_voters = int(summary.loc[src.election_key, "n_voters"])
        n_redacted = int(summary.loc[src.election_key, "n_redacted_dropped"])

        status = "ok"
        if delta != 0:
            status = "MISMATCH-raw-row-count"
            has_regression = True
        if n_sheets + n_redacted > raw_count:
            status = "MISMATCH-sheets-plus-redacted-exceeds-raw"
            has_regression = True
        if n_voters > n_sheets:
            status = "MISMATCH-voters-exceeds-sheets"
            has_regression = True

        rows.append({
            "election_key":        src.election_key,
            "status":              status,
            "raw_row_count":       raw_count,
            "pipeline_n_raw_rows": pipeline_n_raw,
            "delta_raw":           delta,
            "n_sheets":            n_sheets,
            "n_voters":            n_voters,
            "n_redacted_dropped":  n_redacted,
        })

    report = {"rows": rows, "has_regression": has_regression}
    (AUDIT_DIR / "reconcile.json").write_text(json.dumps(report, indent=2) + "\n")

    md_lines = [
        "# Reconcile report\n",
        "Cross-check of per-election raw row counts between the pipeline "
        "output (`data/processed/_summary.csv`) and an independent row count "
        "of the originals.\n",
        "| Election | status | raw rows | pipeline n_raw | Δ | sheets | voters | redacted |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        md_lines.append(
            f"| {r['election_key']} | {r['status']} | "
            f"{r['raw_row_count']} | {r['pipeline_n_raw_rows']} | "
            f"{r['delta_raw']} | {r['n_sheets']} | {r['n_voters']} | "
            f"{r['n_redacted_dropped']} |"
        )
    md_lines.append("")
    (AUDIT_DIR / "reconcile.md").write_text("\n".join(md_lines) + "\n")
    if verbose:
        print(f"  wrote {AUDIT_DIR/'reconcile.md'}")

    if has_regression:
        print("RECONCILE REGRESSION — see data/audit/reconcile.md",
              file=sys.stderr)
        raise SystemExit(1)
    return report


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.reconcile", description=__doc__)
    p.add_argument("--quiet", "-q", action="store_true")
    a = p.parse_args(argv)
    reconcile(verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
