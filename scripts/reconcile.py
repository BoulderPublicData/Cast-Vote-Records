"""Independent re-derivation of headline counts and per-contest mark totals.

For every election, this script re-reads the original xlsx with a different
parser (``python-calamine``, not the loader's ``openpyxl``), re-applies the
redaction rule from scratch, and checks the published outputs against it:

1. **Raw rows.** Rows after the 4-row header == ``_summary.csv``
   ``n_raw_rows``; aggregate rows == ``n_aggregate_rows_dropped``.
2. **Processed CSV.** Re-count the rows of
   ``data/processed/cast-vote-records/<election>-county-wide-by-voter.csv`` (== ``n_voters``),
   assert ``_ID/voter_id`` is unique, ``Σ _ID/n_sheets`` == the sheets left
   after dropping aggregates, and the ``_ID/redacted`` count ==
   ``n_redacted_kept``.
3. **Mark totals.** For every contest-choice column, the sum of marks in the
   processed CSV == the sum over the raw rows that are not aggregates. A
   merge that drops, duplicates or overwrites a sheet shows up here.

Any failure sets a non-``ok`` status and the script exits non-zero. Results
go to ``data/audit/reconcile.json`` and ``data/audit/reconcile.md``
(plus ``reconcile-sov.csv`` with every compared contest-choice).

4. **Aggregate side table.** ``<election>-aggregate-rows.csv`` has one row
   per raw aggregate, its per-column totals equal the raw aggregate rows'
   marks, and its ballot counts equal the counts re-read from the labels.

**Statement of Votes check** (``--sov DIR``): point it at the sibling
`BoulderPublicData/Election-Results` repo's
``data/processed/statements-of-votes/`` folder. For every contest-choice
present in both (matched by normalized name; see :func:`_norm`), the CVR's
kept marks plus its aggregate marks must equal the official votes. Any
difference fails the run, unless ``data/lookups/sov-exceptions.csv`` lists
that election, contest and choice with the same difference, a reason and
evidence. An exception whose difference has gone to zero (upstream fixed)
or that no longer matches anything is reported as stale, without failing,
so it can be removed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import ftfy
import numpy as np
import pandas as pd

from . import config
from .config import ensure_dirs
from .fetch import LfsPointerError, check_lfs_pointers
from .sources import SOURCES

_ID_LABELS = {
    "CvrNumber",
    "TabulatorNum",
    "BatchId",
    "RecordId",
    "ImprintedId",
    "CountingGroup",
    "PrecinctPortion",
    "BallotType",
}
_AGGREGATE_RE = re.compile(r"consolidat|aggregat", re.IGNORECASE)
_CVR_LIST_RE = re.compile(r"\s*\d+(?:\s*,\s*\d+)+\s*")  # 2017/2018: summed CVR numbers


def _ballots_in_label(label: object) -> int | None:
    """Ballots an aggregate's ``CvrNumber`` label says it sums: the entries of
    a CVR-number list, or ``N`` in "... N Ballots"; else ``None``."""
    if not isinstance(label, str):
        return None
    if _CVR_LIST_RE.fullmatch(label):
        return label.count(",") + 1
    m = re.search(r"(\d+)\s+Ballot", label, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _fix(text: object) -> object:
    """Repair mojibake in a header cell, as the loader does (see #22)."""
    return ftfy.fix_encoding(text).replace("\xa0", " ") if isinstance(text, str) else text


def _read_original(path: Path) -> pd.DataFrame:
    """Read the original independently of the loader: xlsx with calamine (the
    loader uses openpyxl), csv with the standard-library reader (the loader
    uses pandas)."""
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        width = max(len(r) for r in rows)
        return pd.DataFrame(
            [[(v if v != "" else None) for v in r] + [None] * (width - len(r)) for r in rows]
        )
    try:
        return pd.read_excel(path, header=None, engine="calamine")
    except ImportError:  # pragma: no cover - calamine is a core dependency
        return pd.read_excel(path, header=None)


def independent_counts(path: Path) -> dict:
    """Re-derive row counts and per-column mark totals from the original.

    Returns ``{"n_raw", "n_aggregate", "n_kept", "marks", "aggregate_marks"}``
    where ``marks`` / ``aggregate_marks`` map ``"contest::choice"`` to the
    mark total over kept rows / aggregate rows.
    """
    raw = _read_original(path)
    labels = raw.iloc[3]
    body = raw.iloc[4:].reset_index(drop=True)
    id_pos = {
        str(labels.iloc[i]): i
        for i in range(raw.shape[1])
        if isinstance(labels.iloc[i], str) and labels.iloc[i] in _ID_LABELS
    }
    contest_pos = [i for i in range(raw.shape[1]) if i not in id_pos.values()]
    names = [f"{_fix(raw.iloc[1, i])}::{_fix(raw.iloc[2, i])}" for i in contest_pos]

    cvr = body.iloc[:, id_pos["CvrNumber"]]
    tab = body.iloc[:, id_pos["TabulatorNum"]]
    redacted = (
        pd.to_numeric(cvr, errors="coerce").isna() | pd.to_numeric(tab, errors="coerce").isna()
    )
    values = body.iloc[:, contest_pos].apply(pd.to_numeric, errors="coerce")
    by_label = cvr.astype("string").str.contains(_AGGREGATE_RE, na=False) | cvr.astype(
        "string"
    ).str.fullmatch(_CVR_LIST_RE, na=False)
    by_value = (values > 1).any(axis=1)
    aggregate = redacted & (by_label | by_value)

    kept_sums = values[~aggregate].sum().to_numpy()
    agg_sums = values[aggregate].sum().to_numpy()
    counts = [_ballots_in_label(v) for v in cvr[aggregate]]
    return {
        "n_raw": len(body),
        "n_aggregate": int(aggregate.sum()),
        "n_aggregate_with_count": sum(c is not None for c in counts),
        "n_aggregate_ballots": sum(c for c in counts if c is not None),
        "n_kept": int((~aggregate).sum()),
        "duplicate_names": sorted({n for n in names if names.count(n) > 1}),
        "marks": dict(zip(names, kept_sums.astype(float), strict=True)),
        "aggregate_marks": dict(zip(names, agg_sums.astype(float), strict=True)),
    }


def _processed_path(election_key: str) -> Path:
    return config.CVR_DIR / f"{election_key}-county-wide-by-voter.csv"


def check_processed(path: Path, indep: dict, summary_row: dict | None) -> dict:
    """Compare a processed CSV against the independent counts and summary."""
    problems: list[str] = []
    out: dict = {}
    if not path.exists():
        if indep["n_kept"] > 0:
            problems.append("processed CSV missing")
        return {"problems": problems, "csv_rows": 0}

    df = pd.read_csv(path, dtype={"_ID/BallotType": str}, low_memory=False)
    out["csv_rows"] = len(df)
    if summary_row is not None and len(df) != int(summary_row["n_voters"]):
        problems.append(f"csv rows {len(df)} != summary n_voters {summary_row['n_voters']}")
    if not df["_ID/voter_id"].is_unique:
        n_dup = int(df["_ID/voter_id"].duplicated().sum())
        problems.append(f"{n_dup} duplicate voter_id")
    n_sheets = int(df["_ID/n_sheets"].sum())
    out["sum_n_sheets"] = n_sheets
    if n_sheets != indep["n_kept"]:
        problems.append(f"sum(n_sheets) {n_sheets} != non-aggregate raw rows {indep['n_kept']}")
    n_red = int(df["_ID/redacted"].astype(bool).sum()) if "_ID/redacted" in df else 0
    out["csv_redacted"] = n_red
    if summary_row is not None and n_red != int(summary_row.get("n_redacted_kept", 0)):
        problems.append(f"redacted rows {n_red} != summary n_redacted_kept")

    # Per-column mark totals
    contest_cols = [c for c in df.columns if not c.startswith("_ID/")]
    csv_marks = df[contest_cols].sum()
    n_cols = 0
    mismatched: list[str] = []
    for name, raw_total in indep["marks"].items():
        if raw_total == 0 and name not in csv_marks.index:
            continue  # all-blank column dropped by the cleaner
        n_cols += 1
        got = float(csv_marks.get(name, np.nan))
        if not np.isclose(got, raw_total):
            mismatched.append(f"{name}: csv {got:g} vs raw {raw_total:g}")
    extra = sorted(set(contest_cols) - set(indep["marks"]))
    if extra:
        problems.append(f"{len(extra)} csv column(s) not in the original: {extra[:3]}")
    if mismatched:
        problems.append(f"{len(mismatched)} column mark total(s) differ: {mismatched[:3]}")
    out["n_columns_checked"] = n_cols
    out["total_marks_csv"] = float(csv_marks.sum())
    out["total_marks_raw"] = float(sum(indep["marks"].values()))
    out["problems"] = problems
    return out


def _aggregate_path(election_key: str) -> Path:
    return config.CVR_DIR / f"{election_key}-aggregate-rows.csv"


def check_aggregates(path: Path, indep: dict) -> dict:
    """Compare the aggregate side table against the raw aggregate rows."""
    problems: list[str] = []
    if indep["n_aggregate"] == 0:
        if path.exists():
            problems.append("aggregate table present but the original has no aggregates")
        return {"problems": problems, "agg_csv_rows": 0, "agg_marks_csv": 0.0}
    if not path.exists():
        return {"problems": ["aggregate table missing"], "agg_csv_rows": 0}

    df = pd.read_csv(path, dtype={"_ID/BallotType": str, "_ID/CvrNumber": str}, low_memory=False)
    out: dict = {"agg_csv_rows": len(df)}
    if len(df) != indep["n_aggregate"]:
        problems.append(f"aggregate table rows {len(df)} != raw aggregates {indep['n_aggregate']}")
    if not df["_ID/aggregate"].astype(bool).all():
        problems.append("aggregate table has rows not flagged _ID/aggregate")
    if not df["_ID/aggregate_id"].is_unique:
        problems.append("duplicate _ID/aggregate_id in aggregate table")
    n_ballots = df["_ID/n_ballots"]
    if int(n_ballots.notna().sum()) != indep["n_aggregate_with_count"] or int(
        n_ballots.sum()
    ) != int(indep["n_aggregate_ballots"]):
        problems.append(
            f"aggregate ballot counts {int(n_ballots.sum())} in {int(n_ballots.notna().sum())} "
            f"row(s) != labels {indep['n_aggregate_ballots']} in "
            f"{indep['n_aggregate_with_count']}"
        )
    out["agg_ballots_labelled"] = int(n_ballots.sum())

    contest_cols = [c for c in df.columns if not c.startswith("_ID/")]
    sums = df[contest_cols].sum()
    mismatched = []
    for name, raw_total in indep["aggregate_marks"].items():
        got = float(sums.get(name, 0.0))
        if not np.isclose(got, raw_total):
            mismatched.append(f"{name}: table {got:g} vs raw {raw_total:g}")
    extra = sorted(set(contest_cols) - set(indep["aggregate_marks"]))
    if extra:
        problems.append(f"{len(extra)} aggregate column(s) not in the original: {extra[:3]}")
    if mismatched:
        problems.append(f"{len(mismatched)} aggregate mark total(s) differ: {mismatched[:3]}")
    out["agg_marks_csv"] = float(sums.sum())
    out["problems"] = problems
    return out


# ---------------------------------------------------------------------------
# Statement of Votes check
# ---------------------------------------------------------------------------

EXCEPTION_COLUMNS = (
    "election_key",
    "contest",
    "choice",
    "expected_delta",
    "reason",
    "evidence",
    "remove_when",
)
"""Columns of ``data/lookups/sov-exceptions.csv``. ``expected_delta`` is
``cvr_marks + aggregate_marks - sov_votes`` for that contest-choice."""


def sov_exceptions_path() -> Path:
    return config.LOOKUPS_DIR / "sov-exceptions.csv"


def load_sov_exceptions(path: Path | None = None) -> pd.DataFrame:
    """Read and validate the reviewed list of known SoV differences.

    Raises ``ValueError`` on a malformed file: a missing column, an unknown
    election, a non-integer ``expected_delta`` (or 0, which needs no
    exception), a blank reason or evidence, or a duplicate row.
    """
    path = sov_exceptions_path() if path is None else path
    if not path.exists():
        return pd.DataFrame(columns=[*EXCEPTION_COLUMNS, "key"])
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in EXCEPTION_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {missing}")
    known = {s.election_key for s in SOURCES}
    bad: list[str] = []
    for i, r in df.iterrows():
        where = f"{path.name} row {i + 2}"
        if r["election_key"] not in known:
            bad.append(f"{where}: unknown election_key {r['election_key']!r}")
        if not re.fullmatch(r"-?\d+", r["expected_delta"].strip()) or int(r["expected_delta"]) == 0:
            bad.append(f"{where}: expected_delta must be a non-zero integer")
        for col in ("contest", "choice", "reason", "evidence"):
            if not r[col].strip():
                bad.append(f"{where}: {col} is blank")
    df["key"] = df["contest"].map(_norm) + "::" + df["choice"].map(_norm)
    dup = df.duplicated(["election_key", "key"])
    if dup.any():
        bad.append(f"{path.name}: duplicate row(s) {df.loc[dup, 'key'].tolist()[:3]}")
    if bad:
        raise ValueError("; ".join(bad))
    df["expected_delta"] = df["expected_delta"].astype(int)
    return df


_SUFFIX_RE = re.compile(r"\s*\((?:vote for=\d+|number of positions=[^)]*)\)\s*$", re.IGNORECASE)


def _norm(text: object) -> str:
    """Normalize a contest or choice name for matching CVR to SoV.

    Drops a trailing ``(Vote For=N)`` / ``(Number of positions=...)``, puts
    single spaces around hyphens, collapses whitespace and lowercases. Names
    that still differ (``Yes/For`` vs ``Yes``, renamed contests) do not match
    and are not compared.
    """
    s = _SUFFIX_RE.sub("", str(text))
    s = re.sub(r"\s*-\s*", " - ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _is_rank_column(choice: str) -> bool:
    return bool(re.search(r"\(\d+\)$", choice))


def sov_crosscheck(src, indep: dict, sov_dir: Path) -> pd.DataFrame | None:
    """Per contest-choice: CVR marks, aggregate marks, official SoV votes.

    Returns ``None`` when Election-Results has no Boulder County SoV for this
    election, otherwise one row per CVR contest-choice whose normalized
    ``contest::choice`` (:func:`_norm`) is in the SoV (possibly none). SoV
    votes are summed over precincts. RCV rank columns are skipped: they have
    no single SoV total. ``delta`` = ``cvr_marks + aggregate_marks -
    sov_votes``. ``attrs["cvr_choices"]`` is the number of comparable CVR
    columns, matched or not.
    """
    path = sov_dir / f"{src.election_key}-boulder-county.csv"
    if not path.exists():
        return None
    sov = pd.read_csv(path, low_memory=False)
    sov["key"] = sov["contest"].map(_norm) + "::" + sov["candidate_or_option"].map(_norm)
    official = sov.groupby("key")["votes"].sum()

    rows = []
    n_comparable = 0
    for name, marks in indep["marks"].items():
        contest, _, choice = name.partition("::")
        if _is_rank_column(choice):
            continue
        n_comparable += 1
        key = f"{_norm(contest)}::{_norm(choice)}"
        if key not in official.index:
            continue
        rows.append(
            {
                "election_key": src.election_key,
                "contest": contest,
                "choice": choice,
                "key": key,
                "cvr_marks": marks,
                "aggregate_marks": indep["aggregate_marks"][name],
                "sov_votes": float(official[key]),
            }
        )
    out = pd.DataFrame(
        rows,
        columns=[
            "election_key",
            "contest",
            "choice",
            "key",
            "cvr_marks",
            "aggregate_marks",
            "sov_votes",
        ],
    )
    out["delta"] = out["cvr_marks"] + out["aggregate_marks"] - out["sov_votes"]
    out.attrs["cvr_choices"] = n_comparable
    return out


def apply_sov_exceptions(
    election_key: str, frame: pd.DataFrame | None, exceptions: pd.DataFrame
) -> tuple[pd.DataFrame | None, list[str], list[dict]]:
    """Fail every nonzero ``delta`` not covered by a matching exception.

    Returns ``(frame with an "exception" column, problems, exception rows)``.
    Each exception row gets a ``status``:

    * ``applied``: the difference is exactly ``expected_delta``;
    * ``differs``: the contest-choice differs by something else (a failure);
    * ``stale``: the difference is now 0, so upstream agrees; remove the row;
    * ``unmatched``: nothing to compare (no SoV for the election, or the
      names no longer match); remove or fix the row.

    ``stale`` and ``unmatched`` do not fail the run; they are reported.
    """
    exc = exceptions[exceptions["election_key"] == election_key]
    problems: list[str] = []
    statuses: list[dict] = []
    if frame is None:
        for _, e in exc.iterrows():
            statuses.append({**_exc_fields(e), "status": "unmatched", "delta": None})
        return None, problems, statuses

    frame = frame.copy()
    frame["exception"] = ""
    by_key = {k: i for i, k in zip(frame.index, frame["key"], strict=True)}
    for _, e in exc.iterrows():
        idx = by_key.get(e["key"])
        if idx is None:
            statuses.append({**_exc_fields(e), "status": "unmatched", "delta": None})
            continue
        delta = int(frame.at[idx, "delta"])
        if delta == int(e["expected_delta"]):
            status = "applied"
            frame.at[idx, "exception"] = "excepted"
        elif delta == 0:
            status = "stale"
        else:
            status = "differs"
            frame.at[idx, "exception"] = "differs"
        statuses.append({**_exc_fields(e), "status": status, "delta": delta})

    bad = frame[(frame["delta"] != 0) & (frame["exception"] != "excepted")]
    for _, r in bad.iterrows():
        problems.append(
            f"SoV: {r['contest']} :: {r['choice']}: CVR {r['cvr_marks']:g} + aggregates "
            f"{r['aggregate_marks']:g} = {r['cvr_marks'] + r['aggregate_marks']:g} vs SoV "
            f"{r['sov_votes']:g} (delta {r['delta']:+g})"
        )
    if frame.empty:
        problems.append("SoV: Statement of Votes present but no contest-choice matched by name")
    return frame, problems, statuses


def _exc_fields(e: pd.Series) -> dict:
    return {
        "election_key": e["election_key"],
        "contest": e["contest"],
        "choice": e["choice"],
        "expected_delta": int(e["expected_delta"]),
        "reason": e["reason"],
        "remove_when": e["remove_when"],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _load_summary() -> pd.DataFrame:
    summary_csv = config.SUMMARY_CSV
    if not summary_csv.exists():
        raise SystemExit(f"{summary_csv} not found; run `python -m scripts.clean` first")
    return pd.read_csv(summary_csv, dtype={"multi_sheet_ballot_types": str}).set_index(
        "election_key"
    )


def _sov_status(frame: pd.DataFrame | None, problems: list[str]) -> str:
    if frame is None:
        return "no SoV"
    if problems:
        return "MISMATCH"
    n_exc = int((frame["exception"] == "excepted").sum())
    return f"ok ({n_exc} excepted)" if n_exc else "ok"


def reconcile(verbose: bool = True, *, sov_dir: Path | None = None) -> dict:
    """Run every check; raise ``SystemExit(1)`` on any regression."""
    ensure_dirs()
    try:
        check_lfs_pointers(config.ORIGINAL_DIR / s.filename for s in SOURCES)
    except LfsPointerError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    summary = _load_summary()
    exceptions = None
    if sov_dir is not None:
        try:
            exceptions = load_sov_exceptions()
        except ValueError as exc:
            raise SystemExit(f"FAIL: {exc}") from exc

    rows: list[dict] = []
    sov_frames: list[pd.DataFrame] = []
    exception_rows: list[dict] = []
    has_regression = False
    for src in SOURCES:
        orig = config.ORIGINAL_DIR / src.filename
        base = {"election_key": src.election_key}
        if not orig.exists():
            rows.append({**base, "status": "skip-no-original"})
            continue
        if verbose:
            print(f"  reconciling {src.election_key}...", flush=True)
        indep = independent_counts(orig)
        srow = (
            summary.loc[src.election_key].to_dict() if src.election_key in summary.index else None
        )

        problems: list[str] = []
        if srow is None:
            problems.append("election missing from _summary.csv")
        else:
            if int(srow["n_raw_rows"]) != indep["n_raw"]:
                problems.append(f"n_raw_rows {srow['n_raw_rows']} != raw {indep['n_raw']}")
            if int(srow.get("n_aggregate_rows_dropped", -1)) != indep["n_aggregate"]:
                problems.append(
                    f"n_aggregate_rows_dropped {srow.get('n_aggregate_rows_dropped')} "
                    f"!= raw {indep['n_aggregate']}"
                )
            if int(srow["n_sheets_after_redaction"]) != indep["n_kept"]:
                problems.append("n_sheets_after_redaction != raw non-aggregate rows")
            if int(srow.get("n_aggregate_ballots_labelled", -1)) != indep["n_aggregate_ballots"]:
                problems.append(
                    f"n_aggregate_ballots_labelled {srow.get('n_aggregate_ballots_labelled')} "
                    f"!= labels {indep['n_aggregate_ballots']}"
                )
            agg_total = float(sum(indep["aggregate_marks"].values()))
            if not np.isclose(float(srow.get("n_aggregate_marks", -1)), agg_total):
                problems.append(
                    f"n_aggregate_marks {srow.get('n_aggregate_marks')} != raw {agg_total:g}"
                )
        if indep["duplicate_names"]:
            problems.append(f"duplicate contest::choice headers: {indep['duplicate_names'][:3]}")
        checked = check_processed(_processed_path(src.election_key), indep, srow)
        problems += checked.pop("problems")
        agg_checked = check_aggregates(_aggregate_path(src.election_key), indep)
        problems += agg_checked.pop("problems")

        sov_status = None
        if sov_dir is not None:
            frame = sov_crosscheck(src, indep, sov_dir)
            frame, sov_problems, statuses = apply_sov_exceptions(
                src.election_key, frame, exceptions
            )
            problems += sov_problems
            exception_rows += statuses
            sov_status = _sov_status(frame, sov_problems)
            if frame is not None:
                sov_frames.append(frame)

        status = "ok" if not problems else "MISMATCH"
        has_regression |= bool(problems)
        rows.append(
            {
                **base,
                "status": status,
                "raw_rows": indep["n_raw"],
                "aggregate_rows": indep["n_aggregate"],
                "aggregate_ballots_labelled": indep["n_aggregate_ballots"],
                "sheets_kept": indep["n_kept"],
                "voters": None if srow is None else int(srow["n_voters"]),
                **checked,
                **agg_checked,
                "sov_status": sov_status,
                "problems": problems,
            }
        )
    # Exceptions for elections not in SOURCES are caught by load_sov_exceptions.

    report = {"rows": rows, "has_regression": has_regression}
    sov_summary = _summarize_sov(sov_frames) if sov_frames else None
    if sov_summary is not None and sov_summary.empty:
        sov_summary = None
    sov_csv = config.AUDIT_DIR / "reconcile-sov.csv"
    if sov_summary is not None:
        report["sov"] = sov_summary.to_dict(orient="records")
        pd.concat(sov_frames).drop(columns="key").to_csv(sov_csv, index=False)
    elif sov_csv.exists():
        sov_csv.unlink()  # don't leave a stale cross-check beside a new report
    if sov_dir is not None:
        report["sov_exceptions"] = exception_rows
    (config.AUDIT_DIR / "reconcile.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n"
    )
    (config.AUDIT_DIR / "reconcile.md").write_text(
        _render_md(rows, sov_summary, exception_rows if sov_dir is not None else None)
    )
    if verbose:
        print(f"  wrote {config.AUDIT_DIR / 'reconcile.md'}")

    leftover = [e for e in exception_rows if e["status"] in ("stale", "unmatched")]
    for e in leftover:
        print(
            f"  note: SoV exception {e['status']} ({e['election_key']}: {e['contest']} :: "
            f"{e['choice']}): it does not apply to this SoV; see its remove_when in "
            "data/lookups/sov-exceptions.csv",
            file=sys.stderr,
        )
    if has_regression:
        print("RECONCILE REGRESSION — see data/audit/reconcile.md", file=sys.stderr)
        for r in rows:
            for p in r.get("problems", []):
                print(f"  [{r['election_key']}] {p}", file=sys.stderr)
        raise SystemExit(1)
    return report


def _summarize_sov(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per election with at least one matched contest-choice."""
    rows = []
    for f in frames:
        if f.empty:
            continue
        rows.append(
            {
                "election_key": f["election_key"].iloc[0],
                "cvr_choices": f.attrs.get("cvr_choices"),
                "choices_matched": len(f),
                "cvr_marks": f["cvr_marks"].sum(),
                "aggregate_marks": f["aggregate_marks"].sum(),
                "sov_votes": f["sov_votes"].sum(),
                "n_differ": int((f["delta"] != 0).sum()),
                "n_excepted": int((f["exception"] == "excepted").sum()),
                "max_abs_delta": f["delta"].abs().max(),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["cvr_share_of_sov"] = out["cvr_marks"] / out["sov_votes"]
    out["with_aggregates_share"] = (out["cvr_marks"] + out["aggregate_marks"]) / out["sov_votes"]
    return out


def _fmt(v: object) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _render_md(rows: list[dict], sov: pd.DataFrame | None, exceptions: list[dict] | None) -> str:
    lines = [
        "# Reconcile report",
        "",
        (
            "Generated by `python -m scripts.reconcile`. Each original is re-read "
            "with an independent parser (calamine for xlsx, the standard-library csv "
            "reader for csv), the redaction rule is re-applied, "
            "and the published `_summary.csv`, per-voter CSVs and aggregate side tables "
            "are checked against it: raw and aggregate row counts, processed row count, "
            "unique `voter_id`, Σ `n_sheets` = sheets kept, redacted-row count, the mark "
            "total of every contest-choice column, and the aggregate table's rows, "
            "labelled ballot counts and per-column totals."
        ),
        "",
        (
            "| Election | status | raw rows | aggregate rows | sheets kept | Σ n_sheets "
            "| voters (CSV rows) | redacted kept | columns checked | marks (CSV) | marks (raw) "
            "| aggregate marks | SoV |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['election_key']} | {r['status']} | {_fmt(r.get('raw_rows'))} | "
            f"{_fmt(r.get('aggregate_rows'))} | {_fmt(r.get('sheets_kept'))} | "
            f"{_fmt(r.get('sum_n_sheets'))} | {_fmt(r.get('csv_rows'))} | "
            f"{_fmt(r.get('csv_redacted'))} | {_fmt(r.get('n_columns_checked'))} | "
            f"{_fmt(r.get('total_marks_csv'))} | {_fmt(r.get('total_marks_raw'))} | "
            f"{_fmt(r.get('agg_marks_csv'))} | {r.get('sov_status') or 'not run'} |"
        )
    problems = [(r["election_key"], p) for r in rows for p in r.get("problems", [])]
    if problems:
        lines += ["", "## Problems", ""]
        lines += [f"* **{k}**: {p}" for k, p in problems]
    if sov is not None:
        lines += [
            "",
            "## Statement of Votes check",
            "",
            (
                "Every CVR contest-choice whose name matches the Boulder County "
                "Statement of Votes from Election-Results "
                "(`data/processed/statements-of-votes/`). Names match after dropping "
                "`(Vote For=N)`, normalizing hyphens and whitespace, and lowercasing; "
                "choices that still differ by name (`Yes/For` vs `Yes`, write-ins) and "
                "RCV rank columns are not compared. `cvr_marks` counts the per-voter "
                "rows; `aggregate_marks` the aggregate side table. Kept plus aggregate "
                "marks must equal the SoV for every matched choice, except the "
                "documented differences in `data/lookups/sov-exceptions.csv`."
            ),
            "",
            (
                "| Election | CVR choices | matched | CVR marks | + aggregate marks | SoV votes "
                "| CVR / SoV | (CVR + agg) / SoV | differ | excepted | max abs Δ |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for _, s in sov.iterrows():
            lines.append(
                f"| {s['election_key']} | {_fmt(s['cvr_choices'])} | "
                f"{int(s['choices_matched'])} | "
                f"{int(s['cvr_marks']):,} | {int(s['aggregate_marks']):,} | "
                f"{int(s['sov_votes']):,} | {s['cvr_share_of_sov']:.4%} | "
                f"{s['with_aggregates_share']:.4%} | {int(s['n_differ'])} | "
                f"{int(s['n_excepted'])} | {int(s['max_abs_delta']):,} |"
            )
    if exceptions:
        lines += [
            "",
            "### Exceptions (`data/lookups/sov-exceptions.csv`)",
            "",
            (
                "`applied`: the documented difference is still there. `stale`: the "
                "difference is now 0 (upstream fixed); remove the row. `unmatched`: "
                "nothing to compare; remove or fix the row. `differs`: a different "
                "difference, which fails the run."
            ),
            "",
            "| Election | contest | choice | expected Δ | Δ now | status | remove when |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
        for e in exceptions:
            lines.append(
                f"| {e['election_key']} | {e['contest']} | {e['choice']} | "
                f"{e['expected_delta']:+d} | "
                f"{'' if e['delta'] is None else format(e['delta'], '+d')} | "
                f"{e['status']} | {e['remove_when']} |"
            )
    return "\n".join(lines) + "\n"


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scripts.reconcile",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument(
        "--sov",
        type=Path,
        default=None,
        metavar="DIR",
        help="Election-Results data/processed/statements-of-votes/ folder: fail "
        "on any contest-choice where CVR + aggregate marks differ from the SoV, "
        "except those in data/lookups/sov-exceptions.csv",
    )
    a = p.parse_args(argv)
    reconcile(verbose=not a.quiet, sov_dir=a.sov)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
