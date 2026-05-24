# Changelog

Per-vintage notes on the underlying CVR files and any pipeline changes required to handle them.

## 2025 Coordinated

* Source: [Redacted-CVR-PUBLIC.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx).
* Dominion software version 5.17.17.1.
* Ballot styles coded as zero-padded numeric strings.

## 2024 General (pre-recount)

* Source: [2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx).
* High-turnout presidential cycle; largest CVR by ballot count (~384k county-wide, ~114k city of Boulder).
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
* Largest pre-2024 CVR by row count (~321k county-wide).
* Privacy-aggregated rows carry `NaN` in `CvrNumber` (one row per ballot style).
* **Initial pipeline bug**: without the NaN-CvrNumber redaction rule, those aggregate rows were each detected as "voting on a City of Boulder contest" and flipped 37 ballot styles into the "city" set — producing a falsely inflated city-ballot count of 320k. Fixed with the NaN-redaction rule plus a `min_ballots=5` threshold on city detection.

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
