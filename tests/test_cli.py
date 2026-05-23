"""Integration test for the CLI's build subcommand on a tmp fixture."""

from __future__ import annotations

from pathlib import Path
import shutil

from cvr_pipeline.cli import build
from cvr_pipeline.sources import CvrSource


def test_build_emits_clean_csv(tmp_path: Path, minimal_cvr_path: Path, monkeypatch):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "clean"
    raw_dir.mkdir()

    # Stage the fixture into raw_dir under a known name and patch SOURCES
    shutil.copy(minimal_cvr_path, raw_dir / "test-coord.xlsx")

    fake_source = CvrSource(
        election_key="test-Coordinated",
        year=2099,
        election_type="Coordinated",
        filename="test-coord.xlsx",
        public_url=None,
    )
    monkeypatch.setattr("cvr_pipeline.cli.SOURCES", (fake_source,))

    summary = build(raw_dir=raw_dir, clean_dir=clean_dir, verbose=False)

    assert not summary.empty
    assert (clean_dir / "test-Coordinated-city-of-boulder-wide.csv").exists()
    assert (clean_dir / "_summary.csv").exists()

    row = summary.loc["test-Coordinated"]
    assert int(row["n_city_ballots"]) == 12
    assert row["city_ballot_types"] == "DS-01"
