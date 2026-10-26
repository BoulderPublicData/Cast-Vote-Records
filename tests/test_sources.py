"""Tests for the election source manifest."""

from __future__ import annotations

import pytest

from scripts.sources import ARCHIVED_ORIGINALS, SOURCES, get_source


def test_sources_has_unique_keys():
    keys = [s.election_key for s in SOURCES]
    assert len(keys) == len(set(keys)), "duplicate election_key in SOURCES"


def test_sources_filenames_match_keys_loosely():
    for src in SOURCES:
        assert src.filename.endswith(".xlsx"), src
        assert str(src.year) in src.filename, src
        assert str(src.year) in src.election_key, src


def test_archived_originals_are_not_processed():
    processed = {s.filename for s in SOURCES}
    for arc in ARCHIVED_ORIGINALS:
        assert arc.filename not in processed
        assert arc.notes


def test_every_original_on_disk_is_registered(repo_root):
    """Each file in data/original/ is either a SOURCE or explicitly archived."""
    known = {s.filename for s in SOURCES} | {a.filename for a in ARCHIVED_ORIGINALS}
    on_disk = {p.name for p in (repo_root / "data" / "original").glob("*.xlsx")}
    assert on_disk <= known, on_disk - known


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
