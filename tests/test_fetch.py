"""Tests for LFS-pointer detection and manifest verification (#11, #22)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import config as config_mod
from scripts import fetch as fetch_mod
from scripts.loader import load_raw_cvr

POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:447217d6eb02a399badf85ea7605b3a89d2437e42b20373e786d6b84d6b19ae3\n"
    "size 16789916\n"
)


@pytest.fixture()
def orig(tmp_path: Path, monkeypatch, minimal_cvr_path: Path) -> Path:
    d = tmp_path / "original"
    d.mkdir()
    shutil.copy(minimal_cvr_path, d / "2023-Coordinated-CVR.xlsx")
    monkeypatch.setattr(config_mod, "ORIGINAL_DIR", d)
    monkeypatch.setattr(config_mod, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(config_mod, "CVR_DIR", tmp_path / "processed" / "cast-vote-records")
    monkeypatch.setattr(config_mod, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(config_mod, "LOOKUPS_DIR", tmp_path / "lookups")
    monkeypatch.setattr(config_mod, "ORIGINAL_MANIFEST", d / "manifest.json")
    # Never touch the network: no source gets downloaded in these tests.
    monkeypatch.setattr(fetch_mod, "download_one", lambda src, force=False: False)
    return d


def test_is_lfs_pointer(tmp_path: Path, minimal_cvr_path: Path):
    p = tmp_path / "ptr.xlsx"
    p.write_text(POINTER)
    assert fetch_mod.is_lfs_pointer(p)
    assert not fetch_mod.is_lfs_pointer(minimal_cvr_path)


def test_fetch_stops_on_lfs_pointer_and_keeps_manifest(orig: Path):
    (orig / "2019-CVR.xlsx").write_text(POINTER)
    manifest = {"2019-CVR.xlsx": {"sha256": "447217d6eb02", "size": 16789916}}
    (orig / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SystemExit, match="git lfs pull"):
        fetch_mod.fetch(verbose=False)
    assert json.loads((orig / "manifest.json").read_text()) == manifest


def test_loader_names_lfs_pointer(tmp_path: Path):
    p = tmp_path / "ptr.xlsx"
    p.write_text(POINTER)
    with pytest.raises(fetch_mod.LfsPointerError, match="git lfs pull"):
        load_raw_cvr(p)


def test_fetch_fails_on_hash_mismatch_without_rewriting(orig: Path):
    manifest = {"2023-Coordinated-CVR.xlsx": {"sha256": "0" * 64, "size": 1}}
    (orig / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SystemExit):
        fetch_mod.fetch(verbose=False)
    assert json.loads((orig / "manifest.json").read_text()) == manifest


def test_update_manifest_accepts_a_deliberate_change(orig: Path):
    manifest = {"2023-Coordinated-CVR.xlsx": {"sha256": "0" * 64, "size": 1,
                                              "first_committed_at": "2026-05-23T19:03:50Z"}}
    (orig / "manifest.json").write_text(json.dumps(manifest))
    out = fetch_mod.fetch(update_manifest=True, verbose=False)
    entry = out["2023-Coordinated-CVR.xlsx"]
    assert entry["sha256"] == fetch_mod.sha256_file(orig / "2023-Coordinated-CVR.xlsx")
    assert entry["first_committed_at"] == "2026-05-23T19:03:50Z"


def test_matching_manifest_is_kept_and_mtime_is_never_recorded(orig: Path):
    digest = fetch_mod.sha256_file(orig / "2023-Coordinated-CVR.xlsx")
    manifest = {"2023-Coordinated-CVR.xlsx": {
        "sha256": digest, "size": 1, "mtime_iso": "2026-05-24T11:34:33Z",
        "retrieved_at": "2023-11-29T00:00:00Z",
    }}
    (orig / "manifest.json").write_text(json.dumps(manifest))
    out = fetch_mod.fetch(verbose=False)
    entry = out["2023-Coordinated-CVR.xlsx"]
    assert "mtime_iso" not in entry
    assert entry["retrieved_at"] == "2023-11-29T00:00:00Z"
    assert "xlsx_modified" in entry   # workbook's own timestamp


def test_download_records_retrieved_at(orig: Path, monkeypatch):
    def fake_download(src, force=False):
        if src.filename == "2025-Coordinated-CVR.xlsx":
            shutil.copy(orig / "2023-Coordinated-CVR.xlsx", orig / src.filename)
            return True
        return False
    monkeypatch.setattr(fetch_mod, "download_one", fake_download)
    monkeypatch.setattr(fetch_mod, "_now", lambda: "2026-10-26T00:00:00Z")
    out = fetch_mod.fetch(verbose=False)
    assert out["2025-Coordinated-CVR.xlsx"]["retrieved_at"] == "2026-10-26T00:00:00Z"
    assert out["2023-Coordinated-CVR.xlsx"]["retrieved_at"] == ""
