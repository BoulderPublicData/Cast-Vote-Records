"""Orchestrator: runs each :class:`scripts.sources.CvrSource` through the
loader + cleaner, validates against :mod:`scripts.schema`, and writes
per-election wide CSVs plus a project-wide provenance sidecar to
``data/processed/``.

Outputs:

* ``data/processed/<election_key>-city-of-boulder-wide.csv`` — one per
  election with non-zero City of Boulder ballots.
* ``data/processed/provenance.csv`` — one row per processed artifact with
  source URL, retrieved-at time, SHA-256, output path, row counts.
* ``data/processed/_summary.csv`` — bookkeeping (n raw, n redacted, n city
  ballots, n contests).
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

import pandas as pd

from .cleaner import clean_city_cvr
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
    return PROCESSED_DIR / f"{election_key}-city-of-boulder-wide.csv"


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
        zero city-ballot rows across every output. Catches silent regressions
        from upstream layout changes.

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
    n_total_city = 0

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
        res = clean_city_cvr(raw, election_key=src.election_key)
        out_path = _wide_csv_path(src.election_key)

        if res.n_city_ballots == 0:
            if verbose:
                print(
                    f"  [empty] {src.election_key}: 0 City of Boulder ballots "
                    f"(no City-of-Boulder contests on any ballot style)",
                    flush=True,
                )
        else:
            validate_id_block(res.cleaned)
            res.cleaned.to_csv(out_path, index=False)
            n_total_city += res.n_city_ballots
            if verbose:
                print(
                    f"  [ok]   {src.election_key}: {res.n_city_ballots:,} ballots "
                    f"× {res.n_choice_columns} choice cols → {out_path.name}",
                    flush=True,
                )

        manifest_entry = manifest.get(src.filename, {})
        summary_rows.append({
            "election_key":        res.election_key,
            "year":                src.year,
            "election_type":       src.election_type,
            "n_raw_rows":          res.n_raw_rows,
            "n_redacted_dropped":  res.n_redacted_dropped,
            "city_ballot_types":   ",".join(res.city_ballot_types),
            "n_city_ballots":      res.n_city_ballots,
            "n_choice_columns":    res.n_choice_columns,
            "public_url":          src.public_url or "",
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
                if res.n_city_ballots else ""
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

    if fail_on_empty and n_total_city == 0:
        print("FAIL: pipeline produced zero City of Boulder ballots",
              file=sys.stderr)
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
