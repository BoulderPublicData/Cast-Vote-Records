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


def _agg(proc: Path) -> Path:
    return proc / "2023-coordinated-aggregate-rows.csv"


def test_reconcile_checks_the_aggregate_table(staged):
    proc, _ = staged
    report = rec_mod.reconcile(verbose=False)
    row = next(r for r in report["rows"] if r["election_key"] == "2023-coordinated")
    assert row["agg_csv_rows"] == 4
    assert row["agg_marks_csv"] == 30
    assert row["agg_ballots_labelled"] == 10


def test_reconcile_fails_on_missing_aggregate_table(staged):
    proc, _ = staged
    _agg(proc).unlink()
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)


def test_reconcile_fails_on_changed_aggregate_mark(staged):
    proc, audit = staged
    df = pd.read_csv(_agg(proc), dtype=str)
    col = "City of Boulder Council Candidates (Vote For=1)::Alice"
    df.loc[0, col] = "2"
    df.to_csv(_agg(proc), index=False)
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)
    report = json.loads((audit / "reconcile.json").read_text())
    row = next(r for r in report["rows"] if r["election_key"] == "2023-coordinated")
    assert any("aggregate mark total" in p for p in row["problems"])


def test_reconcile_fails_on_changed_ballot_count(staged):
    proc, _ = staged
    df = pd.read_csv(_agg(proc), dtype=str)
    df.loc[df["_ID/n_ballots"].notna(), "_ID/n_ballots"] = "11"
    df.to_csv(_agg(proc), index=False)
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False)


# ---------------------------------------------------------------------------
# Statement of Votes check (#33)
# ---------------------------------------------------------------------------

# Minimal fixture totals: kept rows Alice 4 + 1 (NaN-label ballot), Bob 5,
# Carol 3 + 1 (RCV row); aggregates Alice 1+3+4, Bob 1+2+5, Carol 0+1+3.
KEPT = {"Alice": 5, "Bob": 5, "Carol": 4}
AGG = {"Alice": 8, "Bob": 8, "Carol": 4}


def _write_sov(tmp_path: Path, votes: dict[str, int], contest="City of Boulder Council Candidates"):
    sov_dir = tmp_path / "sov"
    sov_dir.mkdir(exist_ok=True)
    # Two precincts per choice: the check sums them.
    rows = []
    for name, v in votes.items():
        rows += [(contest, name, v - v // 2), (contest, name, v // 2)]
    pd.DataFrame(rows, columns=["contest", "candidate_or_option", "votes"]).to_csv(
        sov_dir / "2023-coordinated-boulder-county.csv", index=False
    )
    return sov_dir


def _write_exceptions(tmp_path: Path, rows: list[dict]) -> None:
    lookups = tmp_path / "lookups"
    lookups.mkdir(exist_ok=True)
    base = {
        "election_key": "2023-coordinated",
        "contest": "City of Boulder Council Candidates (Vote For=1)",
        "reason": "test",
        "evidence": "test",
        "remove_when": "never",
    }
    pd.DataFrame([{**base, **r} for r in rows], columns=list(rec_mod.EXCEPTION_COLUMNS)).to_csv(
        lookups / "sov-exceptions.csv", index=False
    )


def _sov_row(report: dict) -> dict:
    return next(r for r in report["rows"] if r["election_key"] == "2023-coordinated")


def test_sov_check_passes_when_kept_plus_aggregates_equal_the_sov(staged, tmp_path):
    exact = {k: KEPT[k] + AGG[k] for k in KEPT}
    report = rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, exact))
    assert report["has_regression"] is False
    sov = report["sov"][0]
    assert sov["choices_matched"] == 3
    assert sov["cvr_choices"] == 5  # Dana and Eve are not in this SoV
    assert sov["cvr_marks"] == 14
    assert sov["aggregate_marks"] == 20
    assert sov["sov_votes"] == 34
    assert _sov_row(report)["sov_status"] == "ok"


def test_sov_check_fails_on_a_difference(staged, tmp_path):
    """Before #33 this was informational; a difference now fails the run."""
    _, audit = staged
    votes = {k: KEPT[k] + AGG[k] for k in KEPT} | {"Bob": 12}
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, votes))
    report = json.loads((audit / "reconcile.json").read_text())
    row = _sov_row(report)
    assert row["sov_status"] == "MISMATCH"
    assert any("SoV:" in p and "Bob" in p and "delta +1" in p for p in row["problems"])


