"""Tests for the cleaner (filter, integrity, auto-detection)."""

from __future__ import annotations

import pandas as pd
import pytest

from cvr_pipeline.cleaner import (
    clean_city_cvr,
    detect_city_ballot_types,
    flatten_columns,
)
from cvr_pipeline.loader import load_raw_cvr


def test_detect_city_ballot_types_finds_ds01(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    assert detect_city_ballot_types(df) == ("DS-01",)


def test_detect_city_ballot_types_min_ballots_threshold_drops_aggregate(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    # The DS-02 aggregate row (NaN CvrNumber) has City of Boulder votes filled
    # in. The default min_ballots threshold must reject it; with min_ballots=0
    # it would falsely flag DS-02 as a city ballot type.
    assert "DS-02" not in detect_city_ballot_types(df)


def test_detect_city_ballot_types_returns_empty_when_marker_absent(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    # No contest in the fixture mentions "Lafayette"
    assert detect_city_ballot_types(df, marker="Lafayette") == ()


def test_clean_city_cvr_drops_redacted_and_filters_city(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    result = clean_city_cvr(df, election_key="test")

    assert result.n_raw_rows == 20
    # Both the sentinel-string row and the NaN-CvrNumber aggregate row should drop
    assert result.n_redacted_dropped == 2
    assert result.city_ballot_types == ("DS-01",)
    assert result.n_city_ballots == 12


def test_clean_city_cvr_drops_all_nan_choice_columns(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    result = clean_city_cvr(df, election_key="test")

    # Longmont contest columns are all-NaN for DS-01 voters and must be dropped
    cols = list(result.cleaned.columns)
    assert not any("Longmont" in c for c in cols)
    # City of Boulder columns survive
    assert any("City of Boulder" in c for c in cols)


def test_clean_city_cvr_flattens_columns(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    result = clean_city_cvr(df, election_key="test")

    for c in result.cleaned.columns:
        assert isinstance(c, str)
    assert "_ID/CvrNumber" in result.cleaned.columns
    assert "_ID/BallotType" in result.cleaned.columns


def test_clean_city_cvr_empty_result_when_no_city_ballots(minimal_cvr_path):
    df = load_raw_cvr(minimal_cvr_path)
    # Force-pass an empty city_ballot_types
    result = clean_city_cvr(df, election_key="test", city_ballot_types=())
    assert result.n_city_ballots == 0
    assert result.cleaned.shape[0] == 0


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


def test_clean_city_cvr_integrity_check_catches_missing_id():
    # Construct a df with no BallotType column
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
