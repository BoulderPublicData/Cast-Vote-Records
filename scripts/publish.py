"""Build a SQLite database for [Datasette](https://datasette.io/) from the
processed CVR CSVs.

Scaffolded per the data-liberation publishing convention. Opt-in: install the
``[publish]`` extra (``pip install -e ".[publish]"``) to get ``sqlite-utils``
+ ``datasette``. Deployment to Vercel / Fly / Cloud Run is opt-in via
``.github/workflows/publish.yml.disabled`` (rename to enable).

Each election becomes one table; columns are the wide CVR's flattened columns.
A ``provenance`` table joined on ``election_key`` carries the source URL,
retrieved-at time, and SHA-256.
"""

from __future__ import annotations

import argparse
import shutil
import sys

import pandas as pd

try:
    import sqlite_utils
except ImportError:
    sqlite_utils = None  # type: ignore

from .config import PROCESSED_DIR, PROVENANCE_CSV, ensure_dirs


DB_PATH = PROCESSED_DIR / "cast_vote_records.db"
METADATA_PATH = PROCESSED_DIR / "metadata.yaml"


def _check_sqlite_utils():
    if sqlite_utils is None:
        raise SystemExit(
            "publish requires sqlite-utils. Install with: "
            "pip install -e \".[publish]\""
        )


def build(verbose: bool = True):
    """Build ``data/processed/cast_vote_records.db`` from every wide CSV."""
    _check_sqlite_utils()
    ensure_dirs()
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite_utils.Database(DB_PATH)

    wide_csvs = sorted(PROCESSED_DIR.glob("*-county-wide-by-voter.csv"))
    if not wide_csvs:
        raise SystemExit(
            "no wide CSVs in data/processed/; run `python -m scripts.clean` first"
        )

    for csv in wide_csvs:
        election_key = csv.name.removesuffix("-county-wide-by-voter.csv")
        table_name = election_key.replace("-", "_").lower()
        df = pd.read_csv(csv, low_memory=False)
        db[table_name].insert_all(df.to_dict(orient="records"))  # type: ignore[union-attr]
        if verbose:
            print(f"  inserted {len(df):,} rows into table '{table_name}'")

    if PROVENANCE_CSV.exists():
        prov = pd.read_csv(PROVENANCE_CSV)
        db["provenance"].insert_all(prov.to_dict(orient="records"))  # type: ignore[union-attr]
        if verbose:
            print(f"  inserted {len(prov)} rows into table 'provenance'")

    _write_metadata(verbose=verbose)
    return DB_PATH


def _write_metadata(verbose: bool) -> None:
    from .sources import SOURCES
    lines = [
        "title: Boulder County Cast Vote Records",
        "description_html: |",
        "  <p>Redacted ballot-level Cast Vote Records published by the Boulder County",
        "  Clerk and Recorder, 2019&ndash;2025. Each table holds the City of",
        "  Boulder-eligible ballots from one election; the <code>provenance</code>",
        "  table carries source URLs and SHA-256 hashes for the underlying xlsx files.</p>",
        "license: CC-BY-4.0",
        "license_url: https://creativecommons.org/licenses/by/4.0/",
        "source: Boulder County Clerk and Recorder",
        "source_url: https://bouldercounty.gov/elections/",
        "databases:",
        "  cast_vote_records:",
        "    tables:",
    ]
    for src in SOURCES:
        if src.election_key == "2024-Primary":
            continue
        table_name = src.election_key.replace("-", "_").lower()
        lines.append(f"      {table_name}:")
        lines.append(
            f"        description: 'Per-voter ballots from the "
            f"{src.year} {src.election_type} election (countywide).'"
        )
    lines.append("      provenance:")
    lines.append("        description: 'Source URL, SHA-256 and retrieval time per file.'")
    METADATA_PATH.write_text("\n".join(lines) + "\n")
    if verbose:
        print(f"  wrote {METADATA_PATH}")


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.publish", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="Build SQLite + metadata for Datasette")
    sub.add_parser("serve", help="Build then launch a local Datasette server")
    sub.add_parser("deploy", help="Build then `datasette publish vercel`")
    a = p.parse_args(argv)
    if a.cmd == "build":
        build()
        return 0
    if a.cmd in {"serve", "deploy"}:
        build()
        cmd = ["datasette"]
        if a.cmd == "serve":
            cmd += ["serve", str(DB_PATH), "-m", str(METADATA_PATH)]
        else:
            cmd += [
                "publish", "vercel", str(DB_PATH), "-m", str(METADATA_PATH),
                "--project", "cast-vote-records",
            ]
        if shutil.which(cmd[0]) is None:
            print(f"{cmd[0]} not on PATH; install datasette first", file=sys.stderr)
            return 1
        import subprocess
        return subprocess.call(cmd)
    return 2


if __name__ == "__main__":
    sys.exit(_main())
