# Methodology

How the wide CSVs in ``data/processed/cast-vote-records/`` are derived from the redacted xlsx files in ``data/original/``.

## Sources

Boulder County publishes redacted Cast Vote Records on `assets.bouldercounty.gov` as Dominion XLSX exports, linked from its [Elections by year](https://bouldercounty.gov/elections/by-year/) pages. The 2023 Coordinated through 2025 Coordinated CVRs come from those pages (`source_page` in `sources.py`). On 2026-10-26 each was downloaded again from its `public_url` and was byte-identical to the copy in ``data/original/``. The 2019–2022 by-year pages list no CVR; those files were obtained via Colorado Open Records Act request C000518-121923 to the Boulder County Open Records Center, released 2023-12-19 (`obtained_at`), and are archived in this repository under ``data/original/``. The County's file names were `2019_Coordinated_Election_Public_CVR.xlsx`, `2020_General_Election_Public_CVR.xlsx`, `2021_Coordinated_Election_Public_CVR.xlsx` and `2022_General_Election_Public_CVR.xlsx`. The request also asked for the 2018 General; the County released a 2018 Primary CSV (`2018_Primary_Election_Public_CVR.csv`) instead, which is not in this repository.

The 2024 by-year page also links two CVRs this pipeline does not process: the post-recount 2024 General CVR (see the note on `2024-general` in `sources.py`) and the March 2024 Presidential Primary CVR (`CVR-2024PPE-Final.xlsx`).

The source registry is in [`../scripts/sources.py`](../scripts/sources.py). `python -m scripts.fetch` downloads any artifact with a public URL and **verifies** every file in ``data/original/`` against the SHA-256 manifest ``data/original/manifest.json``. If a file is a Git LFS pointer (a fresh clone without `git lfs pull`), fetch, clean and reconcile stop with "run `git lfs pull` first". A hash mismatch fails the run instead of silently overwriting the manifest; `--update-manifest` accepts a deliberate change.

The manifest records, per file: `sha256` and `size`; `retrieved_at` (when the file was downloaded from its `public_url`); `source_last_modified` (the County server's `Last-Modified` header at that time, i.e. when the County posted this version); `obtained_at` (for CORA files, the release date, entered by hand in `sources.py`); `first_committed_at` (when the file entered this repository, an upper bound on when it was obtained; 2026-05-23 for every current file); and `xlsx_created` / `xlsx_modified` from the workbook itself, i.e. when the County produced the export. File modification times are never used, because a checkout resets them. For the four public files, `retrieved_at` is the 2026-10-26 re-download that matched the committed bytes; the original 2026-05 download time was never recorded. For the CORA files, `obtained_at` is the release date in the County's response. `data/processed/cast-vote-records/provenance.csv` carries `public_url`, `source_page`, `retrieved_at`, `source_last_modified`, `obtained_at`, `first_committed_at` and the workbook's save time for each election.

`data/original/2023-CVR.xlsx` is the CORA copy of the 2023 Coordinated CVR. It holds the same 118,787 rows and the same ballots as the public `2023-Coordinated-CVR.xlsx`: once `CvrNumber` (a row sequence number) is ignored, the two files contain an identical multiset of rows, in a different order. The workbook was re-saved 2023-12-01, against 2023-11-28 for the public copy. It is archived for provenance (`ARCHIVED_ORIGINALS` in `sources.py`) but not processed, because it would duplicate the public file.

## Pipeline

```
data/original/*.xlsx
    └── scripts.fetch: verify SHA-256 against manifest.json (stop on LFS pointers)
    └── scripts.loader.load_raw_cvr
        ├── reconstruct the 4-row Dominion header into a MultiIndex DataFrame
        ├── repair mojibake in contest / candidate names (ftfy.fix_encoding)
        ├── ID columns → ("_ID", label)
        └── contest columns → (contest, candidate)
    └── scripts.cleaner.clean_countywide
        ├── normalize BallotType to text ("4", 4, 4.0 → "04"; "DS-01" kept)
        ├── coerce contest cells to numbers; fail on non-blank text
        ├── split_redacted: rows whose CvrNumber/TabulatorNum is not a number
        │   ├── aggregate (label says Consolidated/Aggregated, or a cell > 1)
        │   │   → dropped, counted in n_aggregate_rows_dropped
        │   └── single ballot with blanked IDs → kept, _ID/redacted = True
        ├── combine_multisheet (ordinary sheets only)
        │   ├── per BallotType, identify distinct contest-fill fingerprints
        │   ├── assign sheet order empirically (which fingerprint appears
        │   │   at lowest RecordId in each (Tab, Batch) group)
        │   ├── pass 1: walk (Tab, Batch, RecordId), merge each forward
        │   │   (sheet K, sheet K+1, ...) run within BallotType + CountingGroup
        │   ├── pass 2: merge adjacent incomplete runs with complementary
        │   │   sheets (sheet 2 scanned before sheet 1)
        │   └── add _ID/n_sheets + _ID/voter_id bookkeeping
        ├── append kept redacted ballots as one-sheet voters
        ├── drop all-blank contest columns; cast marks to nullable Int8
        ├── integrity checks (required columns; Σ n_sheets = sheets kept)
        └── flatten columns to "_ID/<label>" + "<contest>::<choice>"
    └── scripts.schema: validate_id_block + validate_contest_columns
    └── data/processed/cast-vote-records/<election>-county-wide-by-voter.csv
```

The orchestrator is `scripts.clean.clean`. The CLI driver is `python -m scripts.pipeline`. Jurisdiction filtering (City of Boulder, Longmont, etc.) is done downstream in the analysis layer — see `scripts.cleaner.detect_city_ballot_types` for the helper.

## Multi-sheet merge

Dominion CVRs export one row per ballot **sheet**, not per voter. Boulder's 2024 General, for example, was a two-sheet ballot — every City of Boulder voter contributed two rows to the raw CVR (sheet 1 with the federal/state/judicial contests; sheet 2 with the city ballot questions and state propositions). Treating each row as one voter therefore over-counts voters by the average sheet-count, roughly 2× for 2024G.

The cleaner identifies multi-sheet ballots by looking at which contest columns are non-null on each row. For each `BallotType`, sheet 1 always has the same set of contests filled and sheet 2 has a different (disjoint) set — so two distinct contest-fill fingerprints per BallotType signals a 2-sheet ballot. The sheet order is determined empirically: for each `(Tab, Batch)` group, the fingerprint that appears first by RecordId is "sheet 1." A sanity check warns when the empirical order disagrees with the heuristic that sheet 1 usually has more non-null contests.

The merger then walks rows in scanner order (`Tab, Batch, RecordId`) in two passes, both limited to adjacent rows (consecutive `RecordId`) with the same `BallotType`, `TabulatorNum`, `BatchId` and `CountingGroup`:

1. **Forward runs.** Each consecutive `(sheet K, sheet K+1, ...)` run becomes one voter.
2. **Complementary runs.** Adjacent runs that are still incomplete merge when their sheet sets don't overlap and together fit the style, e.g. a lone sheet 2 directly followed by a lone sheet 1. This handles ballots fed back page first: 233 voters in the 2024 General and 330 in the 2022 General were previously split into two one-sheet "voters". The forward pass runs first, so in an ambiguous run like `2, 1, 2` the ordinary `(1, 2)` pair wins and the leading sheet 2 stays alone. Either reading gives the same voter count. The number of pass-2 merges is `n_out_of_order_merges` in `_summary.csv`.

Single-sheet voters (where only one of the sheets was returned, or the ballot style is genuinely single-sheet) remain standalone. Edge cases the merger handles: two adjacent sheet-1 rows from different voters; BallotType, batch, tabulator or `RecordId`-gap boundaries; two lone sheet-2 rows (never complementary).

**Rare fingerprints.** Within a ballot style, a fingerprint held by fewer than 5% of sheets gets no sheet number, and each such sheet becomes its own one-sheet voter. `_summary.csv` reports how many (`n_rare_fingerprint_sheets`) and how many of those fill *every* contest of the style (`n_rare_fingerprint_full_ballot`), i.e. a whole ballot recorded on one row. In the 2022 General all 3,319 rare-fingerprint sheets are whole ballots, mostly from tabulators 101 and 108. They are complete voters rather than halves of a split ballot, so keeping them as one-sheet voters is correct.

**Three or more sheets.** A ballot style with three or more frequent fingerprints is merged as 3+-sheet voters (Dominion supports multi-card ballots), in any sheet order, and the cleaner logs a warning asking for a check against the ballot design. No 2019–2025 file has such a style.

The bookkeeping columns `_ID/n_sheets` and `_ID/voter_id` carry the merge metadata. `voter_id` is the `ImprintedId` of the voter's lowest-`RecordId` sheet (for a back-first voter, that is their sheet 2).

## City of Boulder filtering (downstream)

The pipeline no longer filters by jurisdiction — every ballot in the county is processed. To restrict to City of Boulder voters in the analysis layer, the notebook `clusters.ipynb` filters by checking whether any contest column whose name contains `"City of Boulder"` is non-null for that voter. The helper `scripts.cleaner.detect_city_ballot_types` is still available for the inverse operation (ballot-style → membership) if needed.

The County's ballot-style coding has drifted over time. In 2023, City of Boulder ballots use the code `DS-01`. In 2024 the coding switched to zero-padded numeric strings (`01`, `06`, `27`). The set of "city" ballot styles also changes by year. Filtering by contest content (rather than by ballot-style code) sidesteps the drift.

## Redaction

To protect ballot secrecy, the County alters some rows before publishing. A row is **redacted** when its `CvrNumber` or `TabulatorNum` is not a number. Redacted rows come in two kinds, and the cleaner treats them differently:

| Kind | How to recognize it | Treatment | Labels seen (`CvrNumber`) |
| --- | --- | --- | --- |
| **Single redacted ballot** | identifiers (`TabulatorNum`, `BatchId`, `RecordId`, `ImprintedId`) blanked; every contest cell is 0, 1 or blank | **kept**, `_ID/redacted = True`, `voter_id = redacted-NNNNN`, `n_sheets = 1` | `Redacted` (2024 Primary, 2025), `RCV Redacted & Randomly Sorted` (2023), `NaN` (2022: 1 row, 2025: 1 row) |
| **Aggregate** | several ballots summed into one row: a label containing "Consolidated" or "Aggregated", or any contest cell > 1 | **dropped** (not one ballot) | `Redacted & Aggregated` (2023), `Redacted and Aggregated - A cards` / `- B cards` / `- B cards or Property Owner Ballot` (2024 General), `Redacted and Consolidated` (2024 Primary), `Redacted and Consolidated N Ballots` (2025), `NaN` (2019–2022, one row per style), the style code e.g. `DS-01` (2021 per-style summaries) |

The full sentinel lists are `SINGLE_BALLOT_SENTINELS` and `AGGREGATE_SENTINELS` in `scripts/loader.py`. Classification uses the pattern and the cell values, not the exact list, so a new label still lands in the right bucket (and is logged as unrecognized). `_summary.csv` reports `n_redacted_kept` and `n_aggregate_rows_dropped` for every election.

Before this rule, the pipeline dropped every redacted row, which removed about 1,000 individual ballots from each of the 2024 Primary and 2025 Coordinated files, mostly in small ballot styles. For example, Joe Neguse's 2024 Democratic primary marks rise from 50,738 to 51,310 when the 1,012 single-ballot rows are kept; the three consolidated rows hold about 157 more, which stay out.

**Limits of redacted rows.**

* *They cannot be sheet-merged.* With no Tabulator/Batch/RecordId, a redacted sheet cannot be matched to the same voter's other sheet(s). In a multi-sheet ballot style, each redacted sheet stays as its own one-sheet row; `n_redacted_in_multisheet_styles` counts them (0 in every 2019–2025 file: the multi-sheet elections, 2022 and 2024 General, have no single-sheet redactions apart from the 2022 row below).
* *2023's RCV rows are partial ballots.* Each `RCV Redacted & Randomly Sorted` row holds one voter's mayoral ranking and nothing else. The same voters' other contests are summed into the dropped `Redacted & Aggregated` rows. So these 100 rows count as 100 "voters" whose other contests are blank.
* *The 2022 `NaN` row is laid out like an aggregate.* It sums to at most 1 everywhere, so it is one ballot. But, like the County's aggregate rows, it fills every contest in the county with 0 (including Erie, Superior and Longmont contests a DS-38 voter could not vote in), so its blank-vs-0 eligibility pattern is not reliable.
* *The 2025 `NaN` row has no ballot style.* It records a single Coal Creek Canyon Fire Protection District 7B vote with every identifier, including `BallotType`, blank.

**Privacy rationale and re-identification caveat.** Colorado counties redact CVRs so that no published row can be tied to a voter. Scan position (`TabulatorNum`/`BatchId`/`RecordId`/`ImprintedId`) can reveal when and where a ballot was scanned, and a ballot style used by only a handful of voters can reveal how those few people voted. The County resolves this by blanking identifiers on ballots in small styles and summing the smallest groups. This pipeline republishes only what the County released. It never re-creates a blanked identifier, never restores the scan order of redacted ballots (they are appended after the ordinary voters in the County's own file order), and numbers them with a sequence (`redacted-NNNNN`) that encodes nothing about the ballot. The County already decided these rows are safe to publish, so keeping them adds no information the public file doesn't already contain. Still, small ballot styles are small. Combining `_ID/BallotType`, `_ID/PrecinctPortion`, a voter's full pattern of marks and outside knowledge could narrow a row to a few people, and `_ID/ImprintedId` / `_ID/voter_id` on ordinary rows is the identifier printed on the paper ballot. Do not use this data to try to identify individual voters.

## NIST CDF mapping

Dominion's XLSX columns map cleanly to the NIST Common Data Format (SP 1500-103) attributes. The mapping is in [`data-dictionary.md`](data-dictionary.md). The cell values store the NIST `SelectionPosition::HasIndication` flag (§3.4.2) — distinct from `IsAllocable` (the contest-rule-based countability decision).

## Validation

* **Pandera ID-block schema.** `scripts.schema.validate_id_block` checks the ID columns at the pipeline boundary: required columns present, `BallotType` as text, `n_sheets >= 1`, unique `voter_id`, boolean `redacted`, and numeric `CvrNumber`/`TabulatorNum` plus a `BallotType` on every non-redacted row.
* **Contest-value check.** `scripts.schema.validate_contest_columns` (called by `scripts.clean` on every output) asserts that every contest cell is blank, 0 or 1. Non-blank text such as `"X"` fails instead of silently turning into a blank. The cleaner applies the same text check to the raw cells before merging.
* **Integrity assertions.** `clean_countywide` asserts the required ID columns exist and that Σ `n_sheets` equals the sheets kept after dropping aggregates.
* **Per-election isolation.** If one election fails to clean, `scripts.clean` reports it, still cleans the others, and exits non-zero.
* **Audit report.** `python -m scripts.audit` writes a Markdown report of per-election shape, null rate, the redaction/merge diagnostics and the `_summary.csv` bookkeeping to ``data/audit/summary.md``, and an auto-generated column profile to ``docs/variables.md``.
* **Reconcile.** `python -m scripts.reconcile` re-reads each original with a second parser (calamine), re-applies the redaction rule, and checks the published outputs against it: raw and aggregate row counts, processed CSV row count, unique `voter_id`, Σ `n_sheets` = sheets kept, redacted-row count, and the mark total of every contest-choice column. Any mismatch exits non-zero. `--sov DIR` adds an informational comparison with the Boulder County Statement of Votes CSVs from [Election-Results](https://github.com/BoulderPublicData/Election-Results) (`data/processed/statements-of-votes/`).

## Reproducibility

Anyone can clone the repository, run `git lfs pull` and `uv sync`, and regenerate every wide CSV with `uv run python -m scripts.pipeline`. Dependencies are pinned in `uv.lock`; `requirements.txt` is exported from it (`uv export --frozen --no-hashes --no-dev --extra analysis --extra publish -o requirements.txt`). The pipeline output is deterministic given the same inputs.

The cluster outputs are reproducible too. `clusters.ipynb` seeds both UMAP runs (`random_state=42`), recomputes every election on each run (no cross-run cache), and is executed top to bottom before commit. `data/processed/clusters/provenance.csv` records, for each derived file, the input CSV's SHA-256, the output's SHA-256, the seed and parameters, and the Python and package versions.

## Limitations

See [`../AGENTS.md`](../AGENTS.md).
