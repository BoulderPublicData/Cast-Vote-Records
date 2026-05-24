# Methodology

How the wide CSVs in ``data/processed/`` are derived from the redacted xlsx files in ``data/original/``.

## Sources

Boulder County publishes redacted Cast Vote Records on `assets.bouldercounty.gov` as Dominion XLSX exports. The 2023 Coordinated through 2025 Coordinated CVRs are posted on the County's by-year pages. The 2019–2022 CVRs are not publicly posted; they were obtained via Colorado Open Records Act disclosure and are archived in this repository under ``data/original/``.

The source registry is in [`../scripts/sources.py`](../scripts/sources.py). `python -m scripts.fetch` downloads any artifact with a public URL and writes a SHA-256 manifest to ``data/original/manifest.json``.

## Pipeline

```
data/original/*.xlsx
    └── scripts.loader.load_raw_cvr
        ├── reconstruct the 4-row Dominion header into a MultiIndex DataFrame
        ├── ID columns → ("_ID", label)
        └── contest columns → (contest, candidate)
    └── scripts.cleaner.clean_countywide
        ├── drop privacy-aggregated rows
        │   ├── sentinel-string CvrNumber (2023+)
        │   ├── NaN CvrNumber (2019–2022)
        │   └── NaN TabulatorNum (2021 per-style summary rows)
        ├── combine_multisheet: merge consecutive ballot sheets into voters
        │   ├── per BallotType, identify distinct contest-fill fingerprints
        │   ├── assign sheet order empirically (which fingerprint appears
        │   │   at lowest RecordId in each (Tab, Batch) group)
        │   ├── walk (Tab, Batch, RecordId), merge each (sheet K, sheet K+1)
        │   │   pair within the same BallotType + CountingGroup
        │   └── add _ID/n_sheets + _ID/voter_id bookkeeping
        ├── drop all-NaN contest columns
        ├── integrity checks
        └── flatten columns to "_ID/<label>" + "<contest>::<choice>"
    └── data/processed/<election>-county-wide-by-voter.csv
```

The orchestrator is `scripts.clean.clean`. The CLI driver is `python -m scripts.pipeline`. Jurisdiction filtering (City of Boulder, Longmont, etc.) is done downstream in the analysis layer — see `scripts.cleaner.detect_city_ballot_types` for the helper.

## Multi-sheet merge

Dominion CVRs export one row per ballot **sheet**, not per voter. Boulder's 2024 General, for example, was a two-sheet ballot — every City of Boulder voter contributed two rows to the raw CVR (sheet 1 with the federal/state/judicial contests; sheet 2 with the city ballot questions and state propositions). Treating each row as one voter therefore over-counts voters by the average sheet-count, roughly 2× for 2024G.

The cleaner identifies multi-sheet ballots by looking at which contest columns are non-null on each row. For each `BallotType`, sheet 1 always has the same set of contests filled and sheet 2 has a different (disjoint) set — so two distinct contest-fill fingerprints per BallotType signals a 2-sheet ballot. The sheet order is determined empirically: for each `(Tab, Batch)` group, the fingerprint that appears first by RecordId is "sheet 1." A sanity check warns when the empirical order disagrees with the heuristic that sheet 1 usually has more non-null contests.

The merger then walks rows in scanner order (`Tab, Batch, RecordId`) and merges each consecutive `(sheet K, sheet K+1)` pair within the same `BallotType` + `CountingGroup` into one voter. Single-sheet voters (where only one of the two sheets was returned, or the ballot style is genuinely single-sheet) remain standalone. Edge cases the merger correctly handles: two adjacent sheet-1 rows from different single-sheet voters; a voter's sheet 2 followed by a different voter's sheet 1; BallotType or batch boundary breaks; ballot styles where 3+ fingerprints are detected (warn and treat each as a single-sheet voter).

The bookkeeping columns `_ID/n_sheets` and `_ID/voter_id` carry the merge metadata.

## City of Boulder filtering (downstream)

The pipeline no longer filters by jurisdiction — every ballot in the county is processed. To restrict to City of Boulder voters in the analysis layer, the notebook `clusters.ipynb` filters by checking whether any contest column whose name contains `"City of Boulder"` is non-null for that voter. The helper `scripts.cleaner.detect_city_ballot_types` is still available for the inverse operation (ballot-style → membership) if needed.

The County's ballot-style coding has drifted over time. In 2023, City of Boulder ballots use the code `DS-01`. In 2024 the coding switched to zero-padded numeric strings (`01`, `06`, `27`). The set of "city" ballot styles also changes by year. Filtering by contest content (rather than by ballot-style code) sidesteps the drift.

## Privacy aggregation

Three conventions appear in Boulder's redacted exports:

1. **2023+** — sentinel string in `CvrNumber` (`"RCV Redacted & Randomly Sorted"` or `"Redacted & Aggregated"`).
2. **2019–2022** — `NaN` in `CvrNumber` for one aggregated row per ballot style.
3. **2021 specifically** — additional per-ballot-style summary rows where `TabulatorNum` is `NaN` and the ballot-style code is stuffed into `CvrNumber`.

The cleaner drops all three.

## NIST CDF mapping

Dominion's XLSX columns map cleanly to the NIST Common Data Format (SP 1500-103) attributes. The mapping is in [`data-dictionary.md`](data-dictionary.md). The cell values store the NIST `SelectionPosition::HasIndication` flag (§3.4.2) — distinct from `IsAllocable` (the contest-rule-based countability decision).

## Validation

* **Pandera ID-block schema.** `scripts.schema.validate_id_block` validates the ID columns at the pipeline boundary.
* **Contest-value check.** `scripts.schema.validate_contest_columns` asserts that every contest column holds only NaN / 0 / 1.
* **Integrity assertions.** `clean_city_cvr` asserts required ID columns and that every retained ballot's `BallotType` is in the detected city-ballot-styles set.
* **Audit report.** `python -m scripts.audit` writes a Markdown report of per-election shape, dtype, null rate, and cardinality to ``data/audit/summary.md`` and an auto-generated column profile to ``docs/variables.md``.
* **Reconcile.** `python -m scripts.reconcile` independently recounts the raw rows in each xlsx and compares to the pipeline's `n_raw_rows`. Mismatches fail CI.

## Reproducibility

Anyone can clone the repository, run `git lfs pull`, and regenerate every wide CSV with `python -m scripts.pipeline`. The output is deterministic given the same inputs.

## Limitations

See [`../AGENTS.md`](../AGENTS.md).
