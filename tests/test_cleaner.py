"""Tests for the cleaner (redaction filter + multi-sheet merger)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cleaner import (
    clean_countywide,
    coerce_contest_values,
    combine_multisheet,
    detect_city_ballot_types,
    flatten_columns,
    normalize_ballot_type,
    split_redacted,
)
from scripts.loader import contest_columns, load_raw_cvr
from tests.conftest import make_sheets

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


def test_clean_countywide_keeps_single_redacted_and_drops_aggregates(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    res = clean_countywide(df, election_key="test")
    # 25 raw rows: 12 DS-01 + 6 DS-02 + 3 single redacted + 4 aggregates
    assert res.n_raw_rows == 25
    # Only the 4 aggregates are dropped (label rule + value rule)
    assert res.n_aggregate_rows_dropped == 4
    # The 3 single-ballot redacted rows are kept and flagged
    assert res.n_redacted_kept == 3
    assert int(res.cleaned["_ID/redacted"].sum()) == 3
    # 21 voter rows (12 + 6 + 3), all single-sheet
    assert res.n_voters == 21
    assert res.n_sheets_after_redaction == 21
    assert res.sheet_count_distribution == {1: 21}


def test_redacted_rows_keep_marks_and_get_unique_voter_ids(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    res = clean_countywide(df, election_key="test")
    red = res.cleaned[res.cleaned["_ID/redacted"]]
    assert list(red["_ID/voter_id"]) == [
        "redacted-00001",
        "redacted-00002",
        "redacted-00003",
    ]
    assert res.cleaned["_ID/voter_id"].is_unique
    assert (red["_ID/n_sheets"] == 1).all()
    # Marks are intact: Carol from the RCV-redacted row, Alice from NaN row
    cob = "City of Boulder Council Candidates (Vote For=1)"
    assert int(red[f"{cob}::Carol"].sum()) == 1
    assert int(red[f"{cob}::Alice"].sum()) == 1
    # The redacted label is preserved, not invented
    labels = set(red["_ID/CvrNumber"].dropna())
    assert labels == {"Redacted", "RCV Redacted & Randomly Sorted"}


def test_split_redacted_rules():
    """Label rule (Consolidated/Aggregated, any case) and value rule (> 1)."""
    cols = pd.MultiIndex.from_tuples(
        [
            ("_ID", "CvrNumber"),
            ("_ID", "TabulatorNum"),
            ("_ID", "BallotType"),
            ("C (Vote For=1)", "A"),
            ("C (Vote For=1)", "B"),
        ]
    )
    df = pd.DataFrame(
        [
            [1, 100, "01", 1.0, 0.0],  # ordinary
            ["Redacted", np.nan, "01", 0.0, 1.0],  # single → kept
            [np.nan, np.nan, "01", 1.0, 0.0],  # single → kept
            ["redacted AND CONSOLIDATED", np.nan, "01", 0.0, 1.0],  # label → drop
            ["Redacted and Aggregated - B cards", np.nan, "01", 0.0, 0.0],
            [np.nan, np.nan, "01", 2.0, 0.0],  # value → drop
            ["DS-01", np.nan, "01", 0.0, 7.0],  # 2021 summary
            ["Something New", np.nan, "01", 0.0, 1.0],  # unknown label
        ],
        columns=cols,
    )
    split = split_redacted(df)
    assert len(split.ballots) == 1
    assert len(split.redacted) == 3
    assert split.n_aggregate_dropped == 4
    # Labels outside the documented sentinel list are reported (even when the
    # pattern classifies them) so a new convention gets documented.
    assert split.unknown_labels == ("Something New", "redacted AND CONSOLIDATED")


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
    assert res.n_raw_rows == 14  # 13 ballots + 1 aggregate
    assert res.n_aggregate_rows_dropped == 1
    assert res.n_redacted_kept == 0
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
        (res.cleaned["_ID/BallotType"] == "DS-01") & (res.cleaned["_ID/n_sheets"] == 1)
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
    pres_cols = [c for c in res.cleaned.columns if "Presidential Electors" in c]
    bq_cols = [c for c in res.cleaned.columns if "Ballot Question 2A" in c]
    for _, row in two_sheet_voters.iterrows():
        # At least one presidential bubble marked AND at least one 2A bubble marked
        assert any(row[c] == 1 for c in pres_cols), (
            f"two-sheet voter missing presidential mark: {row.to_dict()}"
        )
        assert any(row[c] == 1 for c in bq_cols), (
            f"two-sheet voter missing 2A mark: {row.to_dict()}"
        )


# ---------------------------------------------------------------------------
# Misc utility tests
# ---------------------------------------------------------------------------


def test_flatten_columns_handles_ids_and_contests():
    cols = pd.MultiIndex.from_tuples(
        [
            ("_ID", "CvrNumber"),
            ("Contest A", "Alice"),
            ("Contest A", "Bob"),
        ]
    )
    df = pd.DataFrame(columns=cols)
    assert flatten_columns(df) == [
        "_ID/CvrNumber",
        "Contest A::Alice",
        "Contest A::Bob",
    ]


def test_detect_raises_when_ballot_type_missing():
    df = pd.DataFrame(
        [["1", 1, 0]],
        columns=pd.MultiIndex.from_tuples(
            [
                ("_ID", "CvrNumber"),
                ("Contest A", "X"),
                ("Contest A", "Y"),
            ]
        ),
    )
    with pytest.raises(KeyError):
        detect_city_ballot_types(df)


# ---------------------------------------------------------------------------
# Out-of-order sheets (#7): complementary sheets merge in either order
# ---------------------------------------------------------------------------


def _clean(rows, **kw):
    return clean_countywide(make_sheets(rows, **kw), election_key="t")


def _baseline(n_batches=5, voters_per_batch=3):
    """Normal forward-order batches on tabulator 900, so the empirical
    sheet-order inference sees sheet 1 first (as in every real file)."""
    rows = []
    for b in range(1, n_batches + 1):
        for v in range(voters_per_batch):
            rows += [(900, b, 2 * v + 1, "01", 1), (900, b, 2 * v + 2, "01", 2)]
    return rows


def test_reversed_pair_is_merged():
    """10 normal two-sheet voters plus one voter scanned sheet 2 first."""
    rows = []
    rec = 1
    for _ in range(10):
        rows += [(100, 1, rec, "01", 1), (100, 1, rec + 1, "01", 2)]
        rec += 2
    rows += [(100, 1, rec, "01", 2), (100, 1, rec + 1, "01", 1)]  # reversed
    res = _clean(rows)
    assert res.n_voters == 11
    assert res.sheet_count_distribution == {2: 11}
    assert res.n_out_of_order_merges == 1
    # voter_id is the ImprintedId of the lowest-RecordId sheet (its sheet 2)
    assert res.cleaned["_ID/voter_id"].iloc[-1] == f"100-1-{rec}"
    # The merged voter carries both sheets' marks
    last = res.cleaned.iloc[-1]
    assert last["Contest 1 (Vote For=1)::A"] == 1
    assert last["Contest 2 (Vote For=1)::A"] == 1


def test_forward_pairing_wins_when_ambiguous():
    """Lone sheet 2, then a normal voter (sheet 1, sheet 2): the forward pair
    is kept and the lone sheet 2 stays alone (not paired backwards)."""
    rows = [(100, 1, 1, "01", 2), (100, 1, 2, "01", 1), (100, 1, 3, "01", 2)]
    res = _clean(rows + _baseline())
    test_rows = res.cleaned[res.cleaned["_ID/TabulatorNum"] == 100]
    assert len(test_rows) == 2
    assert res.n_out_of_order_merges == 0
    assert list(test_rows["_ID/n_sheets"]) == [1, 2]
    assert list(test_rows["_ID/voter_id"]) == ["100-1-1", "100-1-2"]


def test_reversed_pair_not_merged_across_batch_or_gap():
    rows = [
        (100, 1, 1, "01", 2),
        (100, 2, 2, "01", 1),  # different batch
        (100, 3, 1, "01", 2),
        (100, 3, 3, "01", 1),  # RecordId gap
        (100, 4, 1, "01", 2),
        (101, 4, 2, "01", 1),  # different tabulator
    ]
    res = _clean(rows + _baseline())
    assert res.n_out_of_order_merges == 0
    assert res.n_voters == 6 + 15


def test_reversed_pair_not_merged_when_sheets_repeat():
    """Two lone sheet-2 rows are not complementary."""
    rows = [(100, 1, 1, "01", 1), (100, 1, 2, "01", 2), (100, 1, 3, "01", 2), (100, 1, 4, "01", 2)]
    res = _clean(rows)
    assert res.n_voters == 3
    assert res.n_out_of_order_merges == 0


# ---------------------------------------------------------------------------
# 3+-sheet styles (#15): merged as k-sheet voters, in any order
# ---------------------------------------------------------------------------


def test_three_sheet_style_merges_three_sheet_voters():
    rows = []
    rec = 1
    for _ in range(10):
        for k in (1, 2, 3):
            rows.append((100, 1, rec, "01", k))
            rec += 1
    res = _clean(rows, n_contests=3)
    assert res.n_voters == 10
    assert res.sheet_count_distribution == {3: 10}
    assert any("3 sheet fingerprints" in w for w in res.warnings)


def test_three_sheet_style_out_of_order():
    rows = []
    rec = 1
    for _ in range(10):
        for k in (1, 2, 3):
            rows.append((100, 1, rec, "01", k))
            rec += 1
    rows += [(100, 1, rec, "01", 3), (100, 1, rec + 1, "01", 1), (100, 1, rec + 2, "01", 2)]
    res = _clean(rows, n_contests=3)
    assert res.n_voters == 11
    assert res.sheet_count_distribution == {3: 11}
    assert res.n_out_of_order_merges == 1


def test_rare_full_ballot_fingerprint_is_counted_and_kept_alone():
    """A row that fills every contest of a 2-sheet style (2022's 3,319
    single-row ballots) is rare, reported, and kept as one voter."""
    rows = []
    rec = 1
    for _ in range(30):
        rows += [(100, 1, rec, "01", 1), (100, 1, rec + 1, "01", 2)]
        rec += 2
    rows.append((100, 1, rec, "01", (1, 2)))
    res = _clean(rows)
    assert res.n_voters == 31
    assert res.n_rare_fingerprint_sheets == 1
    assert res.n_rare_fingerprint_full_ballot == 1
    assert res.sheet_count_distribution == {2: 30, 1: 1}


def test_redacted_sheet_in_multisheet_style_stays_separate():
    rows = [
        (100, 1, 1, "01", 1),
        (100, 1, 2, "01", 2),
        (100, 1, 3, "01", 1),
        (100, 1, 4, "01", 2),
        (None, None, None, "01", 1),
    ]
    res = _clean(rows)
    assert res.n_voters == 3
    assert res.n_redacted_kept == 1
    assert res.n_redacted_in_multisheet_styles == 1
    assert res.n_sheets_after_redaction == 5
    assert int(res.cleaned["_ID/n_sheets"].sum()) == 5


# ---------------------------------------------------------------------------
# Empty / all-redacted elections (#14)
# ---------------------------------------------------------------------------


def test_all_aggregate_election_returns_empty_frame():
    df = make_sheets([(None, None, None, "01", 1)] * 3)
    df[("Contest 1 (Vote For=1)", "A")] = 5  # every row is an aggregate
    res = clean_countywide(df, election_key="t")
    assert res.n_voters == 0
    assert res.n_aggregate_rows_dropped == 3
    assert len(res.cleaned) == 0
    assert "_ID/voter_id" in res.cleaned.columns


def test_all_single_redacted_election_keeps_every_row():
    df = make_sheets([(None, None, None, "01", 1)] * 4)
    res = clean_countywide(df, election_key="t")
    assert res.n_voters == 4
    assert res.cleaned["_ID/redacted"].all()
    assert res.cleaned["_ID/voter_id"].is_unique


def test_combine_multisheet_on_empty_frame():
    empty = make_sheets([(100, 1, 1, "01", 1)]).iloc[0:0]
    merged, stats = combine_multisheet(empty)
    assert len(merged) == 0
    assert stats.sheet_count_distribution == {}


# ---------------------------------------------------------------------------
# Types (#18) and contest validation (#19)
# ---------------------------------------------------------------------------


def test_normalize_ballot_type_zero_pads_numeric_codes():
    s = pd.Series(["04", 4, 10, 4.0, "DS-01", " 7 ", "04 and 25", np.nan], dtype=object)
    out = normalize_ballot_type(s)
    assert list(out[:7]) == ["04", "04", "10", "04", "DS-01", "07", "04 and 25"]
    assert pd.isna(out.iloc[7])


def test_mixed_ballot_type_rows_are_one_style():
    """Excel stores '04' as text and 10 as a number; a mixed column must not
    split one style in two (which would break sheet inference)."""
    rows = [(100, 1, 1, "04", 1), (100, 1, 2, 4, 2), (100, 1, 3, "04", 1), (100, 1, 4, 4, 2)]
    res = _clean(rows)
    assert set(res.cleaned["_ID/BallotType"]) == {"04"}
    assert res.n_voters == 2


def test_contest_cells_are_nullable_int8_and_write_as_integers(tmp_path):
    rows = [(100, 1, 1, "01", 1), (100, 1, 2, "01", 2)]
    res = _clean(rows)
    contest = [c for c in res.cleaned.columns if not c.startswith("_ID/")]
    assert all(str(res.cleaned[c].dtype) == "Int8" for c in contest)
    out = tmp_path / "x.csv"
    res.cleaned.to_csv(out, index=False)
    text = out.read_text()
    assert "1.0" not in text and "0.0" not in text
    back = pd.read_csv(out, dtype={"_ID/BallotType": str})
    assert back["_ID/BallotType"].iloc[0] == "01"


def test_coerce_contest_values_rejects_text():
    df = make_sheets([(100, 1, 1, "01", 1), (100, 1, 2, "01", 1)])
    df[("Contest 1 (Vote For=1)", "A")] = [1, "overvote"]
    with pytest.raises(ValueError, match="non-numeric"):
        coerce_contest_values(df, contest_columns(df))


def test_coerce_contest_values_treats_whitespace_as_blank():
    df = make_sheets([(100, 1, 1, "01", 1), (100, 1, 2, "01", 1)])
    df[("Contest 1 (Vote For=1)", "A")] = [1, "  "]
    out = coerce_contest_values(df, contest_columns(df))
    assert pd.isna(out[("Contest 1 (Vote For=1)", "A")].iloc[1])


def test_clean_countywide_rejects_text_cells():
    df = make_sheets([(100, 1, 1, "01", 1)])
    df[("Contest 1 (Vote For=1)", "A")] = ["X"]
    with pytest.raises(ValueError, match="non-numeric"):
        clean_countywide(df, election_key="t")
