# Changelog

Per-vintage notes on the underlying CVR files and any pipeline changes required to handle them.

## Pipeline change: per-voter (not per-sheet) outputs

Originally, the pipeline emitted one row per ballot **sheet** — and Dominion CVRs really do export one row per sheet ([NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)). For multi-sheet ballots (the 2024 General used a two-sheet ballot for nearly every style), this over-counted voters by the average sheet-count, roughly 2× for 2024G.

The pipeline now merges consecutive sheets from the same voter into a single per-voter row. The output filename is `<election>-county-wide-by-voter.csv` (was `-city-of-boulder-wide.csv`). City-of-Boulder filtering moved into the analysis layer (`clusters.ipynb` filters by checking for any non-null `City of Boulder::*` column).

See `methodology.md` § Multi-sheet merge for the merging rules. The new bookkeeping columns `_ID/n_sheets` and `_ID/voter_id` carry merge metadata.

## 2025 Coordinated

* Source: [Redacted-CVR-PUBLIC.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx).
* Dominion software version 5.17.17.1.
* Ballot styles coded as zero-padded numeric strings.

## 2024 General (pre-recount)

* Source: [2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx).
* High-turnout presidential cycle; largest CVR by row count (**384,384 ballot sheets** county-wide).
* **Two-sheet ballot for every BallotType** — the multi-sheet merger collapses this to **193,238 voters** (191,146 two-sheet voters + 2,092 single-sheet voters whose other sheet was not returned or rejected). Sheet 1 carries presidential + congressional + judicial retentions + state amendments; sheet 2 carries City of Boulder ballot questions (2C/2D/2E) + state propositions.
* Partisan presidential and congressional contests include a third header row with party abbreviations (`DEM`/`REP`/`APV`/`LBR`/`GRN`).
* A post-recount CVR was published separately — would correspond to the NIST "modified" snapshot. Excluded by design.

## 2024 Primary

* Source: [2024-Boulder-County-June-Primary-Election-CVR.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx).
* Partisan state primary; no City of Boulder municipal contests; emits zero rows.

## 2023 Coordinated

* Source: [Redacted-2023Coordinated-CVR.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx).
* First publicly posted Boulder County CVR.
* Includes Boulder's first ranked-choice mayoral election: four candidates × four rounds = sixteen columns named `Aaron Brockett(1)`, etc.
* Privacy aggregation switched to sentinel strings in `CvrNumber`.
* Ballot styles still coded `DS-NN`. No `CountingGroup`.

## 2022 General (CORA)

* Obtained via Colorado Open Records Act disclosure.
* Largest pre-2024 CVR by row count (**320,542 county-wide sheets**) — but the **two-sheet ballot** halves that to **163,043 voters** (157,499 two-sheet + 5,544 single-sheet).
* Privacy-aggregated rows carry `NaN` in `CvrNumber` (one row per ballot style).
* **Initial pipeline bug**: without the NaN-CvrNumber redaction rule, those aggregate rows were each detected as "voting on a City of Boulder contest" and flipped 37 ballot styles into the "city" set — producing a falsely inflated city-ballot count of 320k. Fixed with the NaN-redaction rule plus a `min_ballots=5` threshold on city detection.
* The 2022 cleaner also logs 18 warnings for BallotTypes with a rare third contest-fill fingerprint (~3,300 sheets total across the county). These are treated as single-sheet voters per the convention; investigation suggests they are partial rescans or scanner anomalies.

## 2021 Coordinated (CORA)

* Obtained via CORA disclosure.
* ID columns include `PrecinctPortion`. No `CountingGroup`.
* **Pipeline note**: 2021 also has per-ballot-style summary rows where `TabulatorNum` is `NaN` and the ballot-style code is stuffed into `CvrNumber`. The cleaner drops rows with `NaN` `TabulatorNum`.

## 2020 General (CORA)

* Obtained via CORA disclosure.
* High-turnout presidential cycle.
* Partisan contests include third-row party abbreviations.

## 2019 Coordinated (CORA)

* Obtained via CORA disclosure.
* ID columns include `PrecinctPortion`. Earliest vintage in the archive.
