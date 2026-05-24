"""Idempotent downloader + SHA-256 manifest builder.

Downloads any CVR with a public URL that is missing from ``data/original/``
and updates ``data/original/manifest.json`` with the SHA-256 of every file
in ``data/original/``.

The manifest is the integrity contract: any file in ``data/original/`` that
differs from its manifest hash indicates either a corrupted download or an
upstream change. ``fetch --force`` redownloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

from .config import ORIGINAL_DIR, ORIGINAL_MANIFEST, ensure_dirs
from .sources import SOURCES


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict[str, dict]:
    """Load ``data/original/manifest.json``; return ``{}`` if absent."""
    if not ORIGINAL_MANIFEST.exists():
        return {}
    return json.loads(ORIGINAL_MANIFEST.read_text())


def write_manifest(manifest: dict[str, dict]) -> None:
    """Write ``manifest`` to ``data/original/manifest.json`` (sorted keys)."""
    ORIGINAL_MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def rebuild_manifest() -> dict[str, dict]:
    """Compute fresh SHA-256 + size + mtime for every file in ``data/original/``."""
    manifest: dict[str, dict] = {}
    for p in sorted(ORIGINAL_DIR.glob("**/*")):
        if not p.is_file() or p.name == "manifest.json" or p.name.startswith("."):
            continue
        rel = str(p.relative_to(ORIGINAL_DIR))
        manifest[rel] = {
            "sha256":    sha256_file(p),
            "size":      p.stat().st_size,
            "mtime_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime)
            ),
        }
    return manifest


def download_one(src, *, force: bool = False) -> bool:
    """Download ``src.public_url`` to ``data/original/<src.filename>`` if missing.

    Returns ``True`` if a new download happened, ``False`` if skipped.
    """
    dest = ORIGINAL_DIR / src.filename
    if src.public_url is None:
        if not dest.exists():
            print(
                f"  [warn] {src.election_key}: no public URL and file missing "
                f"at {dest}. Place the CORA disclosure here manually.",
                file=sys.stderr,
            )
            return False
        return False

    if dest.exists() and not force:
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {src.election_key} from {src.public_url}", flush=True)
    r = requests.get(src.public_url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(
        f"  saved {dest} ({dest.stat().st_size/1e6:.1f} MB)",
        flush=True,
    )
    return True


def fetch(*, force: bool = False, verbose: bool = True) -> dict[str, dict]:
    """Run :func:`download_one` over every :data:`SOURCES` entry, then write
    a fresh manifest."""
    ensure_dirs()
    n_new = 0
    if verbose:
        print("Boulder County redacted Cast Vote Records:")
    for src in SOURCES:
        if download_one(src, force=force):
            n_new += 1
    manifest = rebuild_manifest()
    write_manifest(manifest)
    if verbose:
        print(
            f"\n{n_new} new file(s) downloaded; manifest has "
            f"{len(manifest)} entries → {ORIGINAL_MANIFEST}"
        )
    return manifest


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.fetch", description=__doc__)
    p.add_argument("--force", action="store_true",
                   help="re-download files even when present")
    p.add_argument("--quiet", "-q", action="store_true")
    a = p.parse_args(argv)
    fetch(force=a.force, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
