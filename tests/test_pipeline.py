"""Integration test for the pipeline CLI on a tmp fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts import clean as clean_mod
from scripts import config as config_mod


def test_clean_emits_wide_csv_for_synthetic_fixture(
    tmp_path: Path, minimal_cvr_path: Path, monkeypatch,
):
    """End-to-end: stage one fixture as 2023-Coordinated, point the pipeline at
    tmp dirs, run clean, confirm the wide CSV exists with the right shape.
    """
    orig_dir = tmp_path / "original"
    proc_dir = tmp_path / "processed"
    audit_dir = tmp_path / "audit"
    lookups_dir = tmp_path / "lookups"
    orig_dir.mkdir()
    shutil.copy(minimal_cvr_path, orig_dir / "2023-Coordinated-CVR.xlsx")

    monkeypatch.setattr(config_mod, "ORIGINAL_DIR", orig_dir)
    monkeypatch.setattr(config_mod, "PROCESSED_DIR", proc_dir)
    monkeypatch.setattr(config_mod, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(config_mod, "LOOKUPS_DIR", lookups_dir)
    monkeypatch.setattr(config_mod, "ORIGINAL_MANIFEST", orig_dir / "manifest.json")
    monkeypatch.setattr(config_mod, "PROVENANCE_CSV", proc_dir / "provenance.csv")
    monkeypatch.setattr(config_mod, "SUMMARY_CSV", proc_dir / "_summary.csv")
    monkeypatch.setattr(clean_mod, "ORIGINAL_DIR", orig_dir)
    monkeypatch.setattr(clean_mod, "PROCESSED_DIR", proc_dir)
    monkeypatch.setattr(clean_mod, "PROVENANCE_CSV", proc_dir / "provenance.csv")
    monkeypatch.setattr(clean_mod, "SUMMARY_CSV", proc_dir / "_summary.csv")

    summary = clean_mod.clean(elections=["2023-Coordinated"], verbose=False)

    assert not summary.empty
    out = proc_dir / "2023-Coordinated-city-of-boulder-wide.csv"
    assert out.exists()
    assert int(summary.loc["2023-Coordinated", "n_city_ballots"]) == 12
    assert summary.loc["2023-Coordinated", "city_ballot_types"] == "DS-01"

    assert (proc_dir / "provenance.csv").exists()
    assert (proc_dir / "_summary.csv").exists()
