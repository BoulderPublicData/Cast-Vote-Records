"""Command-line entrypoint: ``python -m cvr_pipeline build``.

Reads each CVR file from ``data/raw/`` listed in
:data:`cvr_pipeline.sources.SOURCES`, runs the loader + cleaner, and writes a
wide CSV per election to ``data/clean/<election_key>-city-of-boulder-wide.csv``.
A summary CSV at ``data/clean/_summary.csv`` records what was produced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from .cleaner import clean_city_cvr
from .loader import load_raw_cvr
from .sources import SOURCES, CvrSource, get_source


RAW_DIR = Path("data/raw")
CLEAN_DIR = Path("data/clean")


def _process(src: CvrSource, raw_dir: Path, clean_dir: Path, verbose: bool):
    raw_path = raw_dir / src.filename
    if not raw_path.exists():
        print(f"  [skip] {src.election_key}: {raw_path} not found", flush=True)
        return None

    if verbose:
        size_mb = raw_path.stat().st_size / 1e6
        print(f"  loading {src.election_key} ({size_mb:.1f} MB)...", flush=True)

    raw = load_raw_cvr(raw_path)
    result = clean_city_cvr(raw, election_key=src.election_key)

    if result.n_city_ballots == 0:
        print(
            f"  [empty] {src.election_key}: 0 City of Boulder ballots "
            f"(no City-of-Boulder contests on any ballot type — expected for "
            f"partisan primaries)",
            flush=True,
        )
        return result

    out_path = clean_dir / f"{src.election_key}-city-of-boulder-wide.csv"
    result.cleaned.to_csv(out_path, index=False)
    print(
        f"  [ok]   {src.election_key}: {result.n_city_ballots:,} ballots × "
        f"{result.n_choice_columns} choice cols → {out_path}",
        flush=True,
    )
    return result


def build(
    elections: Iterable[str] = (),
    raw_dir: Path = RAW_DIR,
    clean_dir: Path = CLEAN_DIR,
    verbose: bool = True,
) -> pd.DataFrame:
    """Run the loader + cleaner for every election (or a filtered subset).

    Parameters
    ----------
    elections
        Iterable of ``election_key`` strings. Empty (default) means *all* in
        :data:`cvr_pipeline.sources.SOURCES`.
    raw_dir, clean_dir
        Input and output directories.
    verbose
        Print per-election progress lines to stdout.

    Returns
    -------
    pandas.DataFrame
        One row per processed election with bookkeeping columns.
    """
    clean_dir.mkdir(parents=True, exist_ok=True)
    targets = tuple(SOURCES) if not elections else tuple(get_source(k) for k in elections)

    rows = []
    for src in targets:
        res = _process(src, raw_dir, clean_dir, verbose=verbose)
        if res is None:
            continue
        rows.append({
            "election_key": res.election_key,
            "year": src.year,
            "election_type": src.election_type,
            "n_raw_rows": res.n_raw_rows,
            "n_redacted_dropped": res.n_redacted_dropped,
            "city_ballot_types": ",".join(res.city_ballot_types),
            "n_city_ballots": res.n_city_ballots,
            "n_choice_columns": res.n_choice_columns,
            "public_url": src.public_url or "",
        })

    summary = pd.DataFrame(rows).set_index("election_key") if rows else pd.DataFrame()
    if not summary.empty:
        summary_path = clean_dir / "_summary.csv"
        summary.to_csv(summary_path)
        if verbose:
            print(f"\nwrote {summary_path}", flush=True)
    return summary


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cvr_pipeline", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    build_p = sub.add_parser("build", help="Clean every CVR in data/raw/")
    build_p.add_argument(
        "--election", "-e", action="append", default=[],
        help="Process only this election_key (repeatable). Default: all.",
    )
    build_p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    build_p.add_argument("--clean-dir", type=Path, default=CLEAN_DIR)
    build_p.add_argument("--quiet", "-q", action="store_true")

    sub.add_parser("list", help="List known elections from sources.py")

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd == "build":
        summary = build(
            elections=args.election,
            raw_dir=args.raw_dir,
            clean_dir=args.clean_dir,
            verbose=not args.quiet,
        )
        if summary.empty:
            print("no elections were processed", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "list":
        for src in SOURCES:
            posted = "public" if src.public_url else "CORA"
            print(f"  {src.election_key:24s} {src.year} {src.election_type:12s} [{posted}] {src.filename}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
