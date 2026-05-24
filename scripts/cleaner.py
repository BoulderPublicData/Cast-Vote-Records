"""Drop privacy-aggregated rows, then combine consecutive ballot **sheets** into
per-**voter** rows.

A Dominion CVR has one row per ballot **sheet** (per [NIST SP 1500-103
§3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)). High-information ballots
span multiple sheets — the 2024 Boulder County General, for example, used a
two-sheet ballot for nearly every ballot style. Treating each row as one
voter therefore over-counts voters by the average sheet-count of the
election (roughly 2× for 2024G). This module merges adjacent ballot sheets
from the same voter back into a single voter row.

The Dominion CVR does **not** carry an explicit ``CVR::BallotSheetId``
(NIST §3.5.2). The sheet number must be inferred from which contests are
filled on each sheet — sheet 1 of any given ballot style always has the
same set of contests, sheet 2 has a different (disjoint) set, and so on.
:func:`combine_multisheet` does this inference per BallotType, then walks
the rows in scanner order (`Tab, Batch, RecordId`) to merge each
``(sheet K, sheet K+1, ...)`` consecutive run into one voter.

**Why privacy aggregation exists.** Boulder County, like every Colorado
jurisdiction, must protect voter anonymity by aggregating ballots in
precincts where the combination of ballot-style and turnout would let a
reader re-identify an individual voter from their CVR. See the AuditEngine
paper (*Auditing Elections Using Ballot Images and AuditEngine*, Lutz 2022,
§3.1.2). Three conventions appear in Boulder's redacted exports — see
:func:`clean_countywide` for the detection rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .loader import REDACTED_VALUES, contest_columns


CITY_CONTEST_MARKER = "City of Boulder"
"""Default substring used by :func:`detect_city_ballot_types` to identify
ballot styles that vote on City of Boulder municipal contests."""


@dataclass
class CleanResult:
    """Outcome of one election's pipeline run."""

    election_key: str
    n_raw_rows: int
    n_redacted_dropped: int
    n_sheets_after_redaction: int
    n_voters: int
    n_choice_columns: int
    sheet_count_distribution: dict[int, int] = field(default_factory=dict)
    """Histogram: number of voters with exactly N sheets, keyed on N."""

    multi_sheet_ballot_types: tuple[str, ...] = field(default_factory=tuple)
    """Ballot styles where the cleaner inferred a multi-sheet layout."""

    warnings: tuple[str, ...] = field(default_factory=tuple)
    """Anomalies the cleaner observed and logged."""

    cleaned: pd.DataFrame = field(default_factory=pd.DataFrame)


# ---------------------------------------------------------------------------
# Phase 1: drop privacy-aggregated rows
# ---------------------------------------------------------------------------

