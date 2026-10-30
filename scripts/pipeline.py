"""End-to-end driver. ``python -m scripts.pipeline`` runs the full chain;
subcommands expose individual phases.

::

    python -m scripts.pipeline                # fetch → clean → audit
    python -m scripts.pipeline fetch          # download + verify manifest
    python -m scripts.pipeline clean          # split redaction + merge → CSV
    python -m scripts.pipeline audit          # summary + variables report
    python -m scripts.pipeline reconcile      # independent count check
    python -m scripts.pipeline publish build  # build Datasette SQLite (opt-in)
    python -m scripts.pipeline list           # list known elections

Shared options (``-q``, ``-e``/``--election`` with lowercase keys such as
``2024-general``, ``--year``, ``--force``, ``--fail-on-empty``,
``--update-manifest``) work before or after the subcommand
(``pipeline -q clean`` and ``pipeline clean -q`` are the same). An option a
subcommand does not use is an error rather than silently ignored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import write_audit
from .clean import clean
from .fetch import fetch
from .reconcile import reconcile
from .sources import SOURCES

# Which shared options each command honours (None = the full run).
_USES = {
    None: {"quiet", "election", "year", "fail_on_empty", "force", "update_manifest"},
    "fetch": {"quiet", "force", "update_manifest"},
    "clean": {"quiet", "election", "year", "fail_on_empty"},
    "audit": {"quiet"},
    "reconcile": {"quiet"},
    "publish": {"quiet"},
    "list": set(),
}
_DEFAULTS = {
    "quiet": False,
    "election": [],
    "year": [],
    "fail_on_empty": False,
    "force": False,
    "update_manifest": False,
}
_FLAGS = {
    "quiet": "-q/--quiet",
    "election": "-e/--election",
    "year": "--year",
    "fail_on_empty": "--fail-on-empty",
    "force": "--force",
    "update_manifest": "--update-manifest",
}


def _common_parser() -> argparse.ArgumentParser:
    """Shared options. ``default=SUPPRESS`` so a subcommand that does not see
    the flag leaves the value parsed at the top level untouched."""
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument("--quiet", "-q", action="store_true", default=argparse.SUPPRESS)
    c.add_argument(
        "--election",
        "-e",
        action="append",
        default=argparse.SUPPRESS,
        help="process only this election_key, e.g. 2024-general (repeatable)",
    )
    c.add_argument(
        "--year",
        action="append",
        type=int,
        default=argparse.SUPPRESS,
        help="process every election in this year (repeatable; as in Election-Results)",
    )
    c.add_argument(
        "--fail-on-empty",
        action="store_true",
        default=argparse.SUPPRESS,
        help="exit non-zero if every output is empty",
    )
    c.add_argument(
        "--force",
        action="store_true",
        default=argparse.SUPPRESS,
        help="re-download originals even when present",
    )
    c.add_argument(
        "--update-manifest",
        action="store_true",
        default=argparse.SUPPRESS,
        help="accept hash changes in data/original/ instead of failing",
    )
    return c


def _list(_: argparse.Namespace) -> int:
    for src in SOURCES:
        posted = "public" if src.public_url else "CORA"
        print(
            f"  {src.election_key:24s} {src.year} {src.election_type:12s} [{posted}] {src.filename}"
        )
    return 0


def _full_run(a: argparse.Namespace) -> int:
    fetch(force=a.force, update_manifest=a.update_manifest, verbose=not a.quiet)
    clean(elections=a.election, years=a.year, fail_on_empty=a.fail_on_empty, verbose=not a.quiet)
    write_audit(verbose=not a.quiet)
    return 0


def _delegate_publish(a: argparse.Namespace) -> int:
    from .publish import _main as publish_main

    return publish_main([a.publish_cmd] + (["--quiet"] if a.quiet else []))


def _build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    p = argparse.ArgumentParser(
        prog="scripts.pipeline",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    p.set_defaults(func=_full_run, cmd=None)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser(
        "fetch", parents=[common], help="download originals + verify manifest"
    ).set_defaults(
        func=lambda a: (
            fetch(force=a.force, update_manifest=a.update_manifest, verbose=not a.quiet),
            0,
        )[1]
    )
    sub.add_parser("clean", parents=[common], help="split redaction + merge → CSVs").set_defaults(
        func=lambda a: (
            clean(
                elections=a.election,
                years=a.year,
                fail_on_empty=a.fail_on_empty,
                verbose=not a.quiet,
            ),
            0,
        )[1]
    )
    sub.add_parser("audit", parents=[common], help="summary stats + variables report").set_defaults(
        func=lambda a: (write_audit(verbose=not a.quiet), 0)[1]
    )
    reconcile_p = sub.add_parser("reconcile", parents=[common], help="independent count check")
    reconcile_p.add_argument(
        "--sov",
        type=Path,
        default=None,
        metavar="DIR",
        help="Election-Results statements-of-votes/ folder for an informational cross-check",
    )
    reconcile_p.set_defaults(func=lambda a: (reconcile(verbose=not a.quiet, sov_dir=a.sov), 0)[1])
    publish_p = sub.add_parser("publish", parents=[common], help="build / serve / deploy Datasette")
    publish_p.add_argument("publish_cmd", choices=["build", "serve", "deploy"])
    publish_p.set_defaults(func=_delegate_publish)
    sub.add_parser("list", parents=[common], help="list known elections").set_defaults(func=_list)
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse ``argv``; fill unset shared options; reject ones the command ignores."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    given = {k for k in _DEFAULTS if k in vars(args)}
    unused = given - _USES[args.cmd]
    if unused:
        flags = ", ".join(sorted(_FLAGS[k] for k in unused))
        parser.error(f"{flags} does not apply to `{args.cmd}`")
    for k, v in _DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, list(v) if isinstance(v, list) else v)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
