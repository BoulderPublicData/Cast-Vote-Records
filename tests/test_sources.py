"""Tests for the election source manifest."""

from __future__ import annotations

import pytest

from scripts.sources import ARCHIVED_ORIGINALS, SOURCES, get_source


def test_sources_has_unique_keys():
    keys = [s.election_key for s in SOURCES]
    assert len(keys) == len(set(keys)), "duplicate election_key in SOURCES"


def test_sources_filenames_match_keys_loosely():
    for src in SOURCES:
        assert src.filename.endswith((".xlsx", ".csv")), src
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
    orig = repo_root / "data" / "original"
    on_disk = {p.name for p in orig.iterdir() if p.suffix in (".xlsx", ".csv")}
    assert on_disk <= known, on_disk - known


def test_get_source_round_trip():
    for src in SOURCES:
        assert get_source(src.election_key) is src


def test_get_source_unknown_raises():
    with pytest.raises(KeyError):
        get_source("1999-Coordinated")


def test_sources_span_2017_to_2025():
    years = sorted({s.year for s in SOURCES})
    assert min(years) == 2017
    assert max(years) >= 2025
    assert set(range(2017, 2026)) <= set(years), "a year between 2017 and 2025 is missing"


def test_election_keys_follow_the_shared_format():
    """`{year}-{type}`, lowercase, type from the vocabulary shared with
    Election-Results (#23)."""
    from scripts.sources import ELECTION_TYPES

    for src in SOURCES:
        assert src.election_type in ELECTION_TYPES, src
        assert src.election_key == f"{src.year}-{src.election_type}", src


def test_old_style_key_gets_a_hint():
    with pytest.raises(KeyError, match="2024-general"):
        get_source("2024-General")


def test_sources_for_years():
    from scripts.sources import sources_for_years

    assert [s.election_key for s in sources_for_years([2024])] == ["2024-primary", "2024-general"]
