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
go to ``data/audit/reconcile.json`` and ``data/audit/reconcile.md``.

Optional **Statement of Votes cross-check** (``--sov DIR``): point it at the
sibling `BoulderPublicData/Election-Results` repo's
``data/processed/statements-of-votes/`` folder. For each contest present in
both, it compares CVR marks (kept rows), marks inside the dropped aggregate
rows, and the official votes. This is informational only (never fails the
run): the SoV counts every ballot, while redaction, write-in adjudication and
the interpreted-snapshot encoding all move CVR totals slightly.
"""

from __future__ import annotations

import argparse
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
    "CvrNumber", "TabulatorNum", "BatchId", "RecordId", "ImprintedId",
    "CountingGroup", "PrecinctPortion", "BallotType",
}
_AGGREGATE_RE = re.compile(r"consolidat|aggregat", re.IGNORECASE)


def _fix(text: object) -> object:
    """Repair mojibake in a header cell, as the loader does (see #22)."""
    return ftfy.fix_encoding(text).replace("\xa0", " ") if isinstance(text, str) else text


def _read_original(path: Path) -> pd.DataFrame:
    """Read the xlsx with calamine (independent of the loader's openpyxl)."""
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
    id_pos = {str(labels.iloc[i]): i for i in range(raw.shape[1])
              if isinstance(labels.iloc[i], str) and labels.iloc[i] in _ID_LABELS}
    contest_pos = [i for i in range(raw.shape[1]) if i not in id_pos.values()]
    names = [f"{_fix(raw.iloc[1, i])}::{_fix(raw.iloc[2, i])}" for i in contest_pos]

    cvr = body.iloc[:, id_pos["CvrNumber"]]
    tab = body.iloc[:, id_pos["TabulatorNum"]]
    redacted = (pd.to_numeric(cvr, errors="coerce").isna()
                | pd.to_numeric(tab, errors="coerce").isna())
    values = body.iloc[:, contest_pos].apply(pd.to_numeric, errors="coerce")
    by_label = cvr.astype("string").str.contains(_AGGREGATE_RE, na=False)
    by_value = (values > 1).any(axis=1)
    aggregate = redacted & (by_label | by_value)

    kept_sums = values[~aggregate].sum().to_numpy()
    agg_sums = values[aggregate].sum().to_numpy()
    return {
        "n_raw": len(body),
        "n_aggregate": int(aggregate.sum()),
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


# ---------------------------------------------------------------------------
# Optional Statement of Votes cross-check
# ---------------------------------------------------------------------------

_SUFFIX_RE = re.compile(r"\s*\((?:vote for=\d+|number of positions=[^)]*)\)\s*$", re.IGNORECASE)


def _norm(text: object) -> str:
    s = _SUFFIX_RE.sub("", str(text))
    s = re.sub(r"\s*-\s*", " - ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def sov_crosscheck(src, indep: dict, sov_dir: Path) -> pd.DataFrame | None:
    """Per contest-choice: CVR marks, aggregate marks, official SoV votes."""
    path = sov_dir / f"{src.election_key}-boulder-county.csv"
    if not path.exists():
        return None
    sov = pd.read_csv(path, low_memory=False)
    sov["key"] = sov["contest"].map(_norm) + "::" + sov["candidate_or_option"].map(_norm)
    official = sov.groupby("key")["votes"].sum()

    rows = []
    for name, marks in indep["marks"].items():
        contest, _, choice = name.partition("::")
        if re.search(r"\(\d+\)$", choice):
            continue  # RCV rank columns have no single SoV total
        key = f"{_norm(contest)}::{_norm(choice)}"
        if key not in official.index:
            continue
        rows.append({
            "election_key": src.election_key,
            "contest": contest,
            "choice": choice,
            "cvr_marks": marks,
            "aggregate_marks": indep["aggregate_marks"][name],
            "sov_votes": float(official[key]),
        })
    if not rows:
        return None
    out = pd.DataFrame(rows)
    out["delta"] = out["cvr_marks"] + out["aggregate_marks"] - out["sov_votes"]
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _load_summary() -> pd.DataFrame:
    summary_csv = config.SUMMARY_CSV
    if not summary_csv.exists():
        raise SystemExit(
            f"{summary_csv} not found; run `python -m scripts.clean` first"
        )
    return pd.read_csv(summary_csv, dtype={"multi_sheet_ballot_types": str}).set_index("election_key")


def reconcile(verbose: bool = True, *, sov_dir: Path | None = None) -> dict:
    """Run every check; raise ``SystemExit(1)`` on any regression."""
    ensure_dirs()
    try:
        check_lfs_pointers(config.ORIGINAL_DIR / s.filename for s in SOURCES)
    except LfsPointerError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    summary = _load_summary()

    rows: list[dict] = []
    sov_frames: list[pd.DataFrame] = []
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
        srow = (summary.loc[src.election_key].to_dict()
                if src.election_key in summary.index else None)

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
        if indep["duplicate_names"]:
            problems.append(f"duplicate contest::choice headers: {indep['duplicate_names'][:3]}")
        checked = check_processed(_processed_path(src.election_key), indep, srow)
        problems += checked.pop("problems")

        status = "ok" if not problems else "MISMATCH"
        has_regression |= bool(problems)
        rows.append({
            **base,
            "status":            status,
            "raw_rows":          indep["n_raw"],
            "aggregate_rows":    indep["n_aggregate"],
            "sheets_kept":       indep["n_kept"],
            "voters":            None if srow is None else int(srow["n_voters"]),
            **checked,
            "problems":          problems,
        })
        if sov_dir is not None:
            frame = sov_crosscheck(src, indep, sov_dir)
            if frame is not None:
                sov_frames.append(frame)

    report = {"rows": rows, "has_regression": has_regression}
    sov_summary = _summarize_sov(sov_frames) if sov_frames else None
    sov_csv = config.AUDIT_DIR / "reconcile-sov.csv"
    if sov_summary is not None:
        report["sov"] = sov_summary.to_dict(orient="records")
        pd.concat(sov_frames).to_csv(sov_csv, index=False)
    elif sov_csv.exists():
        sov_csv.unlink()  # don't leave a stale cross-check beside a new report
    (config.AUDIT_DIR / "reconcile.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (config.AUDIT_DIR / "reconcile.md").write_text(_render_md(rows, sov_summary))
    if verbose:
        print(f"  wrote {config.AUDIT_DIR / 'reconcile.md'}")

    if has_regression:
        print("RECONCILE REGRESSION — see data/audit/reconcile.md", file=sys.stderr)
        for r in rows:
            for p in r.get("problems", []):
                print(f"  [{r['election_key']}] {p}", file=sys.stderr)
        raise SystemExit(1)
    return report


def _summarize_sov(frames: list[pd.DataFrame]) -> pd.DataFrame:
    df = pd.concat(frames)
    g = df.groupby("election_key", sort=False)
    out = pd.DataFrame({
        "choices_matched": g.size(),
        "cvr_marks": g["cvr_marks"].sum(),
        "aggregate_marks": g["aggregate_marks"].sum(),
        "sov_votes": g["sov_votes"].sum(),
    })
    out["cvr_share_of_sov"] = out["cvr_marks"] / out["sov_votes"]
    out["with_aggregates_share"] = (out["cvr_marks"] + out["aggregate_marks"]) / out["sov_votes"]
    out["max_abs_delta"] = g["delta"].apply(lambda s: s.abs().max())
    return out.reset_index()


def _fmt(v: object) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _render_md(rows: list[dict], sov: pd.DataFrame | None) -> str:
    lines = [
        "# Reconcile report",
        "",
        (
            "Generated by `python -m scripts.reconcile`. Each original xlsx is re-read "
            "with an independent parser (calamine), the redaction rule is re-applied, "
            "and the published `_summary.csv` and per-voter CSVs are checked against it: "
            "raw and aggregate row counts, processed row count, unique `voter_id`, "
            "Σ `n_sheets` = sheets kept, redacted-row count, and the mark total of "
            "every contest-choice column."
        ),
        "",
        (
            "| Election | status | raw rows | aggregates dropped | sheets kept | Σ n_sheets "
            "| voters (CSV rows) | redacted kept | columns checked | marks (CSV) | marks (raw) |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['election_key']} | {r['status']} | {_fmt(r.get('raw_rows'))} | "
            f"{_fmt(r.get('aggregate_rows'))} | {_fmt(r.get('sheets_kept'))} | "
            f"{_fmt(r.get('sum_n_sheets'))} | {_fmt(r.get('csv_rows'))} | "
            f"{_fmt(r.get('csv_redacted'))} | {_fmt(r.get('n_columns_checked'))} | "
            f"{_fmt(r.get('total_marks_csv'))} | {_fmt(r.get('total_marks_raw'))} |"
        )
    problems = [(r["election_key"], p) for r in rows for p in r.get("problems", [])]
    if problems:
        lines += ["", "## Problems", ""]
        lines += [f"* **{k}**: {p}" for k, p in problems]
    if sov is not None:
        lines += [
            "",
            "## Statement of Votes cross-check (informational)",
            "",
            (
                "Contest-choices present in both this CVR and the Boulder County "
                "Statement of Votes from Election-Results "
                "(`data/processed/statements-of-votes/`). RCV rank columns are skipped. "
                "`cvr_marks` counts the kept rows; `aggregate_marks` the dropped "
                "aggregate rows. Small gaps are expected (write-in adjudication, "
                "the interpreted snapshot), so this never fails the run."
            ),
            "",
            (
                "| Election | choices matched | CVR marks | + aggregate marks | SoV votes "
                "| CVR / SoV | (CVR + agg) / SoV | max abs Δ |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for _, s in sov.iterrows():
            lines.append(
                f"| {s['election_key']} | {int(s['choices_matched'])} | "
                f"{int(s['cvr_marks']):,} | {int(s['aggregate_marks']):,} | "
                f"{int(s['sov_votes']):,} | {s['cvr_share_of_sov']:.4%} | "
                f"{s['with_aggregates_share']:.4%} | {int(s['max_abs_delta']):,} |"
            )
    return "\n".join(lines) + "\n"


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.reconcile", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--sov", type=Path, default=None, metavar="DIR",
                   help="Election-Results data/processed/statements-of-votes/ "
                        "folder for an informational per-contest cross-check")
    a = p.parse_args(argv)
    reconcile(verbose=not a.quiet, sov_dir=a.sov)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
