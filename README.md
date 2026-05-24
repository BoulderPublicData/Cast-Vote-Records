# Boulder County Cast Vote Records, 2019–2025

A liberated, documented, reproducible archive of ballot-level Cast Vote Records (CVRs) from Boulder County, Colorado — every election from the 2019 Coordinated through the 2025 Coordinated. The wide-format CSVs in `data/processed/` are ready for pandas, R, or any tool that reads CSVs; the source XLSX files in `data/original/` are the immutable originals released by the Boulder County Clerk or obtained via Colorado Open Records Act disclosure.

The project follows the [data-liberation](https://github.com/brianckeegan/data-liberation-skill) convention pragmatically — `scripts/` package, `data/{original,processed,audit,lookups}/`, SHA-256 manifest, per-extract provenance sidecar, pandera-validated schema, Markdown audit report. Architecture, design decisions, and contribution guidelines live in [`AGENTS.md`](AGENTS.md).

## What's in here

Nine original CVR files (seven elections plus a CORA-disclosed 2023 alongside the public version, and the empty-but-archived 2024 Primary) and seven processed countywide per-voter wide-format CSVs. **Each row is one voter** (multi-sheet ballots merged); the previous per-ballot-sheet outputs over-counted voters by the average sheet count (≈ 2× for 2024G).

| Election | Provenance | Raw sheets | Voters (post-merge) | Sheets-per-voter |
| --- | --- | ---: | ---: | --- |
| [2019 Coordinated](data/processed/2019-Coordinated-county-wide-by-voter.csv) | CORA | 115,056 | 115,056 | single-sheet |
| [2020 General](data/processed/2020-General-county-wide-by-voter.csv) | CORA | 205,796 | 205,796 | single-sheet |
| [2021 Coordinated](data/processed/2021-Coordinated-county-wide-by-voter.csv) | CORA | 108,363 | 108,363 | single-sheet |
| [2022 General](data/processed/2022-General-county-wide-by-voter.csv) | CORA | 320,542 | **163,043** | **two-sheet** for nearly every BallotType |
| [2023 Coordinated](data/processed/2023-Coordinated-county-wide-by-voter.csv) | [public](https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx) | 118,669 | 118,669 | single-sheet |
| [2024 Primary](data/processed/2024-Primary-county-wide-by-voter.csv) | [public](https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx) | 64,775 | 64,775 | single-sheet; no City of Boulder municipal contests |
| [2024 General](data/processed/2024-General-county-wide-by-voter.csv) | [public](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx) | 384,384 | **193,238** | **two-sheet** for every BallotType |
| [2025 Coordinated](data/processed/2025-Coordinated-county-wide-by-voter.csv) | [public](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx) | 120,529 | 120,529 | single-sheet |

Exact per-voter counts (including the sheet-count distribution per election) are pinned in [`data/processed/_summary.csv`](data/processed/_summary.csv) and the latest [`data/audit/summary.md`](data/audit/summary.md).

Each row in a processed CSV is one **voter** — the merger of every ballot sheet they returned (per [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103) and the merge rules in [`docs/methodology.md`](docs/methodology.md)). A sample of the 2023 Coordinated:

| `_ID/CvrNumber` | `_ID/TabulatorNum` | `_ID/BallotType` | `City of Boulder Mayoral Candidates …::Aaron Brockett(1)` | `City of Boulder Ballot Issue 2A …::Yes` |
| --- | --- | --- | ---: | ---: |
| 1 | 108 | DS-01 | 1 | 1 |
| 2 | 108 | DS-01 | 0 | 0 |
| 3 | 108 | DS-01 | 0 | NaN |
| 4 | 108 | DS-01 | 0 | 1 |
| 5 | 108 | DS-01 | 1 | 1 |

Cell values: `1` = the scanner detected a mark in the bubble; `0` = the bubble was on the ballot for this style and was not marked; missing = the contest was not on this voter's ballot style. The full data dictionary lives in [`docs/data-dictionary.md`](docs/data-dictionary.md); pandas / R / SQL slicing recipes are in [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md).

## Movement context

Boulder County publishes its CVRs because Colorado statute requires risk-limiting audits of every machine-tabulated election. [C.R.S. § 1-7-515](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html) was authorized by the General Assembly in 2009; the [2017 Coordinated Election](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits) was the first statewide RLA — the first such audit anywhere in the United States. The Colorado Department of State's [`cdos-rla/colorado-rla`](https://github.com/cdos-rla/colorado-rla) software ingests these same Dominion XLSX exports as audit input. Civic-data tradition: a public dataset that exists *because* an open-government law required it.

## Load

### pandas

```python
import pandas as pd
df = pd.read_csv("data/processed/2023-Coordinated-county-wide-by-voter.csv",
                 low_memory=False)
# Filter to City of Boulder voters: any contest column that names the city is non-null
city_cols = [c for c in df.columns if "City of Boulder" in c]
city = df[df[city_cols].notna().any(axis=1)]
```

### R / tidyverse

```r
library(readr); library(dplyr)
df <- read_csv("data/processed/2023-Coordinated-county-wide-by-voter.csv",
               show_col_types = FALSE)
city_cols <- grep("City of Boulder", names(df), value = TRUE)
city <- df |> filter(if_any(all_of(city_cols), \(x) !is.na(x)))
```

### DuckDB

```sql
SELECT * FROM read_csv_auto('data/processed/2023-Coordinated-county-wide-by-voter.csv') LIMIT 5;
```

More recipes — wide→long pivots, cross-election pools, undervote-vs-ineligible — in [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md).

## Provenance and refresh

Every file in `data/original/` is hashed in [`data/original/manifest.json`](data/original/manifest.json) with a SHA-256, byte count, and mtime. [`data/processed/provenance.csv`](data/processed/provenance.csv) joins each processed CSV back to its source xlsx (URL, hash, retrieval time). The audit report in [`data/audit/summary.md`](data/audit/summary.md) is regenerated on every `python -m scripts.audit` run.

The Boulder County Clerk publishes a new CVR within about two months of every election. To pull the latest:

```bash
pip install -e ".[analysis]"
python -m scripts.pipeline        # fetch → clean → audit
```

To opt into scheduled refresh PRs via GitHub Actions, rename [`.github/workflows/refresh.yml.disabled`](.github/workflows/refresh.yml.disabled) to `refresh.yml`.

## Quickstart for analysts

```bash
git clone https://github.com/BoulderPublicData/Cast-Vote-Records
cd Cast-Vote-Records
git lfs pull                            # fetch the xlsx + processed CSVs
pip install -e ".[analysis]"
jupyter notebook clusters.ipynb         # twin-path UMAP + HDBSCAN small-multiples
```

The analysis notebook ([`clusters.ipynb`](clusters.ipynb)) runs the McInnes two-pass UMAP + HDBSCAN pipeline on every processed CSV and renders a small-multiples comparison across elections. See [`AGENTS.md`](AGENTS.md) for the methodological rationale.

## Citation

```bibtex
@misc{boulder_county_cvr,
  author = {Keegan, Brian C.},
  title  = {Boulder County Cast Vote Records, 2019--2025},
  year   = {2026},
  url    = {https://github.com/BoulderPublicData/Cast-Vote-Records},
  note   = {Compiled from publicly posted and CORA-disclosed Dominion CVR exports}
}
```

## License

* **Code** (pipeline, tests, notebook, docs prose): [MIT](LICENSE).
* **Data** (xlsx originals + processed CSVs): public-record release by the Boulder County Clerk and Recorder; redistributed here under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) with attribution to the County.
