"""Tests for the Dominion-XLSX loader."""

from __future__ import annotations

import pandas as pd

from scripts.loader import (
    AGGREGATE_SENTINELS,
    ID_LABELS,
    REDACTED_VALUES,
    SINGLE_BALLOT_SENTINELS,
    contest_columns,
    id_columns,
    load_raw_cvr,
    unique_contests,
)


def test_load_raw_cvr_rebuilds_multiindex(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    assert isinstance(df.columns, pd.MultiIndex)
    assert id_columns(df) == [
        ("_ID", "CvrNumber"),
        ("_ID", "TabulatorNum"),
        ("_ID", "BatchId"),
        ("_ID", "RecordId"),
        ("_ID", "ImprintedId"),
        ("_ID", "BallotType"),
    ]
    # 25 rows: 12 city + 6 Longmont + 3 single redacted + 4 aggregates
    assert len(df) == 25


def test_load_raw_cvr_contest_columns(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    contests = unique_contests(df)
    assert "City of Boulder Council Candidates (Vote For=1)" in contests
    assert "City of Longmont - Mayor (Vote For=1)" in contests
    cob_cols = [
        c for c in contest_columns(df)
        if c[0] == "City of Boulder Council Candidates (Vote For=1)"
    ]
    assert {c[1] for c in cob_cols} == {"Alice", "Bob", "Carol"}


def test_id_labels_includes_all_known_variants():
    for label in (
        "CvrNumber", "TabulatorNum", "BatchId", "RecordId",
        "ImprintedId", "BallotType", "CountingGroup", "PrecinctPortion",
    ):
        assert label in ID_LABELS


def test_redacted_values_contains_known_strings():
    assert "RCV Redacted & Randomly Sorted" in REDACTED_VALUES
    assert "Redacted & Aggregated" in REDACTED_VALUES
    assert "Redacted" in REDACTED_VALUES


def test_sentinel_sets_are_disjoint_and_classified_by_pattern():
    from scripts.cleaner import AGGREGATE_LABEL_RE
    assert not (SINGLE_BALLOT_SENTINELS & AGGREGATE_SENTINELS)
    assert all(AGGREGATE_LABEL_RE.search(s) for s in AGGREGATE_SENTINELS)
    assert not any(AGGREGATE_LABEL_RE.search(s) for s in SINGLE_BALLOT_SENTINELS)
