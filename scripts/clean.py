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
* ``data/processed/_summary.csv`` — bookkeeping (n raw, aggregate rows
  dropped, single-ballot redacted rows kept, n sheets, n voters, out-of-order
  merges, rare-fingerprint sheets, multi-sheet ballot types, sheet-count
  distribution).

One election failing (unreadable file, schema violation) does not stop the
others: the error is reported, the remaining elections are cleaned, and the
run exits non-zero at the end.

``_summary.csv`` and ``provenance.csv`` are **upserted** by ``election_key``:
a run over a subset (``--election``) replaces only those elections' rows and
keeps the rest, so a partial run never shrinks the bookkeeping.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable

import pandas as pd

from . import config
from .cleaner import clean_countywide
from .config import ensure_dirs
from .fetch import LfsPointerError, check_lfs_pointers, load_manifest
from .loader import load_raw_cvr
from .schema import validate_contest_columns, validate_id_block
from .sources import SOURCES, get_source


def _wide_csv_path(election_key: str):
    return config.PROCESSED_DIR / f"{election_key}-county-wide-by-voter.csv"


def upsert_csv(path, new_rows: pd.DataFrame, *, key: str = "election_key") -> pd.DataFrame:
    """Merge ``new_rows`` into the CSV at ``path`` by ``key`` and write it.

    Rows for keys in ``new_rows`` are replaced; other existing rows are kept
    unless their key is no longer in :data:`SOURCES` (a renamed or removed
    election). Output is ordered like :data:`SOURCES`.
    """
    order = {s.election_key: i for i, s in enumerate(SOURCES)}
    frames = []
    if path.exists():
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        old = old[~old[key].isin(new_rows[key]) & old[key].isin(order)]
        frames.append(old)
    frames.append(new_rows.astype(str).replace({"nan": ""}) if len(new_rows) else new_rows)
    out = pd.concat(frames, ignore_index=True) if frames else new_rows
    cols = list(new_rows.columns) + [c for c in out.columns if c not in new_rows.columns]
    out = out[cols].fillna("")
    out = out.sort_values(key, key=lambda k: k.map(order)).reset_index(drop=True)
    if len(out):
        out.to_csv(path, index=False)
    return out


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
    try:
        check_lfs_pointers(config.ORIGINAL_DIR / s.filename for s in targets)
    except LfsPointerError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    summary_rows: list[dict] = []
    provenance_rows: list[dict] = []
    n_total_voters = 0
    all_warnings: list[str] = []
    failures: list[str] = []

    for src in targets:
        raw_path = config.ORIGINAL_DIR / src.filename
        if not raw_path.exists():
            if verbose:
                print(f"  [skip] {src.election_key}: {raw_path} not found", flush=True)
            continue

        if verbose:
            size_mb = raw_path.stat().st_size / 1e6
            print(f"  loading {src.election_key} ({size_mb:.1f} MB)...", flush=True)

        out_path = _wide_csv_path(src.election_key)
        try:
            raw = load_raw_cvr(raw_path)
            res = clean_countywide(raw, election_key=src.election_key)
            if res.n_voters > 0:
                validate_id_block(res.cleaned)
                validate_contest_columns(res.cleaned)
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the others
            msg = f"{src.election_key}: {type(exc).__name__}: {exc}"
            failures.append(msg)
            print(f"  [FAIL] {msg}", file=sys.stderr, flush=True)
            continue

        if res.n_voters == 0:
            if verbose:
                print(
                    f"  [empty] {src.election_key}: 0 voters after dropping "
                    f"aggregate rows",
                    flush=True,
                )
        else:
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
                    f"({dist}; {res.n_redacted_kept:,} redacted kept, "
                    f"{res.n_aggregate_rows_dropped:,} aggregates dropped, "
                    f"{res.n_out_of_order_merges:,} out-of-order merges) "
                    f"→ {out_path.name}",
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
            "n_aggregate_rows_dropped": res.n_aggregate_rows_dropped,
            "n_redacted_kept":         res.n_redacted_kept,
            "n_redacted_in_multisheet_styles": res.n_redacted_in_multisheet_styles,
            "n_sheets_after_redaction": res.n_sheets_after_redaction,
            "n_voters":                res.n_voters,
            "n_out_of_order_merges":   res.n_out_of_order_merges,
            "n_rare_fingerprint_sheets": res.n_rare_fingerprint_sheets,
            "n_rare_fingerprint_full_ballot": res.n_rare_fingerprint_full_ballot,
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
            "retrieved_at":        manifest_entry.get("retrieved_at", ""),
            "obtained_at":         manifest_entry.get("obtained_at", "") or src.obtained_at,
            "first_committed_at":  manifest_entry.get("first_committed_at", ""),
            "original_xlsx_modified": manifest_entry.get("xlsx_modified", ""),
            "processed_path":      (
                str(out_path.relative_to(config.PROCESSED_DIR.parent.parent))
                if res.n_voters else ""
            ),
            "extracted_at":        time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
            "notes":               src.notes,
        })

    summary = pd.DataFrame(summary_rows)
    if summary_rows:
        summary = upsert_csv(config.SUMMARY_CSV, summary)
        upsert_csv(config.PROVENANCE_CSV, pd.DataFrame(provenance_rows))
        summary = pd.read_csv(config.SUMMARY_CSV, dtype={"multi_sheet_ballot_types": str})
        summary = summary.set_index("election_key")

    if verbose and summary_rows:
        print(f"\nupserted {len(summary_rows)} election(s) into "
              f"{config.SUMMARY_CSV.name} + {config.PROVENANCE_CSV.name}")
        if all_warnings:
            print(f"\n{len(all_warnings)} cleaner warning(s):")
            for w in all_warnings:
                print(f"  - {w}")

    if failures:
        print(f"\nFAIL: {len(failures)} election(s) failed to clean:",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        raise SystemExit(1)
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
