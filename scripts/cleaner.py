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

**Why redaction exists.** Boulder County, like every Colorado jurisdiction,
must protect voter anonymity where the combination of ballot style and
turnout would let a reader re-identify an individual voter from their CVR.
See the AuditEngine paper (*Auditing Elections Using Ballot Images and
AuditEngine*, Lutz 2022, §3.1.2). The County does this two ways, and the
cleaner treats them differently (see :func:`split_redacted`):

* **Single-ballot redaction** — one ballot's identifiers are blanked
  (``CvrNumber`` = ``"Redacted"`` / ``"RCV Redacted & Randomly Sorted"`` /
  ``NaN``) but its marks are intact. Kept, flagged ``_ID/redacted = True``.
* **Aggregation** — several ballots are summed into one row (cell values
  > 1, or a label containing "Consolidated"/"Aggregated"). Dropped, because
  the row is not one ballot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
    n_aggregate_rows_dropped: int
    """Rows dropped because they sum several ballots (privacy aggregates)."""

    n_sheets_after_redaction: int
    """Sheets kept: ``n_raw_rows - n_aggregate_rows_dropped``. Includes the
    single-ballot redacted rows. Equals the sum of ``_ID/n_sheets``."""

    n_voters: int
    n_choice_columns: int

    n_redacted_kept: int = 0
    """Single-ballot redacted rows kept (``_ID/redacted = True``)."""

    n_redacted_in_multisheet_styles: int = 0
    """Kept redacted rows whose ballot style is multi-sheet. They have no
    Tabulator/Batch/RecordId, so they cannot be matched to the voter's other
    sheet(s) and stay as separate one-sheet rows."""

    n_out_of_order_merges: int = 0
    """Voters whose sheets were scanned out of order (e.g. sheet 2 before
    sheet 1) and merged by the complementary-sheet pass."""

    n_rare_fingerprint_sheets: int = 0
    """Sheets whose contest-fill fingerprint is rare within their ballot style
    (< ``min_fingerprint_share``). Each becomes its own one-sheet voter."""

    n_rare_fingerprint_full_ballot: int = 0
    """Of the rare-fingerprint sheets, how many fill exactly the union of their
    style's sheet fingerprints, i.e. a complete ballot recorded on one row."""

    sheet_count_distribution: dict[int, int] = field(default_factory=dict)
    """Histogram: number of voters with exactly N sheets, keyed on N."""

    multi_sheet_ballot_types: tuple[str, ...] = field(default_factory=tuple)
    """Ballot styles where the cleaner inferred a multi-sheet layout."""

    warnings: tuple[str, ...] = field(default_factory=tuple)
    """Anomalies the cleaner observed and logged."""

    cleaned: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class MergeStats:
    """Bookkeeping from :func:`combine_multisheet`."""

    sheet_count_distribution: dict[int, int] = field(default_factory=dict)
    multi_sheet_ballot_types: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    n_out_of_order_merges: int = 0
    n_rare_fingerprint_sheets: int = 0
    n_rare_fingerprint_full_ballot: int = 0
    n_sheets_per_ballot_type: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase 0: normalize ID values and validate contest cells
# ---------------------------------------------------------------------------


def _col(df: pd.DataFrame, key: tuple) -> pd.Series:
    """Return ``df[key]`` as a Series even if the label is duplicated."""
    s = df[key]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


def normalize_ballot_type(values: pd.Series) -> pd.Series:
    """Return ``values`` as strings, zero-padding purely numeric codes to two
    digits.

    Excel stores ``"04"`` as text but ``10`` as a number, so a raw 2024+ column
    mixes ``str`` and ``int`` (2024 Primary: 42,327 strings and 23,463 ints).
    Normalizing makes ``"04"``, ``"4"``, ``4`` and ``4.0`` the same style and
    keeps ``DS-01`` / ``"04 and 25"`` untouched. Missing stays missing.
    """

    def one(v: object) -> object:
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            return pd.NA
        if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
            return str(int(v)).zfill(2)
        if isinstance(v, (float, np.floating)) and float(v).is_integer():
            return str(int(v)).zfill(2)
        text = str(v).strip()
        if text.isdigit():
            return text.zfill(2)
        return text

    return pd.Series([one(v) for v in values], index=values.index, dtype="string")


