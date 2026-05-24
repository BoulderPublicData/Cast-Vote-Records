# Data dictionary — City of Boulder wide CVRs

Per-column reference for ``data/processed/<election>-city-of-boulder-wide.csv``. Each row is one **ballot sheet** as defined by [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103); each column is either an identifier (prefix ``_ID/``) or a ballot-choice column (``<contest>::<candidate>``).

The auto-generated mechanical complement to this file is [`variables.md`](variables.md), regenerated on every `python -m scripts.audit` run.

## ID columns

| Column | NIST CDF attribute | Type | Description |
| --- | --- | --- | --- |
| `_ID/CvrNumber` | `CVR::UniqueId` ([NIST §3.5.1](https://doi.org/10.6028/NIST.SP.1500-103)) | string-as-int | Per-CVR unique identifier within the report. Privacy-aggregated rows are dropped upstream — every value present in a processed CSV is a real ballot. |
| `_ID/TabulatorNum` | `CVR::CreatingDevice.SerialNumber` (NIST §3.5.6) | string-as-int | The scanner that captured this ballot. |
| `_ID/BatchId` | `CVRSnapshot::BatchId` (NIST §3.5.5) | string-as-int | Batch identifier. |
| `_ID/RecordId` | `CVRSnapshot::BatchSequenceId` (NIST §3.5.5) | string-as-int | Position within the batch. |
| `_ID/ImprintedId` | `CVR::BallotAuditId` (NIST §3.5.4) | string | Composite `TabulatorNum-BatchId-RecordId`. The Dominion scanner can imprint this on the paper ballot, enabling ballot-level comparison auditing (Colorado RLA). |
| `_ID/CountingGroup` | Dominion-specific | string | `Regular` / `Mail` / `Provisional`. Present in 2019, 2020, 2022, 2024+; absent in 2021, 2023. |
| `_ID/PrecinctPortion` | (cf. NIST `BallotStyleUnit` §3.5.6) | string | Political-geography portion of the precinct served by this ballot style. Present in 2019 and 2021. |
| `_ID/BallotType` | `CVR::BallotStyleId` (NIST §3.5.4.1) | string | **The ballot *style* — which contests the voter was eligible to vote on.** Coding switched from `DS-NN` (2019–2023) to zero-padded numeric strings like `01`, `06`, `27` (2024+). |

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

**Nuance.** What the CSV stores as `1` is `HasIndication`, not `IsAllocable` (whether the mark counts under contest rules). The Dominion interpreted-snapshot collapses both, so overvotes are encoded as `1`. Analyses sensitive to invalidated marks need either the *original* or the *modified* (post-adjudication) snapshot, neither of which Boulder publishes in the redacted archive.

The `NaN`-vs-`0` distinction matters for undervote analysis: an *undervote* is `0` (eligible, left blank), vs. *not eligible* (`NaN`). The clustering pipeline collapses `NaN → 0` for embedding; analyses where the distinction matters should preserve it from the wide CSV.
