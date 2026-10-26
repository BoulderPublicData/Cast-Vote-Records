"""Integration test for the orchestrator on a tmp fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from scripts import clean as clean_mod
from scripts import config as config_mod


def _stage(tmp_path: Path, monkeypatch, files: dict[str, Path]) -> Path:
    """Point every pipeline path at tmp dirs and copy ``files`` into
    ``original/``. Returns the processed dir."""
    orig_dir = tmp_path / "original"
    proc_dir = tmp_path / "processed"
    audit_dir = tmp_path / "audit"
    lookups_dir = tmp_path / "lookups"
    orig_dir.mkdir()
    for name, src in files.items():
        shutil.copy(src, orig_dir / name)

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
    return proc_dir


def test_clean_emits_per_voter_csv_for_multisheet_fixture(
    tmp_path: Path, multisheet_cvr_path: Path, monkeypatch,
):
    """End-to-end: stage one multi-sheet fixture as 2023-Coordinated,
    point the pipeline at tmp dirs, run clean, confirm the wide CSV
    exists with merged voter rows."""
    proc_dir = _stage(tmp_path, monkeypatch,
                      {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})

    summary = clean_mod.clean(elections=["2023-Coordinated"], verbose=False)

    assert not summary.empty
    out = proc_dir / "2023-Coordinated-county-wide-by-voter.csv"
    assert out.exists()
    row = summary.loc["2023-Coordinated"]
    assert int(row["n_voters"]) == 9
    assert int(row["n_sheets_after_redaction"]) == 13
    assert int(row["n_aggregate_rows_dropped"]) == 1
    assert int(row["n_redacted_kept"]) == 0
    assert row["multi_sheet_ballot_types"] == "DS-01"

    assert (proc_dir / "provenance.csv").exists()
    assert (proc_dir / "_summary.csv").exists()

    # Written types: BallotType text, marks as integers (#18)
    text = out.read_text()
    assert ",1.0," not in text and ",0.0," not in text
    df = pd.read_csv(out, dtype={"_ID/BallotType": str})
    assert df["_ID/voter_id"].is_unique
    assert int(df["_ID/n_sheets"].sum()) == 13


def test_clean_calls_contest_validator(
    tmp_path: Path, multisheet_cvr_path: Path, monkeypatch,
):
    _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})
    calls = []
    real = clean_mod.validate_contest_columns
    monkeypatch.setattr(clean_mod, "validate_contest_columns",
                        lambda df: calls.append(len(df)) or real(df))
    clean_mod.clean(elections=["2023-Coordinated"], verbose=False)
    assert calls == [9]


def test_one_bad_election_does_not_stop_the_others(
    tmp_path: Path, multisheet_cvr_path: Path, monkeypatch,
):
    """A file with text in a contest cell fails loudly, but the other
    election is still cleaned and written (#14, #19)."""
    bad = tmp_path / "bad.xlsx"
    raw = pd.read_excel(multisheet_cvr_path, header=None, engine="openpyxl")
    raw.iloc[5, 6] = "overvote"
    raw.to_excel(bad, header=False, index=False)
    proc_dir = _stage(tmp_path, monkeypatch, {
        "2023-Coordinated-CVR.xlsx": bad,
        "2025-Coordinated-CVR.xlsx": multisheet_cvr_path,
    })
    with pytest.raises(SystemExit) as exc:
        clean_mod.clean(elections=["2023-Coordinated", "2025-Coordinated"],
                        verbose=False)
    assert exc.value.code == 1
    assert (proc_dir / "2025-Coordinated-county-wide-by-voter.csv").exists()
    assert not (proc_dir / "2023-Coordinated-county-wide-by-voter.csv").exists()
    summary = pd.read_csv(proc_dir / "_summary.csv")
    assert list(summary["election_key"]) == ["2025-Coordinated"]
