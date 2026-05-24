"""Project-wide path constants.

Centralized so individual modules do not hardcode ``data/original/`` etc.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ORIGINAL_DIR = DATA_DIR / "original"
PROCESSED_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audit"
LOOKUPS_DIR = DATA_DIR / "lookups"
DOCS_DIR = PROJECT_ROOT / "docs"

ORIGINAL_MANIFEST = ORIGINAL_DIR / "manifest.json"
PROVENANCE_CSV = PROCESSED_DIR / "provenance.csv"
SUMMARY_CSV = PROCESSED_DIR / "_summary.csv"


def ensure_dirs() -> None:
    """Create every project data directory if it does not exist."""
    for d in (ORIGINAL_DIR, PROCESSED_DIR, AUDIT_DIR, LOOKUPS_DIR):
        d.mkdir(parents=True, exist_ok=True)
