"""Tests for the independent reconcile check (#8)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from scripts import clean as clean_mod
from scripts import config as config_mod
from scripts import reconcile as rec_mod


@pytest.fixture()
def staged(tmp_path: Path, minimal_cvr_path: Path, monkeypatch):
    """Clean the minimal fixture as 2023-coordinated in tmp dirs."""
    orig = tmp_path / "original"
    proc = tmp_path / "processed"
    audit = tmp_path / "audit"
    orig.mkdir()
    shutil.copy(minimal_cvr_path, orig / "2023-Coordinated-CVR.xlsx")
    monkeypatch.setattr(config_mod, "ORIGINAL_DIR", orig)
    monkeypatch.setattr(config_mod, "PROCESSED_DIR", proc)
    monkeypatch.setattr(config_mod, "CVR_DIR", proc)
    monkeypatch.setattr(config_mod, "AUDIT_DIR", audit)
    monkeypatch.setattr(config_mod, "LOOKUPS_DIR", tmp_path / "lookups")
    monkeypatch.setattr(config_mod, "ORIGINAL_MANIFEST", orig / "manifest.json")
    monkeypatch.setattr(config_mod, "SUMMARY_CSV", proc / "_summary.csv")
    monkeypatch.setattr(config_mod, "PROVENANCE_CSV", proc / "provenance.csv")
    clean_mod.clean(elections=["2023-coordinated"], verbose=False)
    return proc, audit


def _csv(proc: Path) -> Path:
    return proc / "2023-coordinated-county-wide-by-voter.csv"


def test_reconcile_passes_on_clean_output(staged):
    _, audit = staged
    report = rec_mod.reconcile(verbose=False)
    row = next(r for r in report["rows"] if r["election_key"] == "2023-coordinated")
    assert row["status"] == "ok"
    assert row["aggregate_rows"] == 4
    assert row["sum_n_sheets"] == row["sheets_kept"] == 21
    assert row["total_marks_csv"] == row["total_marks_raw"]
    assert (audit / "reconcile.md").exists()


def test_reconcile_skips_missing_originals_without_crashing(staged):
    """Every other election has no original in tmp; skip rows must not
    raise KeyError when the report is rendered."""
    report = rec_mod.reconcile(verbose=False)
    skipped = [r for r in report["rows"] if r["status"] == "skip-no-original"]
    assert len(skipped) == len(rec_mod.SOURCES) - 1


def test_reconcile_fails_on_truncated_csv(staged):
    """The review's repro: truncating the CSV to its header must fail."""
    proc, _ = staged
    header = _csv(proc).read_text().splitlines()[0]
    _csv(proc).write_text(header + "\n")
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)


def test_reconcile_fails_on_changed_mark(staged):
    proc, audit = staged
    df = pd.read_csv(_csv(proc), dtype={"_ID/BallotType": str})
    col = "City of Boulder Council Candidates (Vote For=1)::Alice"
    df.loc[df[col] == 0, col] = 1
    df.to_csv(_csv(proc), index=False)
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)
    report = json.loads((audit / "reconcile.json").read_text())
    row = next(r for r in report["rows"] if r["election_key"] == "2023-coordinated")
    assert any("mark total" in p for p in row["problems"])


def test_reconcile_fails_on_duplicate_voter_id(staged):
    proc, _ = staged
    df = pd.read_csv(_csv(proc), dtype={"_ID/BallotType": str})
    df.loc[1, "_ID/voter_id"] = df.loc[0, "_ID/voter_id"]
    df.to_csv(_csv(proc), index=False)
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)


def test_reconcile_fails_when_election_missing_from_summary(staged):
    proc, _ = staged
    s = pd.read_csv(proc / "_summary.csv")
    s.iloc[0:0].to_csv(proc / "_summary.csv", index=False)
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)


def test_sov_crosscheck_is_informational(staged, tmp_path):
    sov_dir = tmp_path / "sov"
    sov_dir.mkdir()
    pd.DataFrame({
        "contest": ["City of Boulder Council Candidates"] * 3,
        "candidate_or_option": ["Alice", "Bob", "Carol"],
        "votes": [10, 7, 6],   # official totals incl. aggregated ballots
    }).to_csv(sov_dir / "2023-coordinated-boulder-county.csv", index=False)
    report = rec_mod.reconcile(verbose=False, sov_dir=sov_dir)
    assert report["has_regression"] is False
    sov = report["sov"][0]
    assert sov["choices_matched"] == 3
    # Kept rows: Alice 4 + 1 (NaN-label ballot), Bob 5, Carol 3 + 1 (RCV row) = 14
    # Aggregates: Alice 1+3+4, Bob 1+2+5, Carol 0+1+3 = 20
    assert sov["cvr_marks"] == 14
    assert sov["aggregate_marks"] == 20
    assert sov["sov_votes"] == 23
