"""Repository layout mirrors Election-Results: one folder per dataset (#23)."""

from __future__ import annotations

import subprocess

from scripts import config
from scripts.sources import SOURCES


def test_dataset_folders():
    assert config.CVR_DIR == config.PROCESSED_DIR / "cast-vote-records"
    assert config.CLUSTERS_DIR == config.PROCESSED_DIR / "clusters"
    assert config.SUMMARY_CSV.parent == config.CVR_DIR
    assert config.PROVENANCE_CSV.parent == config.CVR_DIR


def test_processed_files_use_current_keys(repo_root):
    keys = {s.election_key for s in SOURCES}
    cvr = repo_root / "data" / "processed" / "cast-vote-records"
    for p in cvr.glob("*-county-wide-by-voter.csv"):
        assert p.name.removesuffix("-county-wide-by-voter.csv") in keys, p.name
    clusters = repo_root / "data" / "processed" / "clusters"
    for p in clusters.glob("*-ballots-with-clusters.csv"):
        assert p.name.removesuffix("-ballots-with-clusters.csv") in keys, p.name
    assert not list((repo_root / "data" / "processed").glob("*.csv")), \
        "processed CSVs belong in a dataset subfolder"


def test_processed_outputs_are_lfs_tracked(repo_root):
    paths = [
        "data/processed/cast-vote-records/2024-general-county-wide-by-voter.csv",
        "data/processed/cast-vote-records/_summary.csv",
        "data/processed/clusters/provenance.csv",
        "data/processed/clusters/city-of-boulder-cluster-smallmultiples.png",
    ]
    out = subprocess.run(["git", "check-attr", "filter", "--", *paths],
                         cwd=repo_root, capture_output=True, text=True, check=True).stdout
    assert out.count("filter: lfs") == len(paths), out
