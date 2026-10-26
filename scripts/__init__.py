"""Boulder County Cast Vote Records — data-liberation pipeline.

The package reads redacted CVR xlsx files (one per election) published by the
Boulder County Clerk and Recorder, reconstructs the four-row header into a
MultiIndex DataFrame, drops multi-ballot privacy aggregates (keeping single
redacted ballots, flagged), combines each voter's ballot sheets into one
per-voter row, and emits a wide CSV per election under ``data/processed/``.

The CLI entrypoint is ``python -m scripts.pipeline``. See ``AGENTS.md`` for
architecture, design decisions, contribution guidelines, limitations, and
references.
"""

from .cleaner import (
    CITY_CONTEST_MARKER,
    CleanResult,
    clean_countywide,
    combine_multisheet,
    detect_city_ballot_types,
    flatten_columns,
    normalize_ballot_type,
    split_redacted,
)
from .loader import (
    AGGREGATE_SENTINELS,
    ID_LABELS,
    REDACTED_VALUES,
    SINGLE_BALLOT_SENTINELS,
    load_raw_cvr,
)
from .sources import SOURCES, CvrSource, get_source

__all__ = [
    "AGGREGATE_SENTINELS",
    "CITY_CONTEST_MARKER",
    "ID_LABELS",
    "REDACTED_VALUES",
    "SINGLE_BALLOT_SENTINELS",
    "SOURCES",
    "CleanResult",
    "CvrSource",
    "clean_countywide",
    "combine_multisheet",
    "detect_city_ballot_types",
    "flatten_columns",
    "get_source",
    "load_raw_cvr",
    "normalize_ballot_type",
    "split_redacted",
]
