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
    └── scripts.cleaner.clean_city_cvr
        ├── drop privacy-aggregated rows
        │   ├── sentinel-string CvrNumber (2023+)
        │   ├── NaN CvrNumber (2019–2022)
        │   └── NaN TabulatorNum (2021 per-style summary rows)
        ├── auto-detect city ballot styles (min_ballots=5 threshold)
        ├── filter to those ballot styles
        ├── drop all-NaN contest columns
        ├── integrity checks
        └── flatten columns to "_ID/<label>" + "<contest>::<choice>"
    └── data/processed/<election>-city-of-boulder-wide.csv
```

The orchestrator is `scripts.clean.clean`. The CLI driver is `python -m scripts.pipeline`.

## City of Boulder detection

A ballot style is "City of Boulder" if more than 5 ballots of that style have a non-null value in any contest column whose name contains the substring "City of Boulder". The threshold defends against privacy-aggregated rows that survive the redaction filter.

Why auto-detect rather than hardcode? Because the County's ballot-style coding has drifted over time. In 2023, City of Boulder ballots use the code `DS-01`. In 2024 the coding switched to zero-padded numeric strings (`01`, `06`, `27`). The set of "city" ballot styles also changes by year (one or two in 2019–2021; three in the 2022 midterm). The auto-detector handles every observed pattern without per-year hardcoding.

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
