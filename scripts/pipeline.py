"""End-to-end driver. ``python -m scripts.pipeline`` runs the full chain;
subcommands expose individual phases.

::

    python -m scripts.pipeline                # fetch → clean → audit
    python -m scripts.pipeline fetch          # download + manifest
    python -m scripts.pipeline clean          # filter + tidy → CSV
    python -m scripts.pipeline audit          # summary + variables report
    python -m scripts.pipeline reconcile      # independent count check
    python -m scripts.pipeline publish build  # build Datasette SQLite (opt-in)
    python -m scripts.pipeline list           # list known elections
"""

from __future__ import annotations

import argparse
import sys

from .audit import write_audit
from .clean import clean
from .fetch import fetch
from .reconcile import reconcile
from .sources import SOURCES


def _list(_: argparse.Namespace) -> int:
    for src in SOURCES:
        posted = "public" if src.public_url else "CORA"
        print(
            f"  {src.election_key:24s} {src.year} "
            f"{src.election_type:12s} [{posted}] {src.filename}"
        )
    return 0


def _full_run(args: argparse.Namespace) -> int:
    fetch(force=args.force, verbose=not args.quiet)
    clean(elections=args.election, fail_on_empty=args.fail_on_empty,
          verbose=not args.quiet)
    write_audit(verbose=not args.quiet)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scripts.pipeline", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.set_defaults(func=_full_run)
    p.add_argument("--force", action="store_true",
                   help="re-download originals even when present")
    p.add_argument("--fail-on-empty", action="store_true",
                   help="exit non-zero if every output is empty")
    p.add_argument("--election", "-e", action="append", default=[],
                   help="process only this election_key (repeatable)")
    p.add_argument("--quiet", "-q", action="store_true")

    sub = p.add_subparsers(dest="cmd")

    fetch_p = sub.add_parser("fetch", help="download originals + write manifest")
    fetch_p.add_argument("--force", action="store_true")
    fetch_p.add_argument("--quiet", "-q", action="store_true")
    fetch_p.set_defaults(func=lambda a: (
        fetch(force=a.force, verbose=not a.quiet), 0)[1])

    clean_p = sub.add_parser("clean", help="filter + tidy → wide CSVs")
    clean_p.add_argument("--election", "-e", action="append", default=[])
    clean_p.add_argument("--fail-on-empty", action="store_true")
    clean_p.add_argument("--quiet", "-q", action="store_true")
    clean_p.set_defaults(func=lambda a: (clean(
        elections=a.election, fail_on_empty=a.fail_on_empty, verbose=not a.quiet
    ), 0)[1])

    audit_p = sub.add_parser("audit", help="summary stats + variables report")
    audit_p.add_argument("--quiet", "-q", action="store_true")
    audit_p.set_defaults(func=lambda a: (
        write_audit(verbose=not a.quiet), 0)[1])

    reconcile_p = sub.add_parser("reconcile", help="independent count check")
    reconcile_p.add_argument("--quiet", "-q", action="store_true")
    reconcile_p.set_defaults(func=lambda a: (
        reconcile(verbose=not a.quiet), 0)[1])

    publish_p = sub.add_parser("publish", help="build / serve / deploy Datasette")
    publish_p.add_argument("publish_cmd", choices=["build", "serve", "deploy"])
    publish_p.set_defaults(func=lambda a: _delegate_publish(a))

    sub.add_parser("list", help="list known elections").set_defaults(func=_list)

    return p


def _delegate_publish(args: argparse.Namespace) -> int:
    from .publish import _main as publish_main
    return publish_main([args.publish_cmd])


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