def coerce_contest_values(df: pd.DataFrame, contest_cols: list) -> pd.DataFrame:
    """Return a copy of ``df`` with every contest column numeric (float).

    Fails loudly if a cell is non-blank but not a number (e.g. ``"X"`` or
    ``"overvote"``): ``to_numeric(errors="coerce")`` would otherwise turn it
    into ``NaN`` and silently read it as "contest not on this ballot".
    """
    out = df.copy()
    bad: list[str] = []
    for c in contest_cols:
        s = _col(out, c)
        num = pd.to_numeric(s, errors="coerce")
        lost = s.notna() & num.isna()
        if lost.any():
            # Whitespace-only strings are blanks, not data.
            lost[lost] = ~s[lost].map(lambda v: isinstance(v, str) and not v.strip()).astype(bool)
        if lost.any():
            sample = sorted({str(v) for v in s[lost].unique()})[:3]
            bad.append(f"{c[0]}::{c[1]}: {int(lost.sum())} non-numeric value(s) {sample}")
        out[c] = num.astype("float64")
    if bad:
        raise ValueError(
            f"contest cells hold non-numeric values in {len(bad)} column(s); first 5: {bad[:5]}"
        )
    return out


# ---------------------------------------------------------------------------
# Phase 1: split redacted rows into single ballots (kept) and aggregates
# ---------------------------------------------------------------------------

AGGREGATE_LABEL_RE = re.compile(r"consolidat|aggregat", re.IGNORECASE)
"""A ``CvrNumber`` label matching this pattern marks an aggregate row."""


@dataclass
class RedactionSplit:
    """Output of :func:`split_redacted`."""

    ballots: pd.DataFrame
    """Rows with numeric ``CvrNumber`` and ``TabulatorNum`` (ordinary sheets)."""

    redacted: pd.DataFrame
    """Single-ballot redacted rows: identifiers blanked, marks intact."""

    n_aggregate_dropped: int
    """Rows dropped as multi-ballot aggregates."""

    unknown_labels: tuple[str, ...] = ()
    """Non-numeric ``CvrNumber`` labels not in
    :data:`scripts.loader.REDACTED_VALUES` (a new convention to document)."""


def split_redacted(raw_df: pd.DataFrame) -> RedactionSplit:
    """Classify every row as an ordinary ballot sheet, a single redacted
    ballot, or a multi-ballot aggregate.

    A row is **redacted** when ``CvrNumber`` or ``TabulatorNum`` is not a
    number (``pd.to_numeric(..., errors="coerce").isna()``, robust to the
    pandas 2 → 3 change in how missing values look in object columns). A
    redacted row is an **aggregate**, and is dropped, when either

    * its ``CvrNumber`` label contains "Consolidated" or "Aggregated"
      (``"Redacted & Aggregated"``, ``"Redacted and Aggregated - A cards"``,
      ``"Redacted and Consolidated 18 Ballots"``, ...), or
    * any of its contest cells is greater than 1 (a single ballot holds at
      most one mark per choice). This catches the 2019–2022 ``NaN``-label
      aggregates and the 2021 per-style summaries labelled ``"DS-01"``.

    Every other redacted row is one voter's sheet with its identifiers
    blanked (``"Redacted"``, ``"RCV Redacted & Randomly Sorted"``, or a
    ``NaN`` label whose cells are all 0/1/blank). These are kept.

    Contest columns must already be numeric (see
    :func:`coerce_contest_values`).
    """
    cvr = _col(raw_df, ("_ID", "CvrNumber"))
    tab = _col(raw_df, ("_ID", "TabulatorNum"))
    is_redacted = (
        pd.to_numeric(cvr, errors="coerce").isna() | pd.to_numeric(tab, errors="coerce").isna()
    )
    labels = cvr.astype("string")
    label_says_aggregate = labels.str.contains(AGGREGATE_LABEL_RE, na=False)
    cc = contest_columns(raw_df)
    if cc:
        values_say_aggregate = (raw_df[cc].to_numpy(dtype="float64") > 1).any(axis=1)
    else:
        values_say_aggregate = np.zeros(len(raw_df), dtype=bool)
    is_aggregate = is_redacted & (label_says_aggregate | values_say_aggregate)
    is_single = is_redacted & ~is_aggregate

    redacted_labels = labels[is_redacted & ~pd.to_numeric(cvr, errors="coerce").notna()]
    unknown = sorted(
        {
            str(v)
            for v in redacted_labels.dropna().unique()
            if str(v) not in REDACTED_VALUES and not re.fullmatch(r"DS-\d+", str(v))
        }
    )
    return RedactionSplit(
        ballots=raw_df[~is_redacted].copy(),
        redacted=raw_df[is_single].copy(),
        n_aggregate_dropped=int(is_aggregate.sum()),
        unknown_labels=tuple(unknown),
    )


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
    structured = np.ascontiguousarray(packed).view(np.dtype((np.void, packed.shape[1])))
    _, codes = np.unique(structured, return_inverse=True)
    return codes.astype(np.int64).ravel()


