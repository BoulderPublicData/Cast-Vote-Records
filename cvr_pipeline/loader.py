"""Parse a Boulder County redacted CVR xlsx into a MultiIndex DataFrame.

Boulder County uses Dominion Voting's tabulation system and exports each
election's Cast Vote Records (CVRs) as an XLSX spreadsheet — Dominion's
proprietary format, not the [NIST Common Data Format Specification
SP 1500-103](https://doi.org/10.6028/NIST.SP.1500-103). The Dominion XLSX is
conceptually equivalent to the NIST CDF's *interpreted* CVR snapshot
(NIST §3.3): the version produced after the scanner applies contest rules to
the voter's marks. The *original* (pre-interpretation) and *modified*
(post-adjudication) snapshots NIST also defines are not exposed in Boulder's
public redacted exports.

Every Boulder County CVR shares the same four-row prelude across 2019–2025:

==========  =====================================================
row index   content
==========  =====================================================
0           election title + Dominion software version
1           contest name (repeated across the columns belonging to
            that contest — *not* merged cells)
2           candidate or choice name (with ``(N)`` rank-position
            suffix for ranked-choice contests, e.g. ``Aaron
            Brockett(1)`` for that candidate at rank 1)
3           ID column labels for the first 6–8 columns; party
            abbreviation (``DEM``/``REP``/``UNI``/...) for partisan
            contest columns in some years; ``NaN`` for everything
            else
==========  =====================================================

Ballot data begins at row 4. :func:`load_raw_cvr` reconstructs a
:class:`pandas.MultiIndex` where ID columns are ``('_ID', label)`` and
ballot-choice columns are ``(contest, candidate)``.

The ID column set drifts across years. The mapping to NIST CDF concepts is:

================ ============================================== ===========
Dominion column  NIST CDF attribute                             years seen
================ ============================================== ===========
CvrNumber        ``CVR::UniqueId`` (NIST §3.5.1)                all
TabulatorNum     ``CVR::CreatingDevice → SerialNumber``         all
BatchId          ``CVRSnapshot::BatchId`` (NIST §3.5.5)         all
RecordId         ``CVRSnapshot::BatchSequenceId`` (NIST §3.5.5) all
ImprintedId      ``CVR::BallotAuditId`` / composite             all
                 ``TabulatorNum-BatchId-RecordId`` for
                 ballot-level comparison auditing (NIST §3.5.4)
CountingGroup    Dominion-specific; counting universe           2019–2020,
                 (Regular, Provisional, Mail, etc.)             2022, 2024+
PrecinctPortion  political-geography portion of the precinct    2019, 2021
                 served by this ballot style
                 (cf. NIST ``BallotStyleUnit`` §3.5.6)
BallotType       ``CVR::BallotStyleId`` (NIST §3.5.4.1) —       all
                 the *style* of the ballot, i.e. which contests
                 the voter was eligible to vote on. NIST calls
                 this *ballot style*, not *ballot type*
================ ============================================== ===========

:data:`ID_LABELS` is the union of every label observed.

Each ballot-choice cell holds the equivalent of the NIST CDF
``SelectionPosition::HasIndication`` flag (NIST §3.4.2) — whether the scanner
detected a mark in the bubble for that contest-choice on that ballot. ``1``
means the bubble was marked; ``0`` means it was on the ballot but unmarked;
``NaN`` means the contest was not on that voter's ballot style. This is
distinct from ``IsAllocable`` (whether the mark can be counted as a vote
under contest rules); Dominion's interpreted-snapshot export collapses both
into the same numeric value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Union

import pandas as pd

ID_LABELS: frozenset[str] = frozenset({
    "CvrNumber",
    "TabulatorNum",
    "BatchId",
    "RecordId",
    "ImprintedId",
    "CountingGroup",
    "PrecinctPortion",
    "BallotType",
})
"""All known ID-column labels across Boulder County CVRs 2019–2025."""

REDACTED_VALUES: frozenset[str] = frozenset({
    "RCV Redacted & Randomly Sorted",
    "Redacted & Aggregated",
})
"""Strings the County puts in :code:`CvrNumber` for privacy-aggregated rows."""


def load_raw_cvr(path: Union[str, Path]) -> pd.DataFrame:
    """Read a CVR xlsx and reconstruct its column index.

    Parameters
    ----------
    path
        Filesystem path to the CVR ``.xlsx`` file.

    Returns
    -------
    pandas.DataFrame
        One row per ballot. Columns are a two-level :class:`pandas.MultiIndex`:

        * ``('_ID', label)`` for identification columns
          (e.g. ``('_ID', 'CvrNumber')``, ``('_ID', 'BallotType')``)
        * ``(contest, candidate)`` for ballot-choice columns

        Values for ID columns are strings; ballot-choice values are
        ``0``/``1``/``NaN`` for single-choice contests and 0/1/NaN per
        candidate-round combination for ranked-choice contests.
    """
    raw = pd.read_excel(path, header=None)
    if len(raw) < 5:
        raise ValueError(f"{path}: fewer than 5 rows; not a Boulder County CVR")

    contest_row = raw.iloc[1]
    candidate_row = raw.iloc[2]
    label_row = raw.iloc[3]

    cols: list[tuple[object, object]] = []
    for i in range(len(raw.columns)):
        lab = label_row.iloc[i]
        if pd.notna(lab) and lab in ID_LABELS:
            cols.append(("_ID", lab))
        else:
            cols.append((contest_row.iloc[i], candidate_row.iloc[i]))

    df = raw.iloc[4:].reset_index(drop=True)
    df.columns = pd.MultiIndex.from_tuples(cols)
    return df


def id_columns(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return the list of ``('_ID', label)`` columns in ``df``."""
    return [c for c in df.columns if c[0] == "_ID"]


def contest_columns(df: pd.DataFrame) -> list[tuple[object, object]]:
    """Return the list of ``(contest, candidate)`` (non-ID) columns in ``df``."""
    return [c for c in df.columns if c[0] != "_ID"]


def unique_contests(df: pd.DataFrame, contains: Iterable[str] = ()) -> list[str]:
    """Return distinct contest names. If ``contains`` is non-empty, return only
    contests that include *any* of those substrings."""
    contains = tuple(contains)
    names: set[str] = set()
    for c, _ in contest_columns(df):
        if not isinstance(c, str):
            continue
        if contains and not any(s in c for s in contains):
            continue
        names.add(c)
    return sorted(names)
