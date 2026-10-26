"""Pandera schema tests for the cleaned wide CSV."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
import pytest

from scripts.schema import (
    ID_BLOCK_SCHEMA,
    OPTIONAL_ID_COLUMNS,
    REQUIRED_ID_COLUMNS,
    validate_contest_columns,
    validate_id_block,
)


def _make_valid_df() -> pd.DataFrame:
    return pd.DataFrame({
        "_ID/CvrNumber":    ["1", "2", "3"],
        "_ID/TabulatorNum": ["100", "100", "100"],
        "_ID/BatchId":      ["1", "1", "1"],
        "_ID/RecordId":     ["1", "2", "3"],
        "_ID/ImprintedId":  ["100-1-1", "100-1-2", "100-1-3"],
        "_ID/BallotType":   ["DS-01", "DS-01", "DS-01"],
        "_ID/n_sheets":     [1, 2, 1],
        "_ID/voter_id":     ["100-1-1", "100-1-2", "100-1-3"],
        "_ID/redacted":     [False, False, False],
        "Contest A::Alice": [1, 0, 0],
        "Contest A::Bob":   [0, 1, 0],
        "Contest A::Carol": [0, 0, 1],
    })


def test_required_id_columns_present():
    for label in ("CvrNumber", "TabulatorNum", "BatchId", "RecordId",
                  "ImprintedId", "BallotType", "n_sheets", "voter_id",
                  "redacted"):
        assert f"_ID/{label}" in REQUIRED_ID_COLUMNS


def test_optional_id_columns_listed():
    assert "_ID/CountingGroup" in OPTIONAL_ID_COLUMNS
    assert "_ID/PrecinctPortion" in OPTIONAL_ID_COLUMNS


def test_validate_id_block_accepts_well_formed_frame():
    df = _make_valid_df()
    assert validate_id_block(df) is df


def test_validate_id_block_rejects_missing_cvrnumber():
    df = _make_valid_df().drop(columns="_ID/CvrNumber")
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)


def test_validate_id_block_rejects_null_cvrnumber():
    df = _make_valid_df()
    df.loc[0, "_ID/CvrNumber"] = None
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)


def test_validate_contest_columns_accepts_0_1_nan():
    df = _make_valid_df()
    df.loc[0, "Contest A::Alice"] = None
    assert validate_contest_columns(df) is df


def test_validate_contest_columns_rejects_arbitrary_value():
    df = _make_valid_df()
    df.loc[0, "Contest A::Alice"] = 2
    with pytest.raises(ValueError, match="unexpected values"):
        validate_contest_columns(df)


def test_id_block_schema_is_a_pandera_schema():
    assert isinstance(ID_BLOCK_SCHEMA, pa.DataFrameSchema)
    for col in REQUIRED_ID_COLUMNS:
        assert col in ID_BLOCK_SCHEMA.columns


def test_validate_contest_columns_rejects_text_values():
    """Text would coerce to NaN and pass as 'not on the ballot' (#19)."""
    df = pd.DataFrame({"C::A": [1, "X"], "C::B": [0, "overvote"]})
    with pytest.raises(ValueError, match="non-numeric"):
        validate_contest_columns(df)


def test_validate_contest_columns_accepts_nullable_int8():
    df = _make_valid_df()
    df["Contest A::Alice"] = pd.array([1, None, 0], dtype="Int8")
    assert validate_contest_columns(df) is df


def test_validate_id_block_rejects_duplicate_voter_id():
    df = _make_valid_df()
    df.loc[2, "_ID/voter_id"] = "100-1-1"
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)


def test_validate_id_block_rejects_zero_sheets():
    df = _make_valid_df()
    df.loc[0, "_ID/n_sheets"] = 0
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)


def test_validate_id_block_rejects_numeric_ballot_type():
    df = _make_valid_df()
    df["_ID/BallotType"] = [1, 1, 1]
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)


def test_validate_id_block_allows_blank_ids_only_on_redacted_rows():
    df = _make_valid_df()
    df["_ID/TabulatorNum"] = df["_ID/TabulatorNum"].astype(object)
    df.loc[1, ["_ID/CvrNumber", "_ID/TabulatorNum"]] = ["Redacted", None]
    with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
        validate_id_block(df)
    df.loc[1, "_ID/redacted"] = True
    assert validate_id_block(df) is df
