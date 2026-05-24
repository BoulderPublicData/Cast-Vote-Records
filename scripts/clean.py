"""Orchestrator: runs each :class:`scripts.sources.CvrSource` through the
loader + cleaner (drop redacted, combine multi-sheet ballots into per-voter
rows), validates against :mod:`scripts.schema`, and writes per-election wide
CSVs plus a project-wide provenance sidecar to ``data/processed/``.

Outputs:

* ``data/processed/<election_key>-county-wide-by-voter.csv`` — one per
  election, one row per **voter** (multi-sheet ballots merged), all ballots
  in the county (no jurisdiction filter).
* ``data/processed/provenance.csv`` — one row per processed artifact with
  source URL, retrieved-at time, SHA-256, output path, row counts.
* ``data/processed/_summary.csv`` — bookkeeping (n raw, n redacted,
  n sheets, n voters, multi-sheet ballot types, sheet-count distribution).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Iterable

import pandas as pd

from .cleaner import clean_countywide
from .config import (
    ORIGINAL_DIR,
    PROCESSED_DIR,
    PROVENANCE_CSV,
    SUMMARY_CSV,
    ensure_dirs,
)
from .fetch import load_manifest
from .loader import load_raw_cvr
from .schema import validate_id_block
from .sources import SOURCES, get_source


def _wide_csv_path(election_key: str):
    return PROCESSED_DIR / f"{election_key}-county-wide-by-voter.csv"


def clean(
    elections: Iterable[str] = (),
    *,
    fail_on_empty: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Run the cleaner on every election (or a subset).

    Parameters
    ----------
    elections
        Iterable of election-key strings. Empty (default) means every entry
        in :data:`scripts.sources.SOURCES`.
    fail_on_empty
        If ``True``, raise ``SystemExit(1)`` when the whole pipeline produces
        zero voter rows across every output.

    Returns
    -------
    pandas.DataFrame
        The summary table (one row per processed election).
    """
    ensure_dirs()
    manifest = load_manifest()
    targets = (
        tuple(SOURCES) if not elections
        else tuple(get_source(k) for k in elections)
    )

    summary_rows: list[dict] = []
    provenance_rows: list[dict] = []
    n_total_voters = 0
    all_warnings: list[str] = []

    for src in targets:
        raw_path = ORIGINAL_DIR / src.filename
        if not raw_path.exists():
            if verbose:
                print(f"  [skip] {src.election_key}: {raw_path} not found", flush=True)
            continue

        if verbose:
            size_mb = raw_path.stat().st_size / 1e6
            print(f"  loading {src.election_key} ({size_mb:.1f} MB)...", flush=True)

        raw = load_raw_cvr(raw_path)
        res = clean_countywide(raw, election_key=src.election_key)
        out_path = _wide_csv_path(src.election_key)

        if res.n_voters == 0:
            if verbose:
                print(
                    f"  [empty] {src.election_key}: 0 voters after dropping "
                    f"redacted rows",
                    flush=True,
                )
        else:
            validate_id_block(res.cleaned)
            res.cleaned.to_csv(out_path, index=False)
            n_total_voters += res.n_voters
            if verbose:
                dist = ", ".join(f"{k}-sheet:{v:,}" for k, v
                                 in sorted(res.sheet_count_distribution.items()))
                print(
                    f"  [ok]   {src.election_key}: "
                    f"{res.n_sheets_after_redaction:,} sheets → "
                    f"{res.n_voters:,} voters × "
                    f"{res.n_choice_columns} choice cols  "
                    f"({dist}) → {out_path.name}",
                    flush=True,
                )

        for w in res.warnings:
            all_warnings.append(f"[{src.election_key}] {w}")

        manifest_entry = manifest.get(src.filename, {})
        summary_rows.append({
            "election_key":            res.election_key,
            "year":                    src.year,
            "election_type":           src.election_type,
            "n_raw_rows":              res.n_raw_rows,
            "n_redacted_dropped":      res.n_redacted_dropped,
            "n_sheets_after_redaction": res.n_sheets_after_redaction,
            "n_voters":                res.n_voters,
            "n_choice_columns":        res.n_choice_columns,
            "multi_sheet_ballot_types": ",".join(res.multi_sheet_ballot_types),
            "sheet_count_distribution": json.dumps(
                {str(k): v for k, v in
                 sorted(res.sheet_count_distribution.items())}
            ),
            "n_warnings":              len(res.warnings),
            "public_url":              src.public_url or "",
        })
        provenance_rows.append({
            "election_key":        res.election_key,
            "original_filename":   src.filename,
            "original_sha256":     manifest_entry.get("sha256", ""),
            "original_size_bytes": manifest_entry.get("size", ""),
            "public_url":          src.public_url or "",
            "retrieved_at":        manifest_entry.get("mtime_iso", ""),
            "processed_path":      (
                str(out_path.relative_to(PROCESSED_DIR.parent.parent))
                if res.n_voters else ""
            ),
            "extracted_at":        time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
            "notes":               src.notes,
        })

    summary = (
        pd.DataFrame(summary_rows).set_index("election_key")
        if summary_rows else pd.DataFrame()
    )
    provenance = pd.DataFrame(provenance_rows) if provenance_rows else pd.DataFrame()

    if not summary.empty:
        summary.to_csv(SUMMARY_CSV)
    if not provenance.empty:
        provenance.to_csv(PROVENANCE_CSV, index=False)

    if verbose and not summary.empty:
        print(f"\nwrote {SUMMARY_CSV.name} + {PROVENANCE_CSV.name}")
        if all_warnings:
            print(f"\n{len(all_warnings)} cleaner warning(s):")
            for w in all_warnings:
                print(f"  - {w}")

    if fail_on_empty and n_total_voters == 0:
        print("FAIL: pipeline produced zero voter rows", file=sys.stderr)
        raise SystemExit(1)
    return summary


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.clean", description=__doc__)
    p.add_argument("--election", "-e", action="append", default=[],
                   help="process only this election_key (repeatable)")
    p.add_argument("--fail-on-empty", action="store_true",
                   help="exit non-zero if every output is empty")
    p.add_argument("--quiet", "-q", action="store_true")
    a = p.parse_args(argv)
    clean(elections=a.election, fail_on_empty=a.fail_on_empty,
          verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
