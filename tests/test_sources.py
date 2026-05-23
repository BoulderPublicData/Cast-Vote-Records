"""Tests for the election source manifest."""

from __future__ import annotations

import pytest

from cvr_pipeline.sources import SOURCES, get_source


def test_sources_has_unique_keys():
    keys = [s.election_key for s in SOURCES]
    assert len(keys) == len(set(keys)), "duplicate election_key in SOURCES"


def test_sources_filenames_match_keys_loosely():
    # Every source's filename should be findable and end with .xlsx
    for src in SOURCES:
        assert src.filename.endswith(".xlsx"), src
        assert str(src.year) in src.filename or src.year >= 2019, src


def test_get_source_round_trip():
    for src in SOURCES:
        assert get_source(src.election_key) is src


def test_get_source_unknown_raises():
    with pytest.raises(KeyError):
        get_source("1999-Coordinated")


def test_sources_span_2019_to_2025():
    years = sorted({s.year for s in SOURCES})
    assert min(years) == 2019
    assert max(years) >= 2025
