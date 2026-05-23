# Cast-Vote-Records

Boulder County Cast Vote Records — retrieval, cleaning, and twin-path UMAP / HDBSCAN clustering of City of Boulder voting patterns, 2019–2025.

The repository pairs a tested Python pipeline (`cvr_pipeline/`) that turns raw redacted CVR xlsx files into tidy wide-format CSVs with a single analysis notebook (`clusters.ipynb`) that runs a McInnes-style two-pass UMAP + HDBSCAN per election and renders a small-multiples comparison. See [`AGENT.md`](AGENT.md) for architecture, the Colorado Risk-Limiting Audit context that makes these files public, the NIST CVR data model, and design decisions.

## Quickstart

```
pip install -e ".[analysis,test]"
git lfs pull           # fetch CVR xlsx + clean CSVs
pytest                 # ~18 tests, < 1 second
python -m cvr_pipeline build   # regenerate data/clean/ from data/raw/
jupyter notebook clusters.ipynb
```

## Data

Eight redacted CVRs covering 2019–2025 live in `data/raw/` and are versioned via Git LFS:

| Election | Source | Notes |
| --- | --- | --- |
| 2019 Coordinated | CORA | not on bouldercounty.gov by-year pages |
| 2020 General | CORA | presidential cycle |
| 2021 Coordinated | CORA | |
| 2022 General | CORA | midterm cycle |
| 2023 Coordinated | [public](https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx) | first publicly posted Boulder County CVR; ranked-choice mayoral |
| 2024 Primary | [public](https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx) | partisan only; no City of Boulder municipal contests |
| 2024 General | [public](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx) | pre-recount |
| 2025 Coordinated | [public](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx) | |

Cleaned wide CSVs (one row per City of Boulder ballot, one column per contest-choice) appear in `data/clean/` after running the pipeline.

## What's where

```
cvr_pipeline/    # Python package (loader, cleaner, sources, CLI)
tests/           # pytest with a synthetic xlsx fixture
clusters.ipynb   # single analysis notebook
data/raw/        # CVR xlsx (LFS-tracked)
data/clean/      # generated wide CSVs and cluster outputs (LFS-tracked)
AGENT.md         # architecture, decisions, contribution, limitations, future work
```

## Layout of a cleaned CSV

Rows are City of Boulder ballots (one row per ballot sheet, per [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)); columns are flattened from the CVR's two-level header:

- ID columns prefixed `_ID/`: `_ID/CvrNumber` (= NIST `CVR::UniqueId`), `_ID/TabulatorNum`, `_ID/BatchId`, `_ID/RecordId`, `_ID/ImprintedId`, optionally `_ID/CountingGroup`, `_ID/PrecinctPortion`, `_ID/BallotType` (= NIST `CVR::BallotStyleId`).
- One column per `Contest::Choice` (e.g. `City of Boulder Council Candidates (Vote For=4)::Nicole Speer`). Ranked-choice contests have one column per candidate-rank pair, e.g. `City of Boulder Mayoral Candidates (...)::Aaron Brockett(1)` for rank 1.

Cell values:

- `1` = the scanner detected a mark in the bubble (NIST `SelectionPosition::HasIndication = yes`)
- `0` = the bubble was on the ballot for this style and was not marked
- missing (`NaN`) = the contest was not on the voter's ballot style

Note: per NIST, `HasIndication` is distinct from `IsAllocable` (vote countability under contest rules). The Dominion interpreted-snapshot collapses both. For interpretation of these distinctions see [`AGENT.md`](AGENT.md).

## References

The terminology and data-model assumptions in this repository follow the canonical Cast Vote Record literature and the Colorado RLA framework that makes these files public:

- [NIST SP 1500-103, *Cast Vote Records Common Data Format Specification* v1.0](https://doi.org/10.6028/NIST.SP.1500-103) (Wack, Dana, Deutsch, Dziurlaj, Piper; NIST 2019). The CVR data model — snapshot types, identifiers, contest representations, RCV encoding.
- [Lutz, *Auditing Elections Using Ballot Images and AuditEngine — General Background* (2022)](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf). Practical Dominion-CVR workflow reference; §3.1.2 covers the voter-privacy aggregation conventions Boulder uses.
- [Colorado Secretary of State — Risk-Limiting Audit FAQ](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html). The legal and procedural basis (C.R.S. § 1-7-515, 2009) for why CVRs leave the County in the first place.
- [`cdos-rla/colorado-rla`](https://github.com/cdos-rla/colorado-rla). The audit software (Free and Fair, 2017; IRV extension by Democracy Developers, 2023–2025) that consumes these CVRs as input.

## License

MIT. CVR data is public record released by the Boulder County Clerk and Recorder.
