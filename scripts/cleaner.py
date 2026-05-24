"""Filter a raw CVR to City of Boulder ballots and tidy the result.

The cleaner identifies City of Boulder ballots by detecting which ballot styles
(Dominion calls these "BallotType"; NIST calls them ``CVR::BallotStyleId``,
see §3.5.4.1) present at least one City-of-Boulder municipal contest, drops
privacy-aggregated rows, drops contest columns that are entirely ``NaN`` for
the city subset, runs basic integrity checks, and flattens the column
MultiIndex to a CSV-friendly ``Contest::Choice`` (or ``_ID/Label``) form.

**Why privacy aggregation exists.** Boulder County, like every Colorado
jurisdiction, must protect voter anonymity by aggregating ballots in precincts
where the combination of ballot-style and turnout would let a reader
re-identify an individual voter from their CVR. See the AuditEngine paper
(*Auditing Elections Using Ballot Images and AuditEngine*, Lutz 2022, §3.1.2,
"Privacy and Ballot Anonymity"). Two conventions appear in Boulder's redacted
exports:

* **2023 and later.** The County puts a sentinel string in ``CvrNumber``:
  ``"RCV Redacted & Randomly Sorted"`` for ranked-choice contests whose
  small-precinct CVRs have been shuffled within the contest, and
  ``"Redacted & Aggregated"`` for fully aggregated rows. The vote columns may
  be filled in but the row does not correspond to any single voter.

* **2019–2022.** The County does not use a sentinel string; instead one row
  per ballot style carries ``NaN`` in ``CvrNumber`` (and ``TabulatorNum``,
  ``BatchId``, ``RecordId``) and aggregated vote values across many contests.
  These rows must be detected by the missing ID rather than by a string match.

* **2021 specifically** also has per-ballot-style summary rows where
  ``TabulatorNum`` is ``NaN`` and the ballot-style code (``"DS-01"`` etc.)
  is stuffed into ``CvrNumber``. A real ballot always has a ``TabulatorNum``
  (the scanner that captured it), so the absence is diagnostic.

:func:`clean_city_cvr` drops all three. The auto-detection threshold
``min_ballots`` in :func:`detect_city_ballot_types` is a defensive backstop
in case a single aggregate row slips through and flips a non-city ballot
style into the "city" set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .loader import REDACTED_VALUES, contest_columns


CITY_CONTEST_MARKER = "City of Boulder"


@dataclass
class CleanResult:
    """Outcome of one election's pipeline run."""

    election_key: str
    n_raw_rows: int
    n_redacted_dropped: int
    city_ballot_types: tuple[str, ...]
    n_city_ballots: int
    n_choice_columns: int
    cleaned: pd.DataFrame


def detect_city_ballot_types(
    df: pd.DataFrame,
    marker: str = CITY_CONTEST_MARKER,
    min_ballots: int = 5,
) -> tuple[str, ...]:
    """Return the ballot-type codes that vote on at least one ``marker`` contest.

    A ballot type "presents" the contest if more than ``min_ballots`` ballots of
    that type have a non-null value in any column matching ``marker``. The
    threshold exists to defend against privacy-aggregated rows that survive the
    redaction filter (one such row per ballot type can otherwise flip an entire
    Longmont ballot type to "City of Boulder").

    ``marker`` defaults to ``"City of Boulder"`` so the function returns every
    ballot type whose voters actually got the City of Boulder municipal contests
    on their ballots.
    """
    bt_col = ("_ID", "BallotType")
    if bt_col not in df.columns:
        raise KeyError("DataFrame has no BallotType column; load with load_raw_cvr")

    bt = df[bt_col]
    if isinstance(bt, pd.DataFrame):
        bt = bt.iloc[:, 0]
    bt = bt.astype(str)

    marker_cols = [
        c for c in contest_columns(df)
        if isinstance(c[0], str) and marker in c[0]
    ]
    if not marker_cols:
        return ()

    out: set[str] = set()
    for bt_val in bt.dropna().unique():
        sub = df[bt == bt_val]
        n_with_marker = sub[marker_cols].notna().any(axis=1).sum()
        if n_with_marker > min_ballots:
            out.add(str(bt_val))
    return tuple(sorted(out))


def flatten_columns(df: pd.DataFrame) -> list[str]:
    """Flatten a :func:`load_raw_cvr` MultiIndex into CSV-friendly column names.

    ID columns become ``_ID/<label>`` (e.g. ``_ID/CvrNumber``); contest columns
    become ``<contest>::<candidate>``.
    """
    out: list[str] = []
    for c in df.columns:
        if c[0] == "_ID":
            out.append(f"_ID/{c[1]}")
        else:
            out.append(f"{c[0]}::{c[1]}")
    return out