def _infer_sheet_map(
    df: pd.DataFrame,
    contest_cols: list[tuple],
    *,
    min_fingerprint_share: float = 0.05,
    fingerprints: np.ndarray | None = None,
) -> tuple[dict[tuple[str, int], int], dict[str, int], list[str], dict[str, int]]:
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
    rare_counts
        ``{"sheets": n, "full_ballot": m}``: sheets with a rare fingerprint,
        and how many of those fill exactly the union of the style's sheet
        fingerprints (a whole ballot recorded on one row).

    The sheet order within each BallotType is decided **empirically** — for
    each ``(TabulatorNum, BatchId)`` group containing rows of that ballot
    style, the fingerprint that appears at the lowest ``RecordId`` is
    "sheet 1," next is "sheet 2," etc. The contest-count heuristic (sheet
    with more non-null contests is likely sheet 1) is computed as a sanity
    check; disagreement logs a warning.

    Fingerprints held by fewer than ``min_fingerprint_share`` of a style's
    sheets get no sheet number: each such sheet becomes its own one-sheet
    voter. Styles with 3+ frequent fingerprints are merged as 3+-sheet voters
    (Dominion supports multi-card ballots); none of the 2019–2025 files has
    one, and the cleaner warns if one appears.
    """
    bt_col = ("_ID", "BallotType")
    tab_col = ("_ID", "TabulatorNum")
    bat_col = ("_ID", "BatchId")
    rec_col = ("_ID", "RecordId")

    notna = df[contest_cols].notna().to_numpy()
    if fingerprints is None:
        fingerprints = _row_fingerprints(notna)
    n_filled_per_row = notna.sum(axis=1)

    bt = _col(df, bt_col).astype(str).to_numpy()

    sheet_map: dict[tuple[str, int], int] = {}
    n_sheets_per_bt: dict[str, int] = {}
    warnings: list[str] = []
    rare_counts = {"sheets": 0, "full_ballot": 0}

    work = pd.DataFrame(
        {
            "bt": bt,
            "fp": fingerprints,
            "tab": pd.to_numeric(_col(df, tab_col), errors="coerce").to_numpy(),
            "bat": pd.to_numeric(_col(df, bat_col), errors="coerce").to_numpy(),
            "rec": pd.to_numeric(_col(df, rec_col), errors="coerce").to_numpy(),
            # Cache the contest-count per row for the sanity check
            "n_filled": n_filled_per_row,
        }
    )
    first_row_of_fp = {int(fp): i for i, fp in reversed(list(enumerate(fingerprints)))}

    for bt_val, sub in work.groupby("bt"):
        # Rare fingerprints (likely anomalies, not real sheets) get no sheet no.
        fp_counts = sub["fp"].value_counts()
        share = fp_counts / fp_counts.sum()
        keep_fps = list(fp_counts[share >= min_fingerprint_share].index)
        rare_fps = list(fp_counts[share < min_fingerprint_share].index)
        if rare_fps:
            n_rare = int(sum(fp_counts[f] for f in rare_fps))
            n_full = 0
            if len(keep_fps) >= 2:
                union = np.logical_or.reduce([notna[first_row_of_fp[int(f)]] for f in keep_fps])
                n_full = int(
                    sum(
                        fp_counts[f]
                        for f in rare_fps
                        if (notna[first_row_of_fp[int(f)]] == union).all()
                    )
                )
            rare_counts["sheets"] += n_rare
            rare_counts["full_ballot"] += n_full
            warnings.append(
                f"BallotType {bt_val!r}: {len(rare_fps)} rare fingerprint(s) "
                f"({n_rare} sheets total, <{min_fingerprint_share:.0%} each; "
                f"{n_full} fill every contest of the style) kept as "
                f"one-sheet voters"
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

    return sheet_map, n_sheets_per_bt, warnings, rare_counts


def _assign_groups(
    bt: np.ndarray,
    tab: np.ndarray,
    bat: np.ndarray,
    cg: np.ndarray,
    rec: np.ndarray,
    sheet_no: np.ndarray,
    n_sheets_of_row: np.ndarray,
) -> tuple[np.ndarray, int]:
    """Assign a voter group id to each row (rows already in scanner order).

    Two passes, both restricted to adjacent rows with the same BallotType,
    TabulatorNum, BatchId and CountingGroup and consecutive RecordId:

    1. **Forward runs.** A row continues the previous voter when its sheet
       number is the previous row's plus one (sheet 1 → sheet 2 → ...).
    2. **Complementary runs.** Adjacent *incomplete* groups from pass 1 merge
       when their sheet sets are disjoint and the union still fits the style
       (e.g. a lone sheet 2 directly followed by a lone sheet 1). This fixes
       ballots scanned back page first. Pass 1 runs first so the ordinary
       forward pairing wins in ambiguous runs such as ``2, 1, 2``.

    Returns ``(group_id, n_out_of_order_merges)``.
    """
    n = len(bt)
    if n == 0:
        return np.empty(0, dtype=np.int64), 0

    same_keys = np.zeros(n, dtype=bool)
    same_keys[1:] = (
        (bt[1:] == bt[:-1])
        & (tab[1:] == tab[:-1])
        & (bat[1:] == bat[:-1])
        & (cg[1:] == cg[:-1])
        & (rec[1:] == rec[:-1] + 1)
    )
    has_sheet = ~np.isnan(sheet_no)
    forward = np.zeros(n, dtype=bool)
    forward[1:] = (
        same_keys[1:] & has_sheet[1:] & has_sheet[:-1] & (sheet_no[1:] == sheet_no[:-1] + 1)
    )
    pass1 = np.cumsum(~forward) - 1  # 0-based group ids

    # Summarize pass-1 groups.
    starts = np.flatnonzero(~forward)
    ends = np.append(starts[1:], n) - 1
    bits = np.where(has_sheet, 1 << np.nan_to_num(sheet_no, nan=0).astype(np.int64), 0)
    masks = np.bitwise_or.reduceat(bits, starts) if n else bits

    def popcount(x: int) -> int:
        return int(x).bit_count()

    group_of_pass1 = np.empty(len(starts), dtype=np.int64)
    gid = 0
    cur_mask = int(masks[0])
    cur_end = ends[0]
    group_of_pass1[0] = 0
    n_ooo = 0
    for g in range(1, len(starts)):
        s, m = starts[g], int(masks[g])
        k = int(n_sheets_of_row[s])
        mergeable = (
            same_keys[s]  # adjacent to previous group's end
            and cur_end == s - 1
            and cur_mask != 0
            and m != 0  # both have inferred sheets
            and (cur_mask & m) == 0  # complementary sheet sets
            and popcount(cur_mask) < k
            and popcount(cur_mask | m) <= k
        )
        if mergeable:
            cur_mask |= m
            n_ooo += 1
        else:
            gid += 1
            cur_mask = m
        cur_end = ends[g]
        group_of_pass1[g] = gid

    return group_of_pass1[pass1], n_ooo


def combine_multisheet(
    df: pd.DataFrame,
    *,
    min_fingerprint_share: float = 0.05,
) -> tuple[pd.DataFrame, MergeStats]:
    """Combine ballot sheets from the same voter into single rows.

    Parameters
    ----------
    df
        Ordinary (non-redacted) sheets from :func:`split_redacted`, contest
        columns numeric. The column MultiIndex from :func:`load_raw_cvr` is
        preserved; the returned frame adds ``('_ID', 'n_sheets')`` and
        ``('_ID', 'voter_id')`` bookkeeping columns.
    min_fingerprint_share
        Per BallotType, fingerprints with less than this share of sheets are
        treated as anomalies (single-sheet voters), not as a sheet.

    Returns
    -------
    merged
        DataFrame with one row per voter, in scanner order.
    stats
        :class:`MergeStats` (sheet-count distribution, multi-sheet styles,
        warnings, out-of-order merges, rare-fingerprint counts).
    """
    bt_col = ("_ID", "BallotType")
    tab_col = ("_ID", "TabulatorNum")
    bat_col = ("_ID", "BatchId")
    rec_col = ("_ID", "RecordId")
    cg_col = ("_ID", "CountingGroup")
    cvr_col = ("_ID", "CvrNumber")
    imp_col = ("_ID", "ImprintedId")

    contest_cols = contest_columns(df)

    if len(df) == 0:
        empty = df.iloc[0:0].copy()
        empty[("_ID", "n_sheets")] = pd.Series(dtype="int64")
        empty[("_ID", "voter_id")] = pd.Series(dtype="string")
        return empty, MergeStats()

    # Compute fingerprints ONCE; pass into sheet-map inference + reuse for
    # per-row sheet assignment below.
    notna = df[contest_cols].notna().to_numpy()
    fingerprints = _row_fingerprints(notna)

    sheet_map, n_sheets_per_bt, warnings, rare_counts = _infer_sheet_map(
        df,
        contest_cols,
        min_fingerprint_share=min_fingerprint_share,
        fingerprints=fingerprints,
    )
    multi_sheet_bts = tuple(sorted(bt for bt, n in n_sheets_per_bt.items() if n >= 2))

    bt = _col(df, bt_col).astype(str)
    tab = pd.to_numeric(_col(df, tab_col), errors="coerce")
    bat = pd.to_numeric(_col(df, bat_col), errors="coerce")
    rec = pd.to_numeric(_col(df, rec_col), errors="coerce")
    if cg_col in df.columns:
        cg = _col(df, cg_col).astype(str)
    else:
        cg = pd.Series(["_"] * len(df), index=df.index)

    # Assign each row its sheet number (NaN if its fingerprint has none).
    bt_arr = bt.to_numpy()
    if sheet_map:
        keys = pd.MultiIndex.from_tuples(list(sheet_map.keys()), names=("bt", "fp"))
        lookup = pd.Series(list(sheet_map.values()), index=keys, dtype="float64")
        row_keys = pd.MultiIndex.from_arrays(
            [bt_arr, fingerprints.astype(np.int64)], names=("bt", "fp")
        )
        sheet_no = lookup.reindex(row_keys).to_numpy()
    else:
        sheet_no = np.full(len(df), np.nan)
    n_sheets_of_row = np.array([n_sheets_per_bt.get(b, 0) for b in bt_arr], dtype=np.int64)

    # Sort by (tab, bat, rec) and assign voter groups.
    sort_order = np.lexsort(
        (rec.fillna(-1).to_numpy(), bat.fillna(-1).to_numpy(), tab.fillna(-1).to_numpy())
    )
    df_sorted = df.iloc[sort_order].reset_index(drop=True)
    group_id, n_ooo = _assign_groups(
        bt_arr[sort_order],
        tab.to_numpy(dtype="float64")[sort_order],
        bat.to_numpy(dtype="float64")[sort_order],
        cg.to_numpy()[sort_order],
        rec.to_numpy(dtype="float64")[sort_order],
        sheet_no[sort_order],
        n_sheets_of_row[sort_order],
    )
    df_sorted[("_ID", "_group_id")] = group_id

    # Aggregate: ID columns take the first (lowest-RecordId) row in each
    # group; contest columns take max (values are 0/1/NaN and a voter's
    # sheets fill disjoint contests, so max keeps the one recorded value).
    id_cols = [c for c in df_sorted.columns if c[0] == "_ID" and c[1] != "_group_id"]
    agg: dict = {}
    for c in id_cols:
        agg[c] = "first"
    for c in contest_cols:
        agg[c] = "max"

    merged = (
        df_sorted.groupby(("_ID", "_group_id"), sort=False)
        .agg(agg)
        .reset_index(drop=True)
        .copy()  # defragment before adding bookkeeping columns
    )
    merged.columns = pd.MultiIndex.from_tuples(merged.columns)

    # Bookkeeping columns
    sheet_counts = pd.Series(group_id).value_counts().sort_index()
    merged[("_ID", "n_sheets")] = sheet_counts.to_numpy(dtype="int64")
    if imp_col in merged.columns:
        # voter_id = ImprintedId of the lowest-RecordId sheet (already first)
        merged[("_ID", "voter_id")] = _col(merged, imp_col).astype("string").to_numpy()
    else:
        merged[("_ID", "voter_id")] = _col(merged, cvr_col).astype("string").to_numpy()

    sheet_count_dist = {
        int(k): int(v) for k, v in pd.Series(sheet_counts.values).value_counts().items()
    }

    return merged, MergeStats(
        sheet_count_distribution=sheet_count_dist,
        multi_sheet_ballot_types=multi_sheet_bts,
        warnings=tuple(warnings),
        n_out_of_order_merges=n_ooo,
        n_rare_fingerprint_sheets=rare_counts["sheets"],
        n_rare_fingerprint_full_ballot=rare_counts["full_ballot"],
        n_sheets_per_ballot_type=n_sheets_per_bt,
    )


# ---------------------------------------------------------------------------
# Phase 3: full pipeline (split redaction + merge sheets + tidy)
# ---------------------------------------------------------------------------


def _redacted_voter_rows(redacted: pd.DataFrame, columns: pd.MultiIndex) -> pd.DataFrame:
    """Turn kept single-ballot redacted rows into voter rows.

    They carry no Tabulator/Batch/RecordId, so they cannot be merged with any
    other sheet: each is its own one-sheet voter. ``voter_id`` is
    ``redacted-NNNNN`` numbered in source-file order, so it stays unique and
    stable across re-runs of the same file.
    """
    out = redacted.copy()
    out[("_ID", "n_sheets")] = np.ones(len(out), dtype="int64")
    out[("_ID", "voter_id")] = pd.array(
        [f"redacted-{i:05d}" for i in range(1, len(out) + 1)], dtype="string"
    )
    return out.reindex(columns=columns)


def clean_countywide(
    raw_df: pd.DataFrame,
    election_key: str,
    *,
    min_fingerprint_share: float = 0.05,
) -> CleanResult:
    """Classify redacted rows, combine multi-sheet ballots into per-voter
    rows, and flatten the column MultiIndex for CSV serialization.

    Every ballot in the county is retained (no jurisdiction filter). Use
    :func:`detect_city_ballot_types`, or the contest-name filter in
    ``clusters.ipynb``, to restrict to City of Boulder downstream.

    Steps:

    1. Normalize ``BallotType`` to strings (numeric codes zero-padded).
    2. Coerce contest cells to numbers, failing on non-blank text.
    3. :func:`split_redacted`: drop multi-ballot aggregates; keep
       single-ballot redacted rows with ``_ID/redacted = True``.
    4. :func:`combine_multisheet` on the ordinary sheets.
    5. Append the redacted rows as one-sheet voters.
    6. Drop all-blank contest columns, cast contest cells to nullable
       ``Int8`` (so marks write as ``1``/``0`` and blanks stay blank), and
       flatten column names.

    Parameters
    ----------
    raw_df
        Output of :func:`scripts.loader.load_raw_cvr`.
    election_key
        Slug used in logging and downstream filenames.
    min_fingerprint_share
        Forwarded to :func:`combine_multisheet`.
    """
    n_raw = len(raw_df)
    contest_cols = contest_columns(raw_df)
    bt_col = ("_ID", "BallotType")

    df = coerce_contest_values(raw_df, contest_cols)
    if bt_col in df.columns:
        df[bt_col] = normalize_ballot_type(_col(df, bt_col))

    # 1. Split redacted rows: aggregates dropped, single ballots kept.
    split = split_redacted(df)
    warnings: list[str] = []
    if split.unknown_labels:
        warnings.append(
            f"unrecognized CvrNumber label(s) on redacted rows: "
            f"{list(split.unknown_labels)[:5]}; classified by cell values"
        )

    # 2. Combine sheets into per-voter rows (ordinary sheets only).
    merged, stats = combine_multisheet(
        split.ballots,
        min_fingerprint_share=min_fingerprint_share,
    )
    warnings.extend(stats.warnings)
    merged = merged.copy()
    merged[("_ID", "redacted")] = False

    # 3. Kept redacted ballots become their own one-sheet voters.
    red = _redacted_voter_rows(split.redacted, merged.columns.drop(("_ID", "redacted")))
    red[("_ID", "redacted")] = True
    n_red = len(red)
    multi_bts = set(stats.multi_sheet_ballot_types)
    n_red_multi = int(_col(red, bt_col).isin(multi_bts).sum()) if n_red else 0

    combined = pd.concat([merged, red], ignore_index=True) if n_red else merged
    combined[("_ID", "redacted")] = combined[("_ID", "redacted")].astype(bool)

    sheet_dist = dict(stats.sheet_count_distribution)
    if n_red:
        sheet_dist[1] = sheet_dist.get(1, 0) + n_red

    # 4. Drop ballot-choice columns that are entirely blank across the
    #    output. This rarely fires (every contest is on someone's ballot)
    #    but it keeps the schema honest. Then cast marks to nullable Int8.
    keep = [c for c in combined.columns if c[0] == "_ID" or combined[c].notna().any()]
    combined = combined.loc[:, keep].copy()
    for c in contest_columns(combined):
        combined[c] = combined[c].astype("Int8")
    combined[("_ID", "n_sheets")] = combined[("_ID", "n_sheets")].astype("int64")

    # 5. Integrity checks.
    if len(combined) > 0:
        for required in (
            "CvrNumber",
            "TabulatorNum",
            "BallotType",
            "n_sheets",
            "voter_id",
            "redacted",
        ):
            assert ("_ID", required) in combined.columns, (
                f"{election_key} missing required ID column: {required}"
            )
        n_sheets_total = int(combined[("_ID", "n_sheets")].sum())
        assert n_sheets_total == n_raw - split.n_aggregate_dropped, (
            f"{election_key}: sum(n_sheets)={n_sheets_total} != sheets kept "
            f"{n_raw - split.n_aggregate_dropped}"
        )

    # 6. Flatten columns for CSV serialization.
    combined.columns = flatten_columns(combined)
    n_choice = sum(1 for c in combined.columns if not c.startswith("_ID/"))

    return CleanResult(
        election_key=election_key,
        n_raw_rows=n_raw,
        n_aggregate_rows_dropped=split.n_aggregate_dropped,
        n_sheets_after_redaction=n_raw - split.n_aggregate_dropped,
        n_voters=len(combined),
        n_choice_columns=n_choice,
        n_redacted_kept=n_red,
        n_redacted_in_multisheet_styles=n_red_multi,
        n_out_of_order_merges=stats.n_out_of_order_merges,
        n_rare_fingerprint_sheets=stats.n_rare_fingerprint_sheets,
        n_rare_fingerprint_full_ballot=stats.n_rare_fingerprint_full_ballot,
        sheet_count_distribution=sheet_dist,
        multi_sheet_ballot_types=stats.multi_sheet_ballot_types,
        warnings=tuple(warnings),
        cleaned=combined,
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

    marker_cols = [c for c in contest_columns(df) if isinstance(c[0], str) and marker in c[0]]
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
        DeprecationWarning,
        stacklevel=2,
    )
    # Strip the unused city_ballot_types/marker kwargs
    kwargs.pop("city_ballot_types", None)
    kwargs.pop("marker", None)
    return clean_countywide(*args, **kwargs)
