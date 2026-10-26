# Data dictionary — countywide per-voter CVRs

Per-column reference for ``data/processed/<election>-county-wide-by-voter.csv``. Each row is one **voter** — i.e. the merger of all ballot **sheets** that voter returned (one or more). A Dominion CVR exports one row per ballot sheet (per [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)); Boulder's 2024 General used a two-sheet ballot for nearly every style, so the per-sheet row count is roughly 2× the per-voter row count. The cleaner combines consecutive sheets from the same voter back into a single voter row; see [`methodology.md`](methodology.md) for the merge rules.

Each column is either an identifier (prefix ``_ID/``) or a ballot-choice column (``<contest>::<candidate>``).

The auto-generated mechanical complement to this file is [`variables.md`](variables.md), regenerated on every `python -m scripts.audit` run.

## ID columns

| Column | NIST CDF attribute | Type | Description |
| --- | --- | --- | --- |
| `_ID/CvrNumber` | `CVR::UniqueId` ([NIST §3.5.1](https://doi.org/10.6028/NIST.SP.1500-103)) | string-as-int | Per-CVR unique identifier within the report. On a redacted ballot (`_ID/redacted = True`) it holds the County's label instead (`Redacted`, `RCV Redacted & Randomly Sorted`) or is blank. Aggregate rows (several ballots summed) are dropped upstream, so every row is one ballot. |
| `_ID/TabulatorNum` | `CVR::CreatingDevice.SerialNumber` (NIST §3.5.6) | string-as-int | The scanner that captured this ballot. Blank on redacted ballots, as are `BatchId`, `RecordId` and `ImprintedId`. |
| `_ID/BatchId` | `CVRSnapshot::BatchId` (NIST §3.5.5) | string-as-int | Batch identifier. |
| `_ID/RecordId` | `CVRSnapshot::BatchSequenceId` (NIST §3.5.5) | string-as-int | Position within the batch. |
| `_ID/ImprintedId` | `CVR::BallotAuditId` (NIST §3.5.4) | string | Composite `TabulatorNum-BatchId-RecordId`. The Dominion scanner can imprint this on the paper ballot, enabling ballot-level comparison auditing (Colorado RLA). |
| `_ID/CountingGroup` | Dominion-specific | string | `Regular` / `Mail` / `Provisional`. Present in 2019, 2020, 2022, 2024+; absent in 2021, 2023. |
| `_ID/PrecinctPortion` | (cf. NIST `BallotStyleUnit` §3.5.6) | string | Political-geography portion of the precinct served by this ballot style. Present in 2019 and 2021. |
| `_ID/BallotType` | `CVR::BallotStyleId` (NIST §3.5.4.1) | string | **The ballot *style* — which contests the voter was eligible to vote on.** Coding switched from `DS-NN` (2019–2023) to zero-padded numeric strings like `01`, `06`, `27` (2024+). The cleaner writes every code as text, zero-padding numeric ones (the raw 2024+ files mix the text `"04"` with the number `10`). Read it as text, e.g. `pd.read_csv(..., dtype={"_ID/BallotType": str})`, or `"01"` is read back as the number `1`. Blank only on one 2025 redacted ballot. |
| `_ID/n_sheets` | (cleaner-added) | int | Number of ballot sheets merged into this voter's row. 1 for single-sheet ballots; 2 for most 2022 and 2024 General voters; ≥2 if Boulder ever uses 3+ sheet ballots. Always 1 on redacted ballots, which cannot be matched to their other sheet. The column sums to the sheets kept (`n_sheets_after_redaction` in `_summary.csv`). |
| `_ID/voter_id` | (cleaner-added) | string | The ``ImprintedId`` of the lowest-RecordId sheet in this voter's merge group; `redacted-NNNNN` (numbered in the County's file order) for a redacted ballot. Unique within an election. Stable identifier for joining cluster labels or other per-voter analyses back to the wide CSV. |
| `_ID/redacted` | (cleaner-added) | bool | `True` for a single ballot whose identifiers the County blanked for privacy (marks intact). See [`methodology.md` § Redaction](methodology.md#redaction) for the conventions, the limits of these rows (2023's are mayoral-RCV-only partial ballots) and the re-identification caveat. |

## Ballot-choice columns

Format: ``<contest name>::<choice name>``.

* **Single-choice** / **multi-choice** contests: one column per candidate or Yes/No.
* **Ranked-choice (RCV)** contests (NIST §3.4.3): one column per (candidate × rank) pair, with rank as a `(N)` suffix on the candidate name — e.g. `Aaron Brockett(1)`, `Aaron Brockett(2)` for rank 1 and rank 2. The 2023 Boulder Coordinated mayoral race is the only RCV contest currently in this archive.

### Cell values

| Value | Meaning (NIST SP 1500-103) |
| --- | --- |
| `1` | `SelectionPosition::HasIndication = yes` (§3.4.2) — scanner detected a mark |
| `0` | Bubble was on the ballot for this style and was not marked |
| (empty / `NaN`) | Contest was not on the voter's ballot style |

Cells are written as integers (`1`/`0`, nullable `Int8` in pandas), never `1.0`/`0.0`. Any other value fails `scripts.schema.validate_contest_columns`.

**Nuance.** What the CSV stores as `1` is `HasIndication`, not `IsAllocable` (whether the mark counts under contest rules). The Dominion interpreted-snapshot collapses both, so overvotes are encoded as `1`. Analyses sensitive to invalidated marks need either the *original* or the *modified* (post-adjudication) snapshot, neither of which Boulder publishes in the redacted archive.

The `NaN`-vs-`0` distinction matters for undervote analysis: an *undervote* is `0` (eligible, left blank), vs. *not eligible* (`NaN`). The clustering pipeline collapses `NaN → 0` for embedding; analyses where the distinction matters should preserve it from the wide CSV.
