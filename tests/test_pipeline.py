"""Integration test for the orchestrator on a tmp fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from scripts import clean as clean_mod
from scripts import config as config_mod


def _stage(tmp_path: Path, monkeypatch, files: dict[str, Path]) -> Path:
    """Point every pipeline path (including the manifest) at tmp dirs and copy
    ``files`` into ``original/``. Returns the processed dir."""
    orig_dir = tmp_path / "original"
    proc_dir = tmp_path / "processed"
    orig_dir.mkdir(exist_ok=True)
    for name, src in files.items():
        shutil.copy(src, orig_dir / name)

    monkeypatch.setattr(config_mod, "ORIGINAL_DIR", orig_dir)
    monkeypatch.setattr(config_mod, "PROCESSED_DIR", proc_dir)
    monkeypatch.setattr(config_mod, "CVR_DIR", proc_dir)
    monkeypatch.setattr(config_mod, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(config_mod, "LOOKUPS_DIR", tmp_path / "lookups")
    monkeypatch.setattr(config_mod, "ORIGINAL_MANIFEST", orig_dir / "manifest.json")
    monkeypatch.setattr(config_mod, "PROVENANCE_CSV", proc_dir / "provenance.csv")
    monkeypatch.setattr(config_mod, "SUMMARY_CSV", proc_dir / "_summary.csv")
    return proc_dir


def test_clean_emits_per_voter_csv_for_multisheet_fixture(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    """End-to-end: stage one multi-sheet fixture as 2023-coordinated,
    point the pipeline at tmp dirs, run clean, confirm the wide CSV
    exists with merged voter rows."""
    proc_dir = _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})

    summary = clean_mod.clean(elections=["2023-coordinated"], verbose=False)

    assert not summary.empty
    out = proc_dir / "2023-coordinated-county-wide-by-voter.csv"
    assert out.exists()
    row = summary.loc["2023-coordinated"]
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
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})
    calls = []
    real = clean_mod.validate_contest_columns
    monkeypatch.setattr(
        clean_mod, "validate_contest_columns", lambda df: calls.append(len(df)) or real(df)
    )
    clean_mod.clean(elections=["2023-coordinated"], verbose=False)
    assert calls == [9]


def test_one_bad_election_does_not_stop_the_others(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    """A file with text in a contest cell fails loudly, but the other
    election is still cleaned and written (#14, #19)."""
    bad = tmp_path / "bad.xlsx"
    raw = pd.read_excel(multisheet_cvr_path, header=None, engine="openpyxl")
    raw.iloc[5, 6] = "overvote"
    raw.to_excel(bad, header=False, index=False)
    proc_dir = _stage(
        tmp_path,
        monkeypatch,
        {
            "2023-Coordinated-CVR.xlsx": bad,
            "2025-Coordinated-CVR.xlsx": multisheet_cvr_path,
        },
    )
    with pytest.raises(SystemExit) as exc:
        clean_mod.clean(elections=["2023-coordinated", "2025-coordinated"], verbose=False)
    assert exc.value.code == 1
    assert (proc_dir / "2025-coordinated-county-wide-by-voter.csv").exists()
    assert not (proc_dir / "2023-coordinated-county-wide-by-voter.csv").exists()
    summary = pd.read_csv(proc_dir / "_summary.csv")
    assert list(summary["election_key"]) == ["2025-coordinated"]


def test_clean_reads_the_staged_manifest_not_the_repo_one(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    proc_dir = _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})
    (tmp_path / "original" / "manifest.json").write_text(
        '{"2023-Coordinated-CVR.xlsx": {"sha256": "feedface", "size": 1, '
        '"retrieved_at": "2023-11-29T00:00:00Z"}}'
    )
    clean_mod.clean(elections=["2023-coordinated"], verbose=False)
    prov = pd.read_csv(proc_dir / "provenance.csv")
    assert prov.loc[0, "original_sha256"] == "feedface"
    assert prov.loc[0, "retrieved_at"] == "2023-11-29T00:00:00Z"


def test_partial_clean_upserts_summary_and_provenance(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    minimal_cvr_path: Path,
    monkeypatch,
):
    """`clean --election X` must not drop the other elections' rows (#10)."""
    proc_dir = _stage(
        tmp_path,
        monkeypatch,
        {
            "2023-Coordinated-CVR.xlsx": multisheet_cvr_path,
            "2025-Coordinated-CVR.xlsx": minimal_cvr_path,
        },
    )
    clean_mod.clean(verbose=False)
    first = pd.read_csv(proc_dir / "_summary.csv")
    assert list(first["election_key"]) == ["2023-coordinated", "2025-coordinated"]

    clean_mod.clean(elections=["2025-coordinated"], verbose=False)
    for name in ("_summary.csv", "provenance.csv"):
        df = pd.read_csv(proc_dir / name)
        assert list(df["election_key"]) == ["2023-coordinated", "2025-coordinated"], name
    summary = pd.read_csv(proc_dir / "_summary.csv").set_index("election_key")
    assert int(summary.loc["2023-coordinated", "n_voters"]) == 9
    assert int(summary.loc["2025-coordinated", "n_voters"]) == 21


def test_failed_election_keeps_its_previous_summary_row(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    proc_dir = _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})
    clean_mod.clean(elections=["2023-coordinated"], verbose=False)
    bad = tmp_path / "original" / "2023-Coordinated-CVR.xlsx"
    raw = pd.read_excel(bad, header=None, engine="openpyxl")
    raw.iloc[5, 6] = "X"
    raw.to_excel(bad, header=False, index=False)
    with pytest.raises(SystemExit):
        clean_mod.clean(elections=["2023-coordinated"], verbose=False)
    summary = pd.read_csv(proc_dir / "_summary.csv")
    assert list(summary["election_key"]) == ["2023-coordinated"]


def test_clean_stops_on_lfs_pointer(tmp_path: Path, monkeypatch):
    _stage(tmp_path, monkeypatch, {})
    (tmp_path / "original" / "2023-Coordinated-CVR.xlsx").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:8c0fb890040ae98873a6d957feddf2e1871fc559da5d783089bab4aec584c942\n"
        "size 19645248\n"
    )
    with pytest.raises(SystemExit, match="git lfs pull"):
        clean_mod.clean(elections=["2023-coordinated"], verbose=False)


def test_clean_by_year_and_old_key_hint(
    tmp_path: Path,
    multisheet_cvr_path: Path,
    monkeypatch,
):
    proc_dir = _stage(tmp_path, monkeypatch, {"2023-Coordinated-CVR.xlsx": multisheet_cvr_path})
    clean_mod.clean(years=[2023], verbose=False)
    assert (proc_dir / "2023-coordinated-county-wide-by-voter.csv").exists()
    with pytest.raises(SystemExit, match="lowercase"):
        clean_mod.clean(elections=["2023-Coordinated"], verbose=False)
