"""Project-wide path constants.

Centralized so individual modules do not hardcode ``data/original/`` etc.

``CVR_DATA_DIR`` overrides the data directory, so a long run (the pipeline
or ``clusters.ipynb``) can write to a copy of ``data/`` outside the working
tree and be committed once at the end. See AGENTS.md, "Long runs".
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CVR_DATA_DIR", PROJECT_ROOT / "data")).resolve()
ORIGINAL_DIR = DATA_DIR / "original"
PROCESSED_DIR = DATA_DIR / "processed"
CVR_DIR = PROCESSED_DIR / "cast-vote-records"
"""Per-voter CSVs + ``_summary.csv`` + ``provenance.csv`` (one folder per
dataset, mirroring Election-Results' ``data/processed/<dataset>/``)."""
CLUSTERS_DIR = PROCESSED_DIR / "clusters"
"""Outputs of ``clusters.ipynb`` + their ``provenance.csv``."""
AUDIT_DIR = DATA_DIR / "audit"
LOOKUPS_DIR = DATA_DIR / "lookups"
DOCS_DIR = PROJECT_ROOT / "docs"

ORIGINAL_MANIFEST = ORIGINAL_DIR / "manifest.json"
PROVENANCE_CSV = CVR_DIR / "provenance.csv"
SUMMARY_CSV = CVR_DIR / "_summary.csv"


def ensure_dirs() -> None:
    """Create every project data directory if it does not exist."""
    from . import config  # read the attributes at call time (tests patch them)

    for d in (
        config.ORIGINAL_DIR,
        config.PROCESSED_DIR,
        config.CVR_DIR,
        config.AUDIT_DIR,
        config.LOOKUPS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
