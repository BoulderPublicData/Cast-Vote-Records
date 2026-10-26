# Boulder County Cast Vote Records, 2019–2025

A liberated, documented, reproducible archive of ballot-level Cast Vote Records (CVRs) from Boulder County, Colorado. It covers the **general and coordinated elections from the 2019 Coordinated through the 2025 Coordinated, plus the 2024 June Primary**. Earlier primaries (2020, 2022) are not included. The wide-format CSVs in `data/processed/cast-vote-records/` (one per election, named by the same lowercase `{year}-{type}` key as [Election-Results](https://github.com/BoulderPublicData/Election-Results), e.g. `2024-general`) are ready for pandas, R, or any tool that reads CSVs. The source XLSX files in `data/original/` are the unmodified originals, released by the Boulder County Clerk and Recorder or obtained through Colorado Open Records Act (CORA) requests.

Architecture, design decisions, and contribution guidelines live in [`AGENTS.md`](AGENTS.md).

## What is a Cast Vote Record?

When a paper ballot goes through the County's scanner, the voting system records which bubbles it detected. That electronic record, for one ballot sheet, is a **Cast Vote Record**. A CVR file lists every ballot in an election, one row per sheet, with a 1 or 0 for every choice in every contest on that ballot.

A **Statement of Votes** (SoV) is the official results report: vote totals per contest, candidate and precinct. It tells you *how many* people voted for each choice. A CVR tells you *which choices were made together on the same ballot*: how many voters who chose X also chose Y, how often people skip down-ballot races, how ranked-choice rankings combine. The SoV is the official count. Treat the CVRs as a research dataset that should, and here does, add up to it (see [Accuracy checks](#accuracy-checks)).

## What's in here

Eight processed per-voter CSVs, one per election, built from nine original files (the ninth is a CORA copy of the 2023 file; see below). **Each row is one voter**: when a ballot had two sheets, both rows of the original are merged into one.

| Per-voter CSV | Source | Rows in original | Aggregate rows dropped | Ballot sheets kept | Voters | Redacted ballots kept | Sheets per ballot |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [2019 Coordinated per-voter CSV](data/processed/cast-vote-records/2019-coordinated-county-wide-by-voter.csv) | CORA | 115,068 | 12 | 115,056 | 115,056 | 0 | one |
| [2020 General per-voter CSV](data/processed/cast-vote-records/2020-general-county-wide-by-voter.csv) | CORA | 205,845 | 49 | 205,796 | 205,796 | 0 | one |
| [2021 Coordinated per-voter CSV](data/processed/cast-vote-records/2021-coordinated-county-wide-by-voter.csv) | CORA | 108,381 | 18 | 108,363 | 108,363 | 0 | one |
| [2022 General per-voter CSV](data/processed/cast-vote-records/2022-general-county-wide-by-voter.csv) | CORA | 320,580 | 37 | 320,543 | **162,714** | 1 | **two** for nearly every style |
| [2023 Coordinated per-voter CSV](data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv) | [2023 County download](https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx) | 118,787 | 18 | 118,769 | 118,769 | 100 | one |
| [2024 Primary per-voter CSV](data/processed/cast-vote-records/2024-primary-county-wide-by-voter.csv) | [2024 Primary County download](https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx) | 65,790 | 3 | 65,787 | 65,787 | 1,012 | one; no City of Boulder contests |
| [2024 General per-voter CSV](data/processed/cast-vote-records/2024-general-county-wide-by-voter.csv) | [2024 General County download](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx) | 384,444 | 60 | 384,384 | **193,005** | 0 | **two** for every style |
| [2025 Coordinated per-voter CSV](data/processed/cast-vote-records/2025-coordinated-county-wide-by-voter.csv) | [2025 County download](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx) | 121,540 | 3 | 121,537 | 121,537 | 1,008 | one |

How to read the columns:

* **Rows in original**: rows in the County's spreadsheet, below its header.
* **Aggregate rows dropped**: rows that sum several ballots for privacy (see below).
* **Ballot sheets kept**: the rows that remain after dropping aggregates.
* **Voters**: sheets merged per voter.

Every file covers the whole county; filter to a jurisdiction yourself (recipe below). The 2024 Primary is a partisan state primary with no City of Boulder municipal contests. Its countywide rows are all retained.

Exact counts, including the sheet-count distribution and merge diagnostics, are in [`data/processed/cast-vote-records/_summary.csv`](data/processed/cast-vote-records/_summary.csv) and the latest [audit summary](data/audit/summary.md). `data/original/2023-CVR.xlsx` is the CORA copy of the 2023 file. It holds the same ballots in a different row order, so it is archived but not processed ([details](docs/methodology.md#sources)).

A sample of the 2023 Coordinated: four City of Boulder voters and one redacted ballot (most contest columns omitted):

| `_ID/CvrNumber` | `_ID/TabulatorNum` | `_ID/BallotType` | `_ID/n_sheets` | `_ID/voter_id` | `_ID/redacted` | `City of Boulder Mayoral Candidates (…)::Aaron Brockett(1)` | `City of Boulder Ballot Issue 2A (…)::Yes/For` |
| --- | ---: | --- | ---: | --- | --- | ---: | ---: |
| 1492 | 101 | DS-01 | 1 | 101-4-1 | False | 0 | 1 |
| 1573 | 101 | DS-01 | 1 | 101-4-2 | False | 0 | 1 |
| 1516 | 101 | DS-01 | 1 | 101-4-3 | False | 0 | 1 |
| 1592 | 101 | DS-01 | 1 | 101-4-4 | False | 0 | 1 |
| RCV Redacted & Randomly Sorted | (blank) | DS-01 | 1 | redacted-00001 | True | 0 | (blank) |

Cell values: `1` = the scanner detected a mark in the bubble; `0` = the bubble was on the ballot for this style and was not marked; blank = the contest was not on this voter's ballot style. Read `_ID/BallotType` as text (`dtype={"_ID/BallotType": str}`) or `"01"` becomes `1`. The full data dictionary is in [`docs/data-dictionary.md`](docs/data-dictionary.md); pandas, R and SQL slicing recipes are in [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md).

### Derived files (cluster analysis)

[`clusters.ipynb`](clusters.ipynb) groups City of Boulder voters with similar ballots (UMAP + HDBSCAN) and writes:

* `data/processed/clusters/<election>-ballots-with-clusters.csv`: the City of Boulder voters of that election, with a `cluster` column (`-1` = noise, i.e. not in any cluster) and the 2-D plot coordinates `umap_x`, `umap_y`. Join to the per-voter CSV on `_ID/voter_id`.
* `data/processed/clusters/<election>-cluster-profiles.csv`: one row per cluster; `n_ballots` (the number of voters in the cluster), then the share of the cluster's eligible voters who marked each choice.
* `data/processed/clusters/city-of-boulder-cluster-smallmultiples.png`: the figure below.
* `data/processed/clusters/provenance.csv`: for every derived file, the SHA-256 of the input CSV and of the output, the random seed, the parameters, and the package versions.

The 2024 Primary has no City of Boulder contests, so it has no cluster files. Redacted ballots are left out of the clustering.

![Eight scatter-plot panels, one per Boulder County election from 2019 to 2025, each showing City of Boulder voters projected to two dimensions with UMAP. Points are colored by HDBSCAN cluster, with each cluster's id printed at its center and noise shown as hollow rings. The 2024 Primary panel is empty because that election had no City of Boulder contests.](data/processed/clusters/city-of-boulder-cluster-smallmultiples.png)

*Figure: City of Boulder voter clusters by election. Colors mark each election's eight largest clusters in size order (blue = largest); smaller clusters are black; hollow rings are noise. Numbers are cluster ids, matching the `cluster` column. Positions are only meaningful within a panel.*

## Privacy and redaction

To protect ballot secrecy, the County alters some rows before publishing a CVR:

* **Redacted single ballots.** For ballots in small ballot styles, the County blanks the identifiers that locate a ballot in the scanning sequence (`TabulatorNum`, `BatchId`, `RecordId`, `ImprintedId`). It writes `Redacted` or `RCV Redacted & Randomly Sorted` in `CvrNumber`, but leaves the marks. These rows are **kept** and flagged `_ID/redacted = True`: 2,121 across all elections. In 2023, the 100 redacted rows hold only the mayoral ranked-choice contest.
* **Aggregate rows.** For the smallest groups, the County sums several ballots into one row. Such a row is not one voter, so it is **dropped**: 200 rows across all elections. Their marks are still in the official results.

This repository republishes only what the County released. It never re-creates a blanked identifier and never restores the scan order of redacted ballots. **Re-identification caveat:** a ballot style used by only a few voters is, by definition, a small group. Combining `_ID/BallotType`, `_ID/PrecinctPortion`, a voter's full pattern of choices, and outside knowledge could narrow a row to a handful of people, and `_ID/ImprintedId` (also `_ID/voter_id`) is the number printed on the paper ballot. **Do not use this data to try to identify voters.** Details are in [`docs/methodology.md` § Redaction](docs/methodology.md#redaction).

## Glossary

* **Cast Vote Record (CVR)**: the voting system's record of the marks it read on one ballot sheet.
* **Sheet (card)**: one physical piece of paper. Long ballots use two sheets (the 2022 and 2024 Generals), and Dominion exports one row per sheet. This dataset merges them into one row per voter (`_ID/n_sheets`).
* **Ballot style** (`_ID/BallotType`): which set of contests a ballot contains, determined by where the voter lives (city, school district, special districts). Dominion calls it "BallotType"; standards documents call it ballot style.
* **Voter row**: one row of a processed CSV, i.e. all the sheets of one returned ballot.
* **RCV (ranked-choice voting)**: voters rank candidates instead of choosing one. Each candidate × rank is its own column, e.g. `Aaron Brockett(2)` = Brockett ranked second. The 2023 City of Boulder mayoral race is the only RCV contest here.
* **Undervote**: a voter left a contest on their ballot blank, or marked fewer choices than allowed. All of that contest's cells are `0`, and that is different from blank cells (contest not on the ballot).
* **Overvote**: more choices marked than allowed (e.g. two candidates in a vote-for-one race). In these exports **no contest ever has more marks than its limit**, so an overvoted contest appears to have been recorded as all `0`s. It cannot be told apart from an undervote here.
* **Redacted ballot / aggregate row**: see [Privacy and redaction](#privacy-and-redaction).
* **Statement of Votes (SoV)**: the official per-precinct results report.
* **CORA**: the Colorado Open Records Act, the public-records law under which the 2019–2022 files were obtained.

## Movement context

Boulder County publishes its CVRs because Colorado statute requires risk-limiting audits (RLAs) of every machine-tabulated election. The General Assembly authorized RLAs in 2009 under [C.R.S. § 1-7-515 (Secretary of State RLA FAQ)](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html). The [2017 Coordinated Election (NPR coverage)](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits) was the first statewide RLA anywhere in the United States. The Colorado Department of State's [`cdos-rla/colorado-rla` audit software](https://github.com/cdos-rla/colorado-rla) ingests these same Dominion XLSX exports. In the civic-data tradition, this is a public dataset that exists *because* an open-government law required it.

## Load

### pandas

```python
import pandas as pd
df = pd.read_csv("data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv",
                 dtype={"_ID/BallotType": str}, low_memory=False)
# Filter to City of Boulder voters: any contest column that names the city is non-blank
city_cols = [c for c in df.columns if "City of Boulder" in c]
city = df[df[city_cols].notna().any(axis=1)]
```

### R / tidyverse

```r
library(readr); library(dplyr)
df <- read_csv("data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv",
               col_types = cols(`_ID/BallotType` = col_character()),
               show_col_types = FALSE)
city_cols <- grep("City of Boulder", names(df), value = TRUE)
city <- df |> filter(if_any(all_of(city_cols), \(x) !is.na(x)))
```

### DuckDB

```sql
SELECT * FROM read_csv('data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv',
                       types = {'_ID/BallotType': 'VARCHAR'}) LIMIT 5;
```

More recipes, including wide→long pivots, cross-election pools, and undervote-vs-ineligible, are in [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md).

## Accuracy checks

`python -m scripts.reconcile` re-reads every original with an independent parser and checks the published files against it. It fails if any of these differ: row counts, aggregate counts, Σ `n_sheets`, unique `voter_id`, or the mark total of every contest-choice column. With `--sov` it also compares against the official Boulder County Statement of Votes, using the CSVs in [BoulderPublicData/Election-Results](https://github.com/BoulderPublicData/Election-Results). For 2019, 2020, 2021, 2022 and 2025, the marks in these CSVs plus the marks in the dropped aggregate rows equal the official totals exactly, for every matched contest. The latest report is [`data/audit/reconcile.md`](data/audit/reconcile.md).

## Provenance and refresh

Every file in `data/original/` is hashed in [`data/original/manifest.json`](data/original/manifest.json) with a SHA-256 and byte count, plus when it was retrieved or obtained and when the County saved the workbook. `fetch` verifies the hashes on every run. [`data/processed/cast-vote-records/provenance.csv`](data/processed/cast-vote-records/provenance.csv) joins each processed CSV back to its source file (URL, hash, dates). The audit report in [`data/audit/summary.md`](data/audit/summary.md) is regenerated on every `python -m scripts.audit` run.

The Boulder County Clerk publishes a new CVR within about two months of every election. To pull the latest:

```bash
git lfs pull                       # originals + processed CSVs are Git LFS objects
uv sync                            # core pipeline (uv.lock pins every version)
uv run python -m scripts.pipeline  # fetch (verify hashes) → clean → audit
uv run python -m scripts.pipeline reconcile
```

To opt into scheduled refresh PRs via GitHub Actions, rename [the disabled refresh workflow](.github/workflows/refresh.yml.disabled) to `refresh.yml`.

## Quickstart for analysts

```bash
git clone https://github.com/BoulderPublicData/Cast-Vote-Records
cd Cast-Vote-Records
git lfs pull                            # fetch the xlsx + processed CSVs
uv sync --extra analysis                # or: pip install -r requirements.txt
uv run jupyter notebook clusters.ipynb  # twin-path UMAP + HDBSCAN small-multiples
```

The analysis notebook ([`clusters.ipynb`](clusters.ipynb)) runs the McInnes two-pass UMAP + HDBSCAN pipeline on every processed CSV and renders the small-multiples figure above.

## Citation

Please cite the release or commit you used. Machine-readable citation metadata is in [`CITATION.cff`](CITATION.cff); GitHub's "Cite this repository" button reads it.

```bibtex
@misc{keegan_boulder_cvr,
  author  = {Keegan, Brian C.},
  title   = {Boulder County Cast Vote Records, 2019--2025},
  year    = {2026},
  version = {0.3.0},
  url     = {https://github.com/BoulderPublicData/Cast-Vote-Records},
  note    = {Compiled from publicly posted and CORA-disclosed Dominion CVR exports by the Boulder County Clerk and Recorder. Cite the commit hash you used.}
}
```

## License

* **Code** (pipeline, tests, notebook, docs prose): [MIT](LICENSE).
* **Data** (xlsx originals + processed CSVs): public-record release by the Boulder County Clerk and Recorder; redistributed here under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) with attribution to the County.
