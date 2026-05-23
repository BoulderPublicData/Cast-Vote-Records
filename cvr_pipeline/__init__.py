"""Boulder County Cast Vote Record pipeline.

The package reads redacted CVR xlsx files (one per election) published by the
Boulder County Clerk and Recorder, reconstructs the four-row header into a
MultiIndex DataFrame, filters to City of Boulder ballots, and emits a wide CSV
per election under ``data/clean/``.

The CLI entrypoint is ``python -m cvr_pipeline build``.
"""

from .loader import ID_LABELS, REDACTED_VALUES, load_raw_cvr
from .cleaner import (
    CleanResult,
    clean_city_cvr,
    detect_city_ballot_types,
    flatten_columns,
)
from .sources import SOURCES, CvrSource

__all__ = [
    "ID_LABELS",
    "REDACTED_VALUES",
    "load_raw_cvr",
    "CleanResult",
    "clean_city_cvr",
    "detect_city_ballot_types",
    "flatten_columns",
    "SOURCES",
    "CvrSource",
]
