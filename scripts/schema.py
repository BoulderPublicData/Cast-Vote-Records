"""Pandera-based validators for the wide City-of-Boulder CVR output.

The CVR data model is fundamentally **wide-by-key** — one row per ballot
(the observation) and one column per contest-choice (the variable). Per the
data-liberation convention, wide is the *storage* shape for ballot-level data;
a tidy long-form derivative may be added later for cross-source analysis but
is not the default.

The validators below check the ID-column block (stable across every vintage)
and treat contest columns as a permissive open set (because every election
presents a different list of contests).
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import pandera.pandas as pa


REQUIRED_ID_COLUMNS: tuple[str, ...] = (
    "_ID/CvrNumber",
    "_ID/TabulatorNum",
    "_ID/BatchId",
    "_ID/RecordId",
    "_ID/ImprintedId",
    "_ID/BallotType",
)
"""ID columns that must be present in every cleaned wide CSV."""

OPTIONAL_ID_COLUMNS: tuple[str, ...] = (
    "_ID/CountingGroup",
    "_ID/PrecinctPortion",
)
"""ID columns that appear in some Boulder vintages and not others."""


ID_BLOCK_SCHEMA: pa.DataFrameSchema = pa.DataFrameSchema(
    columns={
        "_ID/CvrNumber":    pa.Column(nullable=False),
        "_ID/TabulatorNum": pa.Column(nullable=False),
        "_ID/BatchId":      pa.Column(nullable=True),
        "_ID/RecordId":     pa.Column(nullable=True),
        "_ID/ImprintedId":  pa.Column(nullable=True),
        "_ID/BallotType":   pa.Column(nullable=False),
    },
    strict=False,
    coerce=False,
)
"""Permissive pandera schema for the ID-column block: presence + nullability.

Contest columns are not enumerated (they vary per election); use
:func:`validate_contest_columns` for cross-cutting checks.
"""


def validate_id_block(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the ID-column block via :data:`ID_BLOCK_SCHEMA`.

    Raises :class:`pandera.errors.SchemaError` /
    :class:`pandera.errors.SchemaErrors` on a violation; returns ``df``
    unchanged on success.
    """
    ID_BLOCK_SCHEMA.validate(df, lazy=True)
    return df


def contest_columns(df: pd.DataFrame) -> list[str]:
    """Return the list of ``Contest::Choice`` column names in ``df``."""
    return [c for c in df.columns if not c.startswith("_ID/")]


def id_columns(df: pd.DataFrame) -> list[str]:
    """Return the list of ``_ID/<label>`` column names in ``df``."""
    return [c for c in df.columns if c.startswith("_ID/")]


def validate_contest_columns(
    df: pd.DataFrame,
    *,
    expected_values: Iterable[float] = (0.0, 1.0),
) -> pd.DataFrame:
    """Check that every contest-choice column holds only NaN, 0, or 1.

    The wide CSV's three-value cell encoding is intentional (NIST §3.4.2
    ``HasIndication`` plus a not-on-this-ballot-style sentinel). Any other
    value indicates a pipeline regression.
    """
    expected_set = set(expected_values)
    bad: list[tuple[str, set]] = []
    for col in contest_columns(df):
        vals = pd.to_numeric(df[col], errors="coerce")
        observed = set(float(v) for v in vals.dropna().unique())
        unexpected = {v for v in observed if v not in expected_set}
        if unexpected:
            bad.append((col, unexpected))
    if bad:
        snippets = [f"{c}: {sorted(u)[:5]}" for c, u in bad[:5]]
        raise ValueError(
            f"contest columns hold unexpected values in {len(bad)} columns; "
            f"first 5: {snippets}"
        )
    return df