def clean_city_cvr(
    raw_df: pd.DataFrame,
    election_key: str,
    city_ballot_types: Optional[tuple[str, ...]] = None,
    marker: str = CITY_CONTEST_MARKER,
) -> CleanResult:
    """Run the City of Boulder filter and tidy pass on ``raw_df``.

    Parameters
    ----------
    raw_df
        Output of :func:`cvr_pipeline.loader.load_raw_cvr`.
    election_key
        Slug used in logging and downstream filenames.
    city_ballot_types
        Override for auto-detection. Pass a tuple of ballot-type strings to
        force-include them; pass ``None`` (default) to auto-detect every ballot
        type that votes on at least one ``marker`` contest.
    marker
        Substring used by auto-detection. Default ``"City of Boulder"``.

    Returns
    -------
    CleanResult
        Includes the cleaned DataFrame (with flattened column names) and
        bookkeeping fields suitable for a pipeline summary table.
    """
    n_raw = len(raw_df)

    # 1. Drop privacy-aggregated rows. Boulder County uses three conventions
    #    that collectively differ from a real ballot in one observable way:
    #    a real ballot has BOTH an integer CvrNumber AND an integer
    #    TabulatorNum. The three aggregation conventions each fail at least
    #    one of those two checks:
    #      (a) 2023+ — CvrNumber is a sentinel string like
    #          "RCV Redacted & Randomly Sorted" or "Redacted & Aggregated"
    #          (non-numeric).
    #      (b) 2019–2022 — CvrNumber is NaN (one aggregate row per
    #          BallotType).
    #      (c) 2021 — TabulatorNum is NaN and CvrNumber holds the ballot-
    #          style code ("DS-01" — also non-numeric).
    #
    #    pd.to_numeric(..., errors='coerce').isna() catches all three. It is
    #    robust to the pandas 2.x → 3.x change in how NaN is represented in
    #    object/string columns (where bare `.isna()` on an object series may
    #    behave inconsistently across pandas versions).
    cvr_col = ("_ID", "CvrNumber")
    tab_col = ("_ID", "TabulatorNum")
    cvr_vals = raw_df[cvr_col]
    if isinstance(cvr_vals, pd.DataFrame):
        cvr_vals = cvr_vals.iloc[:, 0]
    tab_vals = raw_df[tab_col]
    if isinstance(tab_vals, pd.DataFrame):
        tab_vals = tab_vals.iloc[:, 0]
    missing_cvr_mask = pd.to_numeric(cvr_vals, errors="coerce").isna()
    missing_tab_mask = pd.to_numeric(tab_vals, errors="coerce").isna()
    redacted_mask = missing_cvr_mask | missing_tab_mask
    df = raw_df[~redacted_mask].copy()
    n_redacted = int(redacted_mask.sum())

    # 2. Identify city ballot types (auto or override) and filter
    if city_ballot_types is None:
        city_ballot_types = detect_city_ballot_types(df, marker=marker)

    bt_col = ("_ID", "BallotType")
    bt = df[bt_col]
    if isinstance(bt, pd.DataFrame):
        bt = bt.iloc[:, 0]
    bt = bt.astype(str)
    city_df = df[bt.isin(city_ballot_types)].copy()

    # 3. Drop ballot-choice columns that are entirely NaN for the city subset
    keep = []
    for c in city_df.columns:
        if c[0] == "_ID":
            keep.append(c)
        elif city_df[c].notna().any():
            keep.append(c)
    city_df = city_df.loc[:, keep]

    # 4. Integrity checks (only when the universe is non-empty)
    if len(city_df) > 0:
        for required in ("CvrNumber", "TabulatorNum", "BallotType"):
            assert ("_ID", required) in city_df.columns, (
                f"{election_key} missing required ID column: {required}"
            )
        bt_after = city_df[bt_col]
        if isinstance(bt_after, pd.DataFrame):
            bt_after = bt_after.iloc[:, 0]
        bad = ~bt_after.astype(str).isin(city_ballot_types)
        assert not bad.any(), (
            f"{election_key} has {int(bad.sum())} non-city ballots after filter"
        )

    # 5. Flatten columns for CSV serialization
    city_df.columns = flatten_columns(city_df)
    n_choice = sum(1 for c in city_df.columns if not c.startswith("_ID/"))

    return CleanResult(
        election_key=election_key,
        n_raw_rows=n_raw,
        n_redacted_dropped=n_redacted,
        city_ballot_types=city_ballot_types,
        n_city_ballots=len(city_df),
        n_choice_columns=n_choice,
        cleaned=city_df,
    )
