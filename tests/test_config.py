"""``CVR_DATA_DIR`` moves every data path, so long runs can write outside the repo."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _paths(env_value: str | None) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k != "CVR_DATA_DIR"}
    if env_value is not None:
        env["CVR_DATA_DIR"] = env_value
    code = (
        "from scripts import config as c; "
        "print(c.DATA_DIR, c.ORIGINAL_DIR, c.CVR_DIR, c.CLUSTERS_DIR, c.AUDIT_DIR, sep='\\n')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def test_default_data_dir_is_in_repo():
    paths = _paths(None)
    assert paths[0] == str(ROOT / "data")


def test_override_moves_every_data_path(tmp_path):
    target = tmp_path / "data"
    paths = _paths(str(target))
    assert paths[0] == str(target.resolve())
    assert all(p.startswith(str(target.resolve())) for p in paths)
