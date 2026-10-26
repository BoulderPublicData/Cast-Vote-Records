"""Idempotent downloader + SHA-256 manifest verifier.

Downloads any CVR with a public URL that is missing from ``data/original/``
and checks every file in ``data/original/`` against
``data/original/manifest.json``.

The manifest is the integrity contract: a file whose SHA-256 differs from its
manifest entry is either a corrupted download, an upstream change, or (on a
fresh clone) a Git LFS pointer that was never pulled. ``fetch`` **fails** on a
mismatch instead of silently replacing the entry; pass ``--update-manifest``
to accept a deliberate change (e.g. after ``--force`` re-downloads a file the
County republished).

Manifest fields per file:

``sha256`` / ``size``
    Content hash and byte count.
``retrieved_at``
    UTC time the file was downloaded from its ``public_url`` (by ``fetch``, or
    by hand and checked byte-identical). Blank for CORA files.
``source_last_modified``
    The County server's ``Last-Modified`` header for ``public_url`` at
    retrieval, i.e. when the County posted this version.
``obtained_at``
    For CORA disclosures: the hand-entered date the County released the file
    (from :data:`scripts.sources.SOURCES`). Blank when unknown.
``first_committed_at``
    When the file first entered this repository: an upper bound on when it
    was obtained, for files whose retrieval time was never recorded.
``xlsx_created`` / ``xlsx_modified``
    The workbook's own ``docProps/core.xml`` timestamps, i.e. when the County
    produced the export.

File mtimes are never used: they are checkout times, not retrieval times.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import zipfile
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from . import config
from .config import ensure_dirs
from .sources import ARCHIVED_ORIGINALS, SOURCES

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


class LfsPointerError(RuntimeError):
    """A file in ``data/original/`` is a Git LFS pointer, not the data."""


def is_lfs_pointer(path: Path) -> bool:
    """True if ``path`` is a small Git LFS pointer file rather than content."""
    try:
        if path.stat().st_size > 1024:
            return False
        with path.open("rb") as f:
            return f.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def check_lfs_pointers(paths) -> None:
    """Raise :class:`LfsPointerError` naming every pointer file in ``paths``."""
    pointers = [p for p in paths if Path(p).exists() and is_lfs_pointer(Path(p))]
    if pointers:
        names = ", ".join(Path(p).name for p in pointers)
        raise LfsPointerError(
            f"{len(pointers)} file(s) in data/original/ are Git LFS pointers, not "
            f"the spreadsheets ({names}). Run `git lfs pull` first."
        )


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def xlsx_timestamps(path: Path) -> dict[str, str]:
    """Return the workbook's ``created`` / ``modified`` core properties."""
    try:
        with zipfile.ZipFile(path) as z:
            core = z.read("docProps/core.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return {}
    found = dict(re.findall(r"<dcterms:(created|modified)[^>]*>([^<]+)<", core))
    return {f"xlsx_{k}": v for k, v in found.items()}


def load_manifest() -> dict[str, dict]:
    """Load ``data/original/manifest.json``; return ``{}`` if absent."""
    if not config.ORIGINAL_MANIFEST.exists():
        return {}
    return json.loads(config.ORIGINAL_MANIFEST.read_text())


def write_manifest(manifest: dict[str, dict]) -> None:
    """Write ``manifest`` to ``data/original/manifest.json`` (sorted keys)."""
    config.ORIGINAL_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _original_files() -> list[Path]:
    return [
        p
        for p in sorted(config.ORIGINAL_DIR.glob("**/*"))
        if p.is_file() and p.name != "manifest.json" and not p.name.startswith(".")
    ]


def verify_manifest(
    manifest: dict[str, dict],
    *,
    downloaded: dict[str, dict[str, str]] | None = None,
    update: bool = False,
) -> tuple[dict[str, dict], list[str]]:
    """Check every file in ``data/original/`` against ``manifest``.

    Parameters
    ----------
    manifest
        The current manifest (not modified).
    downloaded
        ``{relative name: {"retrieved_at": ..., "source_last_modified": ...}}``
        for files this run downloaded.
    update
        Accept hash changes (record the new hash) instead of reporting them.

    Returns
    -------
    (new_manifest, problems)
        ``problems`` lists every hash mismatch that was *not* accepted. Entries
        for files missing from disk are kept unchanged.
    """
    downloaded = downloaded or {}
    obtained = {s.filename: s.obtained_at for s in (*SOURCES, *ARCHIVED_ORIGINALS)}
    files = _original_files()
    check_lfs_pointers(files)

    new = {k: dict(v) for k, v in manifest.items()}
    problems: list[str] = []
    for p in files:
        rel = str(p.relative_to(config.ORIGINAL_DIR))
        digest = sha256_file(p)
        entry = new.get(rel)
        if entry is not None and entry.get("sha256") != digest and not update:
            problems.append(
                f"{rel}: sha256 {digest[:12]} on disk != manifest {str(entry.get('sha256'))[:12]}"
            )
            continue
        entry = dict(entry or {})
        entry.pop("mtime_iso", None)  # checkout time, never a retrieval time
        entry.update({"sha256": digest, "size": p.stat().st_size})
        entry.update(xlsx_timestamps(p))
        if rel in downloaded:
            entry.update(downloaded[rel])
        entry.setdefault("retrieved_at", "")
        entry.setdefault("source_last_modified", "")
        if obtained.get(rel):
            entry["obtained_at"] = obtained[rel]
        entry.setdefault("obtained_at", "")
        entry.setdefault("first_committed_at", "")
        new[rel] = entry
    return new, problems


def download_one(src, *, force: bool = False) -> dict[str, str] | None:
    """Download ``src.public_url`` to ``data/original/<src.filename>`` if missing.

    Returns the manifest fields to record (``retrieved_at``,
    ``source_last_modified``) if a new download happened, ``None`` if skipped.
    """
    dest = config.ORIGINAL_DIR / src.filename
    if src.public_url is None:
        if not dest.exists():
            print(
                f"  [warn] {src.election_key}: no public URL and file missing "
                f"at {dest}. Place the CORA disclosure here manually.",
                file=sys.stderr,
            )
        return None

    if dest.exists() and not force:
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {src.election_key} from {src.public_url}", flush=True)
    r = requests.get(src.public_url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"  saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return {
        "retrieved_at": _now(),
        "source_last_modified": _http_date_to_iso(r.headers.get("Last-Modified", "")),
    }


def _http_date_to_iso(value: str) -> str:
    """``Tue, 07 Jan 2025 02:19:25 GMT`` → ``2025-01-07T02:19:25Z`` ("" if absent)."""
    if not value:
        return ""
    return parsedate_to_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(
    *,
    force: bool = False,
    update_manifest: bool = False,
    verbose: bool = True,
) -> dict[str, dict]:
    """Download missing public CVRs, then verify every file against the
    manifest and write it back.

    Raises ``SystemExit`` with "run `git lfs pull`" if any original is an LFS
    pointer, and ``SystemExit(1)`` on a hash mismatch (unless
    ``update_manifest``); the manifest is not rewritten in either case.
    """
    ensure_dirs()
    try:
        check_lfs_pointers(_original_files())
    except LfsPointerError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    if verbose:
        print("Boulder County redacted Cast Vote Records:")
    downloaded: dict[str, dict[str, str]] = {}
    for src in SOURCES:
        fields = download_one(src, force=force)
        if fields:
            downloaded[src.filename] = fields

    manifest, problems = verify_manifest(
        load_manifest(),
        downloaded=downloaded,
        update=update_manifest,
    )
    if problems:
        print("FAIL: data/original/ does not match manifest.json:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "Re-run `git lfs pull`, or pass --update-manifest to accept a "
            "deliberate upstream change.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    write_manifest(manifest)
    if verbose:
        print(
            f"\n{len(downloaded)} new file(s) downloaded; manifest verified, "
            f"{len(manifest)} entries → {config.ORIGINAL_MANIFEST}"
        )
    return manifest


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scripts.fetch",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--force", action="store_true", help="re-download files even when present")
    p.add_argument(
        "--update-manifest", action="store_true", help="accept hash changes instead of failing"
    )
    p.add_argument("--quiet", "-q", action="store_true")
    a = p.parse_args(argv)
    fetch(force=a.force, update_manifest=a.update_manifest, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