def test_sov_check_fails_when_only_kept_rows_match(staged, tmp_path):
    """Dropping aggregates leaves totals under the SoV; that must not pass."""
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, dict(KEPT)))


def test_documented_exception_passes(staged, tmp_path):
    votes = {k: KEPT[k] + AGG[k] for k in KEPT} | {"Bob": 12}
    _write_exceptions(tmp_path, [{"choice": "Bob", "expected_delta": 1}])
    report = rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, votes))
    assert report["has_regression"] is False
    assert _sov_row(report)["sov_status"] == "ok (1 excepted)"
    (exc,) = report["sov_exceptions"]
    assert exc["status"] == "applied" and exc["delta"] == 1


def test_exception_with_a_different_delta_fails(staged, tmp_path):
    votes = {k: KEPT[k] + AGG[k] for k in KEPT} | {"Bob": 10}
    _write_exceptions(tmp_path, [{"choice": "Bob", "expected_delta": 1}])
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, votes))


def test_fixed_upstream_makes_an_exception_stale_without_failing(staged, tmp_path, capsys):
    exact = {k: KEPT[k] + AGG[k] for k in KEPT}
    _write_exceptions(
        tmp_path,
        [{"choice": "Bob", "expected_delta": 1}, {"choice": "Zed", "expected_delta": 2}],
    )
    report = rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, exact))
    assert report["has_regression"] is False
    statuses = {e["choice"]: e["status"] for e in report["sov_exceptions"]}
    assert statuses == {"Bob": "stale", "Zed": "unmatched"}
    assert "stale" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [
        {"choice": "Bob", "expected_delta": 0},
        {"choice": "Bob", "expected_delta": "one"},
        {"choice": "Bob", "expected_delta": 1, "reason": ""},
        {"choice": "Bob", "expected_delta": 1, "evidence": ""},
        {"choice": "Bob", "expected_delta": 1, "election_key": "1999-general"},
    ],
)
def test_malformed_exceptions_file_fails(staged, tmp_path, bad):
    exact = {k: KEPT[k] + AGG[k] for k in KEPT}
    _write_exceptions(tmp_path, [bad])
    with pytest.raises(SystemExit, match="FAIL"):
        rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, exact))


def test_duplicate_exception_fails(staged, tmp_path):
    exact = {k: KEPT[k] + AGG[k] for k in KEPT}
    row = {"choice": "Bob", "expected_delta": 1}
    _write_exceptions(tmp_path, [row, row])
    with pytest.raises(SystemExit, match="duplicate"):
        rec_mod.reconcile(verbose=False, sov_dir=_write_sov(tmp_path, exact))


def test_sov_with_no_matching_names_fails(staged, tmp_path):
    sov_dir = _write_sov(tmp_path, {"Somebody": 3}, contest="Another Contest")
    with pytest.raises(SystemExit):
        rec_mod.reconcile(verbose=False, sov_dir=sov_dir)


def test_missing_sov_file_is_not_a_failure(staged, tmp_path):
    sov_dir = tmp_path / "empty-sov"
    sov_dir.mkdir()
    report = rec_mod.reconcile(verbose=False, sov_dir=sov_dir)
    assert report["has_regression"] is False
    assert _sov_row(report)["sov_status"] == "no SoV"


def test_name_matching():
    assert rec_mod._norm("Town of Erie - Council Member District 1 (Vote For=2)") == (
        "town of erie - council member district 1"
    )
    assert rec_mod._norm("Town of Erie-Council  Member District 1") == (
        "town of erie - council member district 1"
    )
    assert rec_mod._norm("Board (Number of positions=3)") == "board"
    assert rec_mod._norm("Yes/For") != rec_mod._norm("Yes")


def test_repo_exceptions_file_is_valid(repo_root):
    """The reviewed list in data/lookups/ parses, and every row has a reason,
    evidence and a non-zero expected difference."""
    exc = rec_mod.load_sov_exceptions(repo_root / "data" / "lookups" / "sov-exceptions.csv")
    assert len(exc) > 0
    assert (exc["expected_delta"] != 0).all()
