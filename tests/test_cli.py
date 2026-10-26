"""CLI option handling (#22): shared options before or after the subcommand."""

from __future__ import annotations

import pytest

from scripts.pipeline import parse_args


def test_quiet_before_subcommand_is_kept():
    assert parse_args(["-q", "clean"]).quiet is True


def test_quiet_after_subcommand():
    assert parse_args(["clean", "-q"]).quiet is True


def test_defaults_are_filled():
    a = parse_args(["clean"])
    assert a.quiet is False and a.election == [] and a.fail_on_empty is False


def test_election_either_side():
    assert parse_args(["-e", "2024-general", "clean"]).election == ["2024-general"]
    assert parse_args(["clean", "-e", "2024-general", "-e", "2025-coordinated"]).election == [
        "2024-general", "2025-coordinated",
    ]


def test_full_run_takes_shared_options():
    a = parse_args(["-q", "--force", "-e", "2024-general"])
    assert a.cmd is None and a.quiet and a.force and a.election == ["2024-general"]


@pytest.mark.parametrize("argv", [
    ["-e", "2023-coordinated", "audit"],
    ["audit", "-e", "2023-coordinated"],
    ["clean", "--force"],
    ["reconcile", "--fail-on-empty"],
])
def test_option_a_command_ignores_is_an_error(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2
    assert "does not apply" in capsys.readouterr().err


def test_publish_accepts_quiet_after_subcommand():
    a = parse_args(["publish", "build", "-q"])
    assert a.publish_cmd == "build" and a.quiet is True


def test_reconcile_sov_flag(tmp_path):
    a = parse_args(["reconcile", "--sov", str(tmp_path)])
    assert a.sov == tmp_path


def test_year_filter_either_side():
    assert parse_args(["--year", "2024", "clean"]).year == [2024]
    assert parse_args(["clean", "--year", "2023", "--year", "2025"]).year == [2023, 2025]
    assert parse_args(["clean"]).year == []
