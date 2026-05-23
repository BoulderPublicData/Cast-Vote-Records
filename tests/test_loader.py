"""Tests for the loader (header reconstruction)."""

from __future__ import annotations

import pandas as pd

from cvr_pipeline.loader import (
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

    # Six ID columns at the front
    assert id_columns(df) == [
        ("_ID", "CvrNumber"),
        ("_ID", "TabulatorNum"),
        ("_ID", "BatchId"),
        ("_ID", "RecordId"),
        ("_ID", "ImprintedId"),
        ("_ID", "BallotType"),
    ]

    # 20 rows: 12 city + 6 Longmont + 1 sentinel-redacted + 1 NaN-CvrNumber aggregate
    assert len(df) == 20


def test_load_raw_cvr_contest_columns(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    contests = unique_contests(df)
    assert "City of Boulder Council Candidates (Vote For=1)" in contests
    assert "City of Longmont - Mayor (Vote For=1)" in contests

    # And the contest columns are (contest, candidate)
    cob_cols = [
        c for c in contest_columns(df)
        if c[0] == "City of Boulder Council Candidates (Vote For=1)"
    ]
    candidates = {c[1] for c in cob_cols}
    assert candidates == {"Alice", "Bob", "Carol"}


def test_id_labels_includes_all_known_variants():
    # Spot-check that every label our real-world CVRs use is present
    for label in (
        "CvrNumber", "TabulatorNum", "BatchId", "RecordId",
        "ImprintedId", "BallotType", "CountingGroup", "PrecinctPortion",
    ):
        assert label in ID_LABELS


def test_redacted_values_contains_known_strings():
    assert "RCV Redacted & Randomly Sorted" in REDACTED_VALUES
    assert "Redacted & Aggregated" in REDACTED_VALUES
