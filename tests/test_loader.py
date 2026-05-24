"""Tests for the Dominion-XLSX loader."""

from __future__ import annotations

import pandas as pd

from scripts.loader import (
    ID_LABELS,
    REDACTED_VALUES,
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
    # 21 rows: 12 city + 6 Longmont + 1 sentinel + 1 NaN-CvrNumber + 1 NaN-TabulatorNum
    assert len(df) == 21


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