def _drop_redacted(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop rows where ``CvrNumber`` or ``TabulatorNum`` is not a valid integer.

    Boulder County uses three privacy-aggregation conventions that
    collectively differ from a real ballot in one observable way: a real
    ballot has BOTH an integer ``CvrNumber`` AND an integer ``TabulatorNum``.
    The three aggregation conventions each fail at least one check:

    (a) 2023+ — ``CvrNumber`` is a sentinel string like
        ``"RCV Redacted & Randomly Sorted"`` or ``"Redacted & Aggregated"``
        (non-numeric).
    (b) 2019–2022 — ``CvrNumber`` is ``NaN`` (one aggregate row per
        BallotType).
    (c) 2021 — ``TabulatorNum`` is ``NaN`` and ``CvrNumber`` holds the
        ballot-style code (``"DS-01"`` — also non-numeric).

    ``pd.to_numeric(..., errors='coerce').isna()`` catches all three and is
    robust to the pandas 2.x → 3.x change in how NaN is represented in
    object/string columns.
    """
    cvr_col = ("_ID", "CvrNumber")
    tab_col = ("_ID", "TabulatorNum")
    cvr_vals = raw_df[cvr_col]
    if isinstance(cvr_vals, pd.DataFrame):
        cvr_vals = cvr_vals.iloc[:, 0]
    tab_vals = raw_df[tab_col]
    if isinstance(tab_vals, pd.DataFrame):
        tab_vals = tab_vals.iloc[:, 0]
    missing_cvr_mask = pd.to_numeric(cvr_vals, errors="coerce").isna()
    missing_tab_mask = pd.to_numeric(tab_vals, errors="coerce").isna()
    redacted_mask = missing_cvr_mask | missing_tab_mask
    return raw_df[~redacted_mask].copy(), int(redacted_mask.sum())


# ---------------------------------------------------------------------------
# Phase 2: multi-sheet merge
# ---------------------------------------------------------------------------

def _row_fingerprints(notna_matrix: np.ndarray) -> np.ndarray:
    """Return an integer fingerprint per row.

    Each row's contest-fill pattern (boolean ``notna`` mask across the contest
    columns) is packed into bytes via :func:`numpy.packbits`, then mapped to a
    distinct ``int64`` code via :func:`numpy.unique` on a structured-array
    view. Rows with identical non-null patterns share the same code.

    Vectorized — runs in milliseconds even on the ~400k-row 2024 General CVR.
    Replaces an earlier per-row ``hashlib.md5`` loop that took ~60 s on the
    same input.
    """
    if notna_matrix.size == 0:
        return np.array([], dtype=np.int64)
    if notna_matrix.dtype != np.bool_:
        notna_matrix = notna_matrix.astype(np.bool_)
    packed = np.packbits(notna_matrix, axis=1)  # (N, ceil(C/8))
    # View each row's packed bytes as a single structured element so np.unique
    # can hash whole rows in one pass.
    structured = np.ascontiguousarray(packed).view(
        np.dtype((np.void, packed.shape[1]))
    )
    _, codes = np.unique(structured, return_inverse=True)
    return codes.astype(np.int64).ravel()


def _infer_sheet_map(
    df: pd.DataFrame,
    contest_cols: list[tuple],
    *,
    min_fingerprint_share: float = 0.05,
    fingerprints: Optional[np.ndarray] = None,
) -> tuple[dict[tuple[str, int], int], dict[str, int], list[str]]:
    """Per BallotType, identify distinct contest-fill fingerprints and rank
    them by sheet order (sheet 1 first).

    Returns
    -------
    sheet_map
        ``{(BallotType, fingerprint): sheet_number}`` (1-indexed).
    n_sheets_per_bt
        ``{BallotType: number of distinct sheet fingerprints}``.
    warnings
        Per-BallotType anomaly notes.

    The sheet order within each BallotType is decided **empirically** — for
    each ``(TabulatorNum, BatchId)`` group containing rows of that ballot
    style, the fingerprint that appears at the lowest ``RecordId`` is
    "sheet 1," next is "sheet 2," etc. The contest-count heuristic (sheet
    with more non-null contests is likely sheet 1) is computed as a sanity
    check; disagreement logs a warning.
    """
    bt_col = ("_ID", "BallotType")
    tab_col = ("_ID", "TabulatorNum")
    bat_col = ("_ID", "BatchId")
    rec_col = ("_ID", "RecordId")

    # Compute per-row fingerprints (vectorized) — or reuse caller-supplied
    if fingerprints is None:
        notna = df[contest_cols].notna().to_numpy()
        fingerprints = _row_fingerprints(notna)
        n_filled_per_row = notna.sum(axis=1)
    else:
        n_filled_per_row = df[contest_cols].notna().to_numpy().sum(axis=1)

    bt = df[bt_col]
    if isinstance(bt, pd.DataFrame):
        bt = bt.iloc[:, 0]
    bt = bt.astype(str).to_numpy()

    sheet_map: dict[tuple[str, int], int] = {}
    n_sheets_per_bt: dict[str, int] = {}
    warnings: list[str] = []

    work = pd.DataFrame({
        "bt":  bt,
        "fp":  fingerprints,
        "tab": pd.to_numeric(df[tab_col], errors="coerce").to_numpy(),
        "bat": pd.to_numeric(df[bat_col], errors="coerce").to_numpy(),
        "rec": pd.to_numeric(df[rec_col], errors="coerce").to_numpy(),
        # Cache the contest-count per row for the sanity check
        "n_filled": n_filled_per_row,
    })

    for bt_val, sub in work.groupby("bt"):
        # Drop rare fingerprints (likely anomalies, not real sheets)
        fp_counts = sub["fp"].value_counts()
        share = fp_counts / fp_counts.sum()
        keep_fps = list(fp_counts[share >= min_fingerprint_share].index)
        rare_fps = list(fp_counts[share < min_fingerprint_share].index)
        if rare_fps:
            warnings.append(
                f"BallotType {bt_val!r}: {len(rare_fps)} rare fingerprint(s) "
                f"({sum(fp_counts[f] for f in rare_fps)} sheets total, "
                f"<{min_fingerprint_share:.0%} each) treated as 1-sheet voters"
            )

        if len(keep_fps) == 0:
            n_sheets_per_bt[str(bt_val)] = 0
            continue
        if len(keep_fps) == 1:
            sheet_map[(str(bt_val), int(keep_fps[0]))] = 1
            n_sheets_per_bt[str(bt_val)] = 1
            continue

        # Empirical ordering: within each (tab, bat) group, which fingerprint
        # comes first by RecordId?
        first_fp_counter: dict[int, int] = {int(fp): 0 for fp in keep_fps}
        sub_keep = sub[sub["fp"].isin(keep_fps)]
        for (_, _), grp in sub_keep.groupby(["tab", "bat"]):
            ordered = grp.sort_values("rec")["fp"].tolist()
            seen: set[int] = set()
            for k, fp in enumerate(ordered):
                fp_int = int(fp)
                if fp_int in seen:
                    continue
                seen.add(fp_int)
                # Score: first occurrence gets +len(keep_fps), next +len-1, ...
                first_fp_counter[fp_int] += len(keep_fps) - k
                if len(seen) == len(keep_fps):
                    break

        ordered_fps = sorted(
            (int(fp) for fp in keep_fps),
            key=lambda fp: (-first_fp_counter[fp], fp),
        )
        for i, fp in enumerate(ordered_fps, start=1):
            sheet_map[(str(bt_val), int(fp))] = i
        n_sheets_per_bt[str(bt_val)] = len(ordered_fps)

        # Sanity check: the contest-count heuristic suggests sheet 1 has more
        # non-null columns than sheet 2. Warn if empirical order disagrees.
        if len(ordered_fps) >= 2:
            sheet1_count = sub[sub["fp"] == ordered_fps[0]]["n_filled"].iloc[0]
            sheet2_count = sub[sub["fp"] == ordered_fps[1]]["n_filled"].iloc[0]
            if sheet2_count > sheet1_count:
                warnings.append(
                    f"BallotType {bt_val!r}: empirical sheet 1 has fewer "
                    f"non-null contests ({sheet1_count}) than empirical "
                    f"sheet 2 ({sheet2_count}). Trusting empirical order "
                    f"per the data-liberation convention; consider manual "
                    f"audit."
                )

        if len(ordered_fps) >= 3:
            warnings.append(
                f"BallotType {bt_val!r}: {len(ordered_fps)} sheet fingerprints "
                f"detected (3+). The merger will treat these as "
                f"{len(ordered_fps)}-sheet voters; verify against the original "
                f"ballot design."
            )

    return sheet_map, n_sheets_per_bt, warnings


def combine_multisheet(
    df: pd.DataFrame,
    *,
    min_fingerprint_share: float = 0.05,
) -> tuple[pd.DataFrame, dict[int, int], tuple[str, ...], tuple[str, ...]]:
    """Combine consecutive ballot sheets from the same voter into single rows.

    Parameters
    ----------
    df
        Output of :func:`_drop_redacted` (post-loader, post-redaction). The
        column MultiIndex from :func:`load_raw_cvr` is preserved on input;
        the returned frame has the same MultiIndex plus two new ``('_ID',
        'n_sheets')`` and ``('_ID', 'voter_id')`` bookkeeping columns.
    min_fingerprint_share
        Per BallotType, fingerprints with less than this share of sheets are
        treated as anomalies (single-sheet voters), not as a sheet.

    Returns
    -------
    merged
        DataFrame with one row per voter.
    sheet_count_distribution
        ``{n_sheets: n_voters_with_exactly_this_many_sheets}``.
    multi_sheet_ballot_types
        Sorted tuple of ballot-style codes the cleaner inferred to be
        multi-sheet.
    warnings
        Per-BallotType anomaly notes from sheet inference.
    """
    bt_col = ("_ID", "BallotType")
    tab_col = ("_ID", "TabulatorNum")
    bat_col = ("_ID", "BatchId")
    rec_col = ("_ID", "RecordId")
    cg_col = ("_ID", "CountingGroup")
    cvr_col = ("_ID", "CvrNumber")
    imp_col = ("_ID", "ImprintedId")

    contest_cols = contest_columns(df)

    # Compute fingerprints ONCE; pass into sheet-map inference + reuse for
    # per-row sheet assignment below.
    notna = df[contest_cols].notna().to_numpy()
    fingerprints = _row_fingerprints(notna)

    sheet_map, n_sheets_per_bt, warnings = _infer_sheet_map(
        df, contest_cols,
        min_fingerprint_share=min_fingerprint_share,
        fingerprints=fingerprints,
    )
    multi_sheet_bts = tuple(sorted(
        bt for bt, n in n_sheets_per_bt.items() if n >= 2
    ))

    bt = df[bt_col]
    if isinstance(bt, pd.DataFrame):
        bt = bt.iloc[:, 0]
    bt = bt.astype(str)

    tab = pd.to_numeric(df[tab_col], errors="coerce")
    bat = pd.to_numeric(df[bat_col], errors="coerce")
    rec = pd.to_numeric(df[rec_col], errors="coerce")
    if cg_col in df.columns:
        cg = df[cg_col]
        if isinstance(cg, pd.DataFrame):
            cg = cg.iloc[:, 0]
        cg = cg.astype(str)
    else:
        cg = pd.Series(["_"] * len(df), index=df.index)

    # Assign each row its sheet number (NaN if BallotType wasn't in the map).
    # Vectorized via a Series lookup against a pre-built index.
    bt_arr = bt.to_numpy()
    if sheet_map:
        # Build a lookup Series keyed on (bt, fp) pairs
        keys = pd.MultiIndex.from_tuples(list(sheet_map.keys()),
                                         names=("bt", "fp"))
        lookup = pd.Series(list(sheet_map.values()), index=keys, dtype="float64")
        # Construct per-row keys and look up
        row_keys = pd.MultiIndex.from_arrays(
            [bt_arr, fingerprints.astype(np.int64)], names=("bt", "fp")
        )
        sheet_no = lookup.reindex(row_keys).to_numpy()
    else:
        sheet_no = np.full(len(df), np.nan)

    # Sort by (tab, bat, rec) and walk to assign group_ids.
    sort_order = np.lexsort((rec.fillna(-1).to_numpy(),
                             bat.fillna(-1).to_numpy(),
                             tab.fillna(-1).to_numpy()))
    df_sorted = df.iloc[sort_order].reset_index(drop=True)
    sheet_no = sheet_no[sort_order]
    bt_arr = bt.to_numpy()[sort_order]
    tab_arr = tab.to_numpy()[sort_order]
    bat_arr = bat.to_numpy()[sort_order]
    rec_arr = rec.to_numpy()[sort_order]
    cg_arr = cg.to_numpy()[sort_order]

    # Group assignment: a row starts a new group unless it continues the
    # previous voter (sheet_no = prev + 1, same BallotType / batch / tab /
    # counting group, consecutive RecordId).
    group_id = np.empty(len(df_sorted), dtype=np.int64)
    gid = 0
    group_id[0] = 0
    for i in range(1, len(df_sorted)):
        is_continuation = (
            bt_arr[i] == bt_arr[i-1]
            and tab_arr[i] == tab_arr[i-1]
            and bat_arr[i] == bat_arr[i-1]
            and cg_arr[i] == cg_arr[i-1]
            and rec_arr[i] == rec_arr[i-1] + 1
            and not np.isnan(sheet_no[i])
            and not np.isnan(sheet_no[i-1])
            and sheet_no[i] == sheet_no[i-1] + 1
        )
        if not is_continuation:
            gid += 1
        group_id[i] = gid

    df_sorted = df_sorted.copy()
    df_sorted[("_ID", "_group_id")] = group_id

    # Aggregate: ID columns take first row in each group; contest columns
    # take max (since values are 0/1/NaN, max with skipna gives the
    # marked value if any sheet recorded one).
    id_cols = [c for c in df_sorted.columns if c[0] == "_ID" and c[1] != "_group_id"]
    agg: dict = {}
    for c in id_cols:
        agg[c] = "first"
    for c in contest_cols:
        agg[c] = "max"

    merged = df_sorted.groupby(("_ID", "_group_id"), sort=False).agg(agg)
    merged.reset_index(drop=True, inplace=True)
    merged.columns = pd.MultiIndex.from_tuples(merged.columns)

    # Bookkeeping columns
    sheet_counts = pd.Series(group_id).value_counts().sort_index()
    merged[("_ID", "n_sheets")] = sheet_counts.values
    if imp_col in merged.columns:
        # voter_id = ImprintedId of the lowest-RecordId sheet (already first)
        imp_first = merged[imp_col]
        if isinstance(imp_first, pd.DataFrame):
            imp_first = imp_first.iloc[:, 0]
        merged[("_ID", "voter_id")] = imp_first.values
    else:
        merged[("_ID", "voter_id")] = merged[cvr_col].astype(str).values

    sheet_count_dist = {int(k): int(v) for k, v in
                        pd.Series(sheet_counts.values).value_counts().items()}

    return merged, sheet_count_dist, multi_sheet_bts, tuple(warnings)


# ---------------------------------------------------------------------------
# Phase 3: full pipeline (drop redaction + merge sheets + tidy)
# ---------------------------------------------------------------------------

def clean_countywide(
    raw_df: pd.DataFrame,
    election_key: str,
    *,
    min_fingerprint_share: float = 0.05,
) -> CleanResult:
    """Drop redacted rows, combine multi-sheet ballots into per-voter rows,
    and flatten the column MultiIndex for CSV serialization.

    Unlike the deprecated :func:`clean_city_cvr`, this function does **not**
    filter by jurisdiction — every ballot in the county is retained. Use
    :func:`detect_city_ballot_types` if you need to filter to City of
    Boulder downstream.

    Parameters
    ----------
    raw_df
        Output of :func:`cvr_pipeline.loader.load_raw_cvr`.
    election_key
        Slug used in logging and downstream filenames.
    min_fingerprint_share
        Forwarded to :func:`combine_multisheet`.

    Returns
    -------
    CleanResult
        Includes the cleaned DataFrame (with flattened column names),
        sheet-count distribution, multi-sheet ballot types, and any
        cleaner warnings.
    """
    n_raw = len(raw_df)

    # 1. Drop privacy-aggregated rows.
    df, n_redacted = _drop_redacted(raw_df)
    n_sheets_post = len(df)

    # 2. Combine consecutive sheets into per-voter rows.
    merged, sheet_dist, multi_bts, warnings = combine_multisheet(
        df, min_fingerprint_share=min_fingerprint_share,
    )

    # 3. Drop ballot-choice columns that are entirely NaN across the merged
    #    output. This rarely fires — almost every contest is voted on by at
    #    least someone — but it keeps the schema honest.
    keep = []
    for c in merged.columns:
        if c[0] == "_ID":
            keep.append(c)
        elif merged[c].notna().any():
            keep.append(c)
    merged = merged.loc[:, keep]

    # 4. Integrity checks.
    if len(merged) > 0:
        for required in ("CvrNumber", "TabulatorNum", "BallotType",
                         "n_sheets", "voter_id"):
            assert ("_ID", required) in merged.columns, (
                f"{election_key} missing required ID column: {required}"
            )

    # 5. Flatten columns for CSV serialization.
    merged.columns = flatten_columns(merged)
    n_choice = sum(1 for c in merged.columns if not c.startswith("_ID/"))

    return CleanResult(
        election_key=election_key,
        n_raw_rows=n_raw,
        n_redacted_dropped=n_redacted,
        n_sheets_after_redaction=n_sheets_post,
        n_voters=len(merged),
        n_choice_columns=n_choice,
        sheet_count_distribution=sheet_dist,
        multi_sheet_ballot_types=multi_bts,
        warnings=warnings,
        cleaned=merged,
    )


# ---------------------------------------------------------------------------
# Downstream-helper utilities (still useful even with countywide as default)
# ---------------------------------------------------------------------------

def detect_city_ballot_types(
    df: pd.DataFrame,
    marker: str = CITY_CONTEST_MARKER,
    min_ballots: int = 5,
) -> tuple[str, ...]:
    """Return the ballot-style codes that vote on at least one ``marker``
    contest.

    Kept available for downstream consumers (notebooks, ad-hoc analyses)
    even though the primary pipeline no longer filters by jurisdiction.
    The threshold ``min_ballots`` defends against single-row aggregates
    that survive the redaction filter.
    """
    bt_col = ("_ID", "BallotType")
    if bt_col not in df.columns:
        raise KeyError("DataFrame has no BallotType column; load with load_raw_cvr")

    bt = df[bt_col]
    if isinstance(bt, pd.DataFrame):
        bt = bt.iloc[:, 0]
    bt = bt.astype(str)

    marker_cols = [
        c for c in contest_columns(df)
        if isinstance(c[0], str) and marker in c[0]
    ]
    if not marker_cols:
        return ()

    out: set[str] = set()
    for bt_val in bt.dropna().unique():
        sub = df[bt == bt_val]
        n_with_marker = sub[marker_cols].notna().any(axis=1).sum()
        if n_with_marker > min_ballots:
            out.add(str(bt_val))
    return tuple(sorted(out))


def flatten_columns(df: pd.DataFrame) -> list[str]:
    """Flatten a :func:`load_raw_cvr` MultiIndex into CSV-friendly column names.

    ID columns become ``_ID/<label>``; contest columns become
    ``<contest>::<candidate>``.
    """
    out: list[str] = []
    for c in df.columns:
        if c[0] == "_ID":
            out.append(f"_ID/{c[1]}")
        else:
            out.append(f"{c[0]}::{c[1]}")
    return out


# ---------------------------------------------------------------------------
# DEPRECATED: kept for backwards compatibility with any external scripts
# ---------------------------------------------------------------------------

def clean_city_cvr(*args, **kwargs):
    """Deprecated. Use :func:`clean_countywide` and filter downstream.

    Raises a ``DeprecationWarning`` and forwards to ``clean_countywide``
    so existing callers do not silently break. The City of Boulder filter
    moved into the analysis layer (see ``clusters.ipynb``).
    """
    import warnings as _warnings
    _warnings.warn(
        "clean_city_cvr() is deprecated; use clean_countywide() and filter "
        "to City of Boulder downstream via detect_city_ballot_types().",
        DeprecationWarning, stacklevel=2,
    )
    # Strip the unused city_ballot_types/marker kwargs
    kwargs.pop("city_ballot_types", None)
    kwargs.pop("marker", None)
    return clean_countywide(*args, **kwargs)
