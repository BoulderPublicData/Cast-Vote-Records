"""Boulder County Cast Vote Records — data-liberation pipeline.

The package reads redacted CVR xlsx files (one per election) published by the
Boulder County Clerk and Recorder, reconstructs the four-row header into a
MultiIndex DataFrame, drops privacy-aggregated rows, combines consecutive
ballot sheets from the same voter into single per-voter rows, and emits a
wide CSV per election under ``data/processed/``.

The CLI entrypoint is ``python -m scripts.pipeline``. See ``AGENTS.md`` for
architecture, design decisions, contribution guidelines, limitations, and
references.
"""

from .loader import ID_LABELS, REDACTED_VALUES, load_raw_cvr
from .cleaner import (
    CITY_CONTEST_MARKER,
    CleanResult,
    clean_countywide,
    combine_multisheet,
    detect_city_ballot_types,
    flatten_columns,
)
from .sources import SOURCES, CvrSource, get_source

__all__ = [
    "ID_LABELS",
    "REDACTED_VALUES",
    "load_raw_cvr",
    "CITY_CONTEST_MARKER",
    "CleanResult",
    "clean_countywide",
    "combine_multisheet",
    "detect_city_ballot_types",
    "flatten_columns",
    "SOURCES",
    "CvrSource",
    "get_source",
]
