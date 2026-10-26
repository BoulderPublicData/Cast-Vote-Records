"""Datasette metadata covers every election and says 'countywide' (#9)."""

from __future__ import annotations

from scripts import publish as publish_mod
from scripts.sources import SOURCES


def test_metadata_lists_every_election_including_2024_primary(tmp_path, monkeypatch):
    out = tmp_path / "metadata.yaml"
    monkeypatch.setattr(publish_mod, "METADATA_PATH", out)
    publish_mod._write_metadata(verbose=False)
    text = out.read_text()
    for src in SOURCES:
        assert f"      {src.election_key.replace('-', '_').lower()}:" in text, src
    assert "City of Boulder-eligible" not in text
    assert "countywide" in text
