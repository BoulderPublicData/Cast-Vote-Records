"""Tests for the cleaner (redaction filter + multi-sheet merger)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.cleaner import (
    clean_countywide,
    combine_multisheet,
    detect_city_ballot_types,
    flatten_columns,
)
from scripts.loader import load_raw_cvr


# ---------------------------------------------------------------------------
# detect_city_ballot_types — exercises auto-detection + min_ballots threshold
# ---------------------------------------------------------------------------

def test_detect_city_ballot_types_finds_ds01(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    assert detect_city_ballot_types(df) == ("DS-01",)


def test_detect_city_ballot_types_returns_empty_when_marker_absent(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    assert detect_city_ballot_types(df, marker="Lafayette") == ()


def test_detect_city_ballot_types_min_ballots_threshold_drops_aggregate(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    # DS-02 has only a single NaN-CvrNumber aggregate row with City of Boulder
    # votes filled in. min_ballots=5 (default) must reject it.
    assert "DS-02" not in detect_city_ballot_types(df)


# ---------------------------------------------------------------------------
# clean_countywide — redaction filter on single-sheet fixture
# ---------------------------------------------------------------------------

def test_clean_countywide_drops_all_three_aggregate_conventions(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    res = clean_countywide(df, election_key="test")
    # 21 raw rows: 12 DS-01 + 6 DS-02 + 1 sentinel + 1 NaN-CvrNumber + 1 NaN-Tab
    assert res.n_raw_rows == 21
    # All three aggregate conventions dropped
    assert res.n_redacted_dropped == 3
    # 18 voter rows survive (12 + 6, all single-sheet)
    assert res.n_voters == 18
    assert res.n_sheets_after_redaction == 18


def test_clean_countywide_keeps_all_ballot_types(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    res = clean_countywide(df, election_key="test")
    bts = set(res.cleaned["_ID/BallotType"].astype(str).unique())
    assert bts == {"DS-01", "DS-02"}


def test_clean_countywide_adds_bookkeeping_columns(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    res = clean_countywide(df, election_key="test")
    assert "_ID/n_sheets" in res.cleaned.columns
    assert "_ID/voter_id" in res.cleaned.columns
    # Every row is a single-sheet voter in this fixture
    assert (res.cleaned["_ID/n_sheets"] == 1).all()


# ---------------------------------------------------------------------------
# combine_multisheet — happy path + boundary cases on the multi-sheet fixture
# ---------------------------------------------------------------------------

def test_multisheet_merges_pairs(multisheet_cvr_path):
    df = load_raw_cvr(multisheet_cvr_path)
    res = clean_countywide(df, election_key="multi")
    assert res.n_raw_rows == 14          # 13 ballots + 1 sentinel
    assert res.n_redacted_dropped == 1   # the sentinel row
    assert res.n_sheets_after_redaction == 13
    # 9 voters: A B C D E + F G + H + I
    assert res.n_voters == 9
    # 4 two-sheet voters (A, B, E, I) + 5 one-sheet voters (C, D, F, G, H)
    assert res.sheet_count_distribution == {1: 5, 2: 4}


def test_multisheet_detects_multi_ballot_type(multisheet_cvr_path):
    df = load_raw_cvr(multisheet_cvr_path)
    res = clean_countywide(df, election_key="multi")
    # DS-01 has 2 sheets; DS-02 has 1
    assert res.multi_sheet_ballot_types == ("DS-01",)


def test_multisheet_does_not_merge_across_ballot_type_boundary(multisheet_cvr_path):
    df = load_raw_cvr(multisheet_cvr_path)
    res = clean_countywide(df, election_key="multi")
    # Two Longmont ballots (DS-02) at adjacent RecordIds must remain separate
    longmont = res.cleaned[res.cleaned["_ID/BallotType"] == "DS-02"]
    assert len(longmont) == 2
    assert (longmont["_ID/n_sheets"] == 1).all()


def test_multisheet_lone_sheet_one_stays_alone(multisheet_cvr_path):
    """Voter C and Voter D are both single-sheet voters with sheet-1 only;
    they sit adjacent in the data. Must NOT be merged with each other (both
    are sheet 1, not sheet 1 + sheet 2)."""
    df = load_raw_cvr(multisheet_cvr_path)
    res = clean_countywide(df, election_key="multi")
    single_ds01 = res.cleaned[
        (res.cleaned["_ID/BallotType"] == "DS-01")
        & (res.cleaned["_ID/n_sheets"] == 1)
    ]
    # Three of them: C (RecordId 5), D (RecordId 6), H (RecordId 11 — sheet-2 only)
    assert len(single_ds01) == 3


def test_multisheet_merged_voter_has_union_of_contest_values(multisheet_cvr_path):
    df = load_raw_cvr(multisheet_cvr_path)
    res = clean_countywide(df, election_key="multi")
    # Voter A: sheet 1 voted Harris (presidential), sheet 2 voted Yes (2A)
    # After merge, the voter row should have BOTH the presidential and 2A
    # marks filled.
    two_sheet_voters = res.cleaned[res.cleaned["_ID/n_sheets"] == 2]
    pres_cols = [c for c in res.cleaned.columns
                 if "Presidential Electors" in c]
    bq_cols   = [c for c in res.cleaned.columns
                 if "Ballot Question 2A" in c]
    for _, row in two_sheet_voters.iterrows():
        # At least one presidential bubble marked AND at least one 2A bubble marked
        assert any(row[c] == 1 for c in pres_cols), \
            f"two-sheet voter missing presidential mark: {row.to_dict()}"
        assert any(row[c] == 1 for c in bq_cols), \
            f"two-sheet voter missing 2A mark: {row.to_dict()}"


# ---------------------------------------------------------------------------
# Misc utility tests
# ---------------------------------------------------------------------------

def test_flatten_columns_handles_ids_and_contests():
    cols = pd.MultiIndex.from_tuples([
        ("_ID", "CvrNumber"),
        ("Contest A", "Alice"),
        ("Contest A", "Bob"),
    ])
    df = pd.DataFrame(columns=cols)
    assert flatten_columns(df) == [
        "_ID/CvrNumber",
        "Contest A::Alice",
        "Contest A::Bob",
    ]


def test_detect_raises_when_ballot_type_missing():
    df = pd.DataFrame(
        [["1", 1, 0]],
        columns=pd.MultiIndex.from_tuples([
            ("_ID", "CvrNumber"),
            ("Contest A", "X"),
            ("Contest A", "Y"),
        ]),
    )
    with pytest.raises(KeyError):
        detect_city_ballot_types(df)
