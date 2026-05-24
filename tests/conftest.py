"""Synthetic CVR fixtures.

Two fixtures:

* ``minimal_cvr_path`` — single-sheet ballots only. Tests redaction filter,
  flatten, and the City of Boulder detection helper.
* ``multisheet_cvr_path`` — a synthetic two-sheet ballot style (``DS-01``)
  alongside a single-sheet style (``DS-02``). Tests the multi-sheet
  merger's happy path and every documented edge case.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Single-sheet fixture — exercises redaction filter only
# ---------------------------------------------------------------------------

def _build_minimal_cvr(path: Path) -> None:
    """Write a small single-sheet synthetic CVR xlsx to ``path``.

    Structure mirrors a coordinated-election CVR:
        * 6 ID columns ending with BallotType
        * 1 City of Boulder contest (3 candidates)
        * 1 Longmont contest (2 candidates)
        * 12 City of Boulder ballots (``DS-01``), 6 Longmont ballots
          (``DS-02``), 1 sentinel-string redacted row, 1 NaN-CvrNumber
          aggregate row attached to DS-02, 1 NaN-TabulatorNum 2021-style
          summary row
    """
    rows: list[list[object]] = []
    nan = np.nan

    rows.append(["Synthetic Test Election", "5.17.17.1", nan, nan, nan, nan,
                 nan, nan, nan, nan, nan])
    cob = "City of Boulder Council Candidates (Vote For=1)"
    lmt = "City of Longmont - Mayor (Vote For=1)"
    rows.append([nan, nan, nan, nan, nan, nan,
                 cob, cob, cob, lmt, lmt])
    rows.append([nan, nan, nan, nan, nan, nan,
                 "Alice", "Bob", "Carol", "Dana", "Eve"])
    rows.append(["CvrNumber", "TabulatorNum", "BatchId", "RecordId",
                 "ImprintedId", "BallotType",
                 nan, nan, nan, nan, nan])

    city_votes = [
        (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0),
        (0, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0),
        (0, 1, 0), (0, 0, 1), (1, 0, 0), (0, 1, 0),
    ]
    for i, (a, b, c) in enumerate(city_votes, start=1):
        rows.append([str(i), "100", "1", str(i), f"100-1-{i}", "DS-01",
                     a, b, c, nan, nan])

    long_votes = [(1, 0), (0, 1), (1, 0), (0, 1), (1, 0), (0, 1)]
    for j, (d, e) in enumerate(long_votes, start=20):
        rows.append([str(j), "100", "1", str(j), f"100-1-{j}", "DS-02",
                     nan, nan, nan, d, e])

    # Privacy aggregates: sentinel string, NaN-CvrNumber, NaN-TabulatorNum
    rows.append(["RCV Redacted & Randomly Sorted", nan, nan, nan, nan, "DS-01",
                 0, 0, 0, nan, nan])
    rows.append([nan, nan, nan, nan, nan, "DS-02",
                 0, 0, 0, nan, nan])
    rows.append(["DS-01", nan, nan, nan, nan, "DS-01",
                 0, 0, 0, nan, nan])

    df = pd.DataFrame(rows)
    df.to_excel(path, header=False, index=False)


@pytest.fixture()
def minimal_cvr_path(tmp_path: Path) -> Path:
    p = tmp_path / "mini.xlsx"
    _build_minimal_cvr(p)
    return p


# ---------------------------------------------------------------------------
# Multi-sheet fixture — exercises the merger's happy path + edge cases
# ---------------------------------------------------------------------------

def _build_multisheet_cvr(path: Path) -> None:
    """Write a synthetic CVR with a two-sheet ballot style and a single-sheet
    ballot style, plus every documented edge case the merger must handle.

    Layout (all rows in TabulatorNum=100, BatchId=1, RecordId sequential):

    * Voter A (BallotType DS-01, 2-sheet): RecordId 1 = sheet 1 (presidential),
      RecordId 2 = sheet 2 (ballot question). Should merge.
    * Voter B (BallotType DS-01, 2-sheet): RecordId 3, 4. Should merge.
    * Voter C (BallotType DS-01, sheet-1 only — sheet 2 lost): RecordId 5.
      Should stand alone.
    * Voter D (BallotType DS-01, sheet-1 only): RecordId 6. Should stand alone
      (NOT merged with C because both are sheet 1, not sheet 1 + sheet 2).
    * Voter E (BallotType DS-01, 2-sheet): RecordId 7, 8. Merge.
    * Voter F (BallotType DS-02, 1-sheet): RecordId 9. Stands alone.
    * Voter G (BallotType DS-02, 1-sheet): RecordId 10. Stands alone (and is
      NOT merged with F across BallotType boundary or with anything else).
    * Voter H (BallotType DS-01, sheet-2 only — sheet 1 lost): RecordId 11.
      Should stand alone.
    * Voter I (BallotType DS-01, 2-sheet): RecordId 12, 13. Merge.

    Plus 1 sentinel-string redacted row (dropped before merging).

    Expected outcomes after the cleaner:
        * 14 sheets in raw (after redaction)
        * 9 voters after merging
        * DS-01 has 2 detected fingerprints (sheet 1 = presidential filled,
          sheet 2 = ballot-question filled)
        * DS-02 has 1 detected fingerprint
        * multi_sheet_ballot_types == ("DS-01",)
        * sheet_count_distribution == {1: 4 single-sheets, 2: 4 voters} — wait
          let me recount: A,B,E,I are 2-sheet (4 voters × 2 sheets each),
          plus C,D,F,G,H are 1-sheet (5 voters × 1 sheet each). Total
          voters = 9, total sheets = 13. Plus redacted = 14 raw rows.
    """
    rows: list[list[object]] = []
    nan = np.nan

    # Header: title, contest, candidate, ID labels
    rows.append(["Synthetic Multi-Sheet Test Election", "5.17.17.1",
                 nan, nan, nan, nan,
                 nan, nan, nan, nan, nan, nan, nan])
    pres = "Presidential Electors (Vote For=1)"
    bq   = "City of Boulder Ballot Question 2A (Vote For=1)"
    lmt  = "City of Longmont Mayor (Vote For=1)"
    rows.append([nan, nan, nan, nan, nan, nan,
                 pres, pres, pres, bq, bq, lmt, lmt])
    rows.append([nan, nan, nan, nan, nan, nan,
                 "Harris", "Trump", "Stein", "Yes", "No", "Mayer", "Brown"])
    rows.append(["CvrNumber", "TabulatorNum", "BatchId", "RecordId",
                 "ImprintedId", "BallotType",
                 nan, nan, nan, nan, nan, nan, nan])

    # Sheet 1 pattern: presidential filled, ballot-question NaN
    # Sheet 2 pattern: presidential NaN, ballot-question filled
    def sheet1(rid, choice):
        # choice in {0,1,2} for Harris/Trump/Stein
        v = [0, 0, 0]
        v[choice] = 1
        return [str(rid), "100", "1", str(rid), f"100-1-{rid}", "DS-01",
                v[0], v[1], v[2], nan, nan, nan, nan]

    def sheet2(rid, yesno):
        # yesno in {0,1} for Yes/No
        v = [0, 0]
        v[yesno] = 1
        return [str(rid), "100", "1", str(rid), f"100-1-{rid}", "DS-01",
                nan, nan, nan, v[0], v[1], nan, nan]

    def longmont_ballot(rid, choice):
        v = [0, 0]
        v[choice] = 1
        return [str(rid), "100", "1", str(rid), f"100-1-{rid}", "DS-02",
                nan, nan, nan, nan, nan, v[0], v[1]]

    # Voter A — 2-sheet
    rows.append(sheet1(1, choice=0))   # Harris
    rows.append(sheet2(2, yesno=0))    # Yes
    # Voter B — 2-sheet
    rows.append(sheet1(3, choice=1))   # Trump
    rows.append(sheet2(4, yesno=1))    # No
    # Voter C — sheet-1 only (sheet 2 lost)
    rows.append(sheet1(5, choice=2))   # Stein
    # Voter D — sheet-1 only
    rows.append(sheet1(6, choice=0))   # Harris
    # Voter E — 2-sheet
    rows.append(sheet1(7, choice=0))   # Harris
    rows.append(sheet2(8, yesno=0))    # Yes
    # Voter F — Longmont 1-sheet
    rows.append(longmont_ballot(9, choice=0))
    # Voter G — Longmont 1-sheet
    rows.append(longmont_ballot(10, choice=1))
    # Voter H — DS-01 sheet-2 only (sheet 1 lost)
    rows.append(sheet2(11, yesno=1))   # No
    # Voter I — 2-sheet
    rows.append(sheet1(12, choice=1))  # Trump
    rows.append(sheet2(13, yesno=0))   # Yes

    # Privacy aggregate
    rows.append(["RCV Redacted & Randomly Sorted", nan, nan, nan, nan, "DS-01",
                 0, 0, 0, nan, nan, nan, nan])

    df = pd.DataFrame(rows)
    df.to_excel(path, header=False, index=False)


@pytest.fixture()
def multisheet_cvr_path(tmp_path: Path) -> Path:
    p = tmp_path / "multi.xlsx"
    _build_multisheet_cvr(p)
    return p


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
