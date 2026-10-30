"""CSV originals (2017 Coordinated, 2018 Primary): same export, different file type."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pandas.testing as pdt

from scripts.cleaner import clean_countywide, split_redacted
from scripts.loader import AGGREGATE_CVR_LIST_RE, load_raw_cvr
from scripts.reconcile import independent_counts


def _xlsx_to_csv(xlsx: Path, out: Path) -> Path:
    raw = pd.read_excel(xlsx, header=None, dtype=str, engine="openpyxl")
    raw.to_csv(out, header=False, index=False)
    return out


def test_csv_and_xlsx_of_the_same_export_clean_identically(minimal_cvr_path, tmp_path):
    csv_path = _xlsx_to_csv(minimal_cvr_path, tmp_path / "mini.csv")
    a = clean_countywide(load_raw_cvr(minimal_cvr_path), election_key="test")
    b = clean_countywide(load_raw_cvr(csv_path), election_key="test")
    assert (b.n_raw_rows, b.n_aggregate_rows_dropped, b.n_redacted_kept, b.n_voters) == (
        a.n_raw_rows,
        a.n_aggregate_rows_dropped,
        a.n_redacted_kept,
        a.n_voters,
    )
    contests = [c for c in a.cleaned.columns if not c.startswith("_ID/")]
    pdt.assert_frame_equal(
        b.cleaned[contests].reset_index(drop=True), a.cleaned[contests].reset_index(drop=True)
    )


def _write_rows(path: Path, rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


def _list_label_cvr(tmp_path: Path) -> Path:
    head = [
        ["2017 Synthetic Coordinated Election", "5.2.16.1", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "Question 1 (Vote For=1)", "Question 1 (Vote For=1)"],
        ["", "", "", "", "", "", "Yes", "No"],
        ["CvrNumber", "TabulatorNum", "BatchId", "RecordId", "ImprintedId", "BallotType", "", ""],
    ]
    body = [
        ["1", "1", "1", "1", "1-1-1", "DS-03", "1", "0"],
        ["2", "1", "1", "2", "1-1-2", "DS-03", "0", "1"],
        # Aggregate whose cells are all 0/1: only the CvrNumber list identifies it.
        ["81883,81886", "", "", "", "", "DS-09", "1", "0"],
        # Aggregate with a space after each comma (2018 style) and a cell > 1.
        ["69676, 69680, 69758", "", "", "", "", "DS-09", "2", "1"],
    ]
    return _write_rows(tmp_path / "list.csv", head + body)


def test_cvr_number_list_marks_an_aggregate(tmp_path):
    raw = load_raw_cvr(_list_label_cvr(tmp_path))
    split = split_redacted(raw)
    assert split.n_aggregate_dropped == 2
    assert len(split.redacted) == 0
    assert split.unknown_labels == ()
    res = clean_countywide(raw, election_key="test")
    assert res.n_voters == 2


def test_cvr_list_pattern_requires_two_numbers():
    assert AGGREGATE_CVR_LIST_RE.fullmatch("81883,81886")
    assert AGGREGATE_CVR_LIST_RE.fullmatch("69676, 69680, 69758")
    assert not AGGREGATE_CVR_LIST_RE.fullmatch("81883")
    assert not AGGREGATE_CVR_LIST_RE.fullmatch("Redacted")


def test_reconcile_reads_csv_independently(tmp_path):
    counts = independent_counts(_list_label_cvr(tmp_path))
    assert counts["n_raw"] == 4
    assert counts["n_aggregate"] == 2
    assert counts["n_kept"] == 2
