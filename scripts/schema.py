"""Pandera-based validators for the countywide per-voter CVR output.

The CVR data model is fundamentally **wide-by-key** — one row per voter
(the observation) and one column per contest-choice (the variable). Per the
data-liberation convention, wide is the *storage* shape for ballot-level data;
a tidy long-form derivative may be added later for cross-source analysis but
is not the default.

The validators below check the ID-column block (stable across every vintage)
and treat contest columns as an open set (every election presents a
different list of contests) whose cells must be blank, 0 or 1.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import pandera.pandas as pa

REQUIRED_ID_COLUMNS: tuple[str, ...] = (
    "_ID/CvrNumber",
    "_ID/TabulatorNum",
    "_ID/BatchId",
    "_ID/RecordId",
    "_ID/ImprintedId",
    "_ID/BallotType",
    "_ID/n_sheets",
    "_ID/voter_id",
    "_ID/redacted",
)
"""ID columns that must be present in every cleaned wide CSV."""

OPTIONAL_ID_COLUMNS: tuple[str, ...] = (
    "_ID/CountingGroup",
    "_ID/PrecinctPortion",
)
"""ID columns that appear in some Boulder vintages and not others."""

BOOKKEEPING_ID_COLUMNS: tuple[str, ...] = (
    "_ID/n_sheets",
    "_ID/voter_id",
    "_ID/redacted",
)
"""ID columns the cleaner adds for each voter row: ``n_sheets`` is the number
of ballot sheets merged into this voter; ``voter_id`` is the ImprintedId of
the lowest-RecordId sheet (``redacted-NNNNN`` for a redacted ballot);
``redacted`` is ``True`` for a single ballot whose identifiers the County
blanked."""


def _ids_present_unless_redacted(df: pd.DataFrame) -> bool:
    """Ordinary (non-redacted) rows must carry numeric CvrNumber/TabulatorNum
    and a BallotType. Redacted single ballots may lack all three (the 2025
    file has one ballot with every identifier blank)."""
    needed = ("_ID/redacted", "_ID/CvrNumber", "_ID/TabulatorNum", "_ID/BallotType")
    if any(c not in df.columns for c in needed):
        return True  # the missing column is reported by its own Column check
    ordinary = ~df["_ID/redacted"].astype(bool)
    for col in ("_ID/CvrNumber", "_ID/TabulatorNum"):
        if pd.to_numeric(df.loc[ordinary, col], errors="coerce").isna().any():
            return False
    return not df.loc[ordinary, "_ID/BallotType"].isna().any()


def _is_str_or_na(s: pd.Series) -> pd.Series:
    return s.map(lambda v: isinstance(v, str) or v is pd.NA).astype(bool)


ID_BLOCK_SCHEMA: pa.DataFrameSchema = pa.DataFrameSchema(
    columns={
        # Redacted single ballots have blanked identifiers; the dataframe
        # check below requires them on every other row.
        "_ID/CvrNumber": pa.Column(nullable=True),
        "_ID/TabulatorNum": pa.Column(nullable=True),
        "_ID/BatchId": pa.Column(nullable=True),
        "_ID/RecordId": pa.Column(nullable=True),
        "_ID/ImprintedId": pa.Column(nullable=True),
        "_ID/BallotType": pa.Column(
            nullable=True,
            checks=pa.Check(
                _is_str_or_na,
                element_wise=False,
                error="BallotType must be a string (e.g. '01', 'DS-01')",
            ),
        ),
        "_ID/n_sheets": pa.Column(int, checks=pa.Check.ge(1), nullable=False),
        "_ID/voter_id": pa.Column(nullable=False, unique=True),
        "_ID/redacted": pa.Column(bool, nullable=False),
    },
    checks=[
        pa.Check(
            _ids_present_unless_redacted,
            error="non-redacted row without numeric CvrNumber/TabulatorNum",
        ),
    ],
    strict=False,
    coerce=False,
)
"""Pandera schema for the ID-column block: presence, nullability, BallotType
as text, ``n_sheets >= 1``, unique ``voter_id``, boolean ``redacted``, and
(dataframe-level) CvrNumber / TabulatorNum / BallotType present on every
non-redacted row.

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
    """Check that every contest-choice column holds only blank, 0, or 1.

    The wide CSV's three-value cell encoding is intentional (NIST §3.4.2
    ``HasIndication`` plus a not-on-this-ballot-style blank). Any other
    value indicates a pipeline regression. A non-blank cell that is not a
    number (``"X"``, ``"overvote"``) also fails: it would otherwise coerce to
    ``NaN`` and pass as "not on the ballot".
    """
    expected_set = set(expected_values)
    bad: list[str] = []
    for col in contest_columns(df):
        s = df[col]
        vals = pd.to_numeric(s, errors="coerce")
        lost = s.notna() & vals.isna()
        if lost.any():
            lost[lost] = ~s[lost].map(lambda v: isinstance(v, str) and not v.strip()).astype(bool)
        if lost.any():
            sample = sorted({str(v) for v in s[lost].unique()})[:5]
            bad.append(f"{col}: non-numeric {sample}")
            continue
        observed = {float(v) for v in vals.dropna().unique()}
        unexpected = {v for v in observed if v not in expected_set}
        if unexpected:
            bad.append(f"{col}: {sorted(unexpected)[:5]}")
    if bad:
        raise ValueError(
            f"contest columns hold unexpected values in {len(bad)} columns; first 5: {bad[:5]}"
        )
    return df
