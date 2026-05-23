# AGENT.md — Cast Vote Records

Architecture, design decisions, contribution guidelines, limitations, and future work for the Boulder County Cast Vote Records pipeline and analysis.

## Repository purpose

Provide a reproducible, open archive of Boulder County, Colorado Cast Vote Records (CVRs) from 2019–2025 together with a tested pipeline that produces a tidy wide-format CSV of every City of Boulder ballot per election, plus a single analysis notebook that runs a twin-path UMAP / HDBSCAN clustering on those ballots to surface latent structure in voting behavior.

The audience is anyone who wants to re-run, contest, or extend an empirical finding about how City of Boulder voters vote — civic journalists, election-integrity researchers, political scientists, the County Clerk's office, the broader public.

## Why Boulder publishes CVRs in the first place — Colorado's RLA mandate

Colorado was the first state in the country to require **risk-limiting audits (RLAs)** of every election. The General Assembly authorized RLAs in 2009 via [C.R.S. § 1-7-515](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html), and the [2017 Coordinated Election](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits) was the first statewide RLA — every county that tabulates ballots by machine participates; the few counties that hand-count are exempt because "the audit *is* an audit of the voting system" ([SOS FAQ](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html)).

The RLA gives "a statistical level of confidence that the outcome of an election is correct" — that "there is a high probability that the reported winners accurately reflect how voters marked their ballots." Colorado started at a 9% risk limit and has tightened it to 3% as counties have gotten more practiced.

The audit is a *comparison audit*: counties export their CVRs from the voting system, the state's RLA software ([cdos-rla/colorado-rla](https://github.com/cdos-rla/colorado-rla) — originally built by Free and Fair in 2017, extended for IRV/ranked-choice contests by Democracy Developers in 2023–2025) draws a statistically powered random sample of ballots, and bipartisan county audit boards then physically pull those paper ballots and reproduce the voter markings in the software. The boards' interpretations are compared against the CVR's interpretation; discrepancies above the risk limit force escalation up to a full hand count.

**This is why the Boulder County CVRs we archive in this repository exist.** Without Colorado's RLA mandate the County would not be exporting and (eventually) publishing ballot-level records — there would be only the precinct-level Statement of Votes. The CVR files Boulder posts publicly on `assets.bouldercounty.gov` are derived from the same Dominion exports the County feeds into the RLA. The public release is downstream: redactions are applied to protect voter anonymity ([AuditEngine §3.1.2](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf)) and then the file is posted to the County's election results page.

Two consequences for this repository:

1. **The Dominion XLSX format is what the RLA consumes.** The ColoradoRLA software has historically accepted Dominion CVR exports (and ES&S equivalents) directly. The four-row header, the ballot-style code in `BallotType`, and the contest-per-column layout are not Boulder idiosyncrasies — they are the format the state's audit infrastructure was built to read.
2. **The 2023 Boulder mayoral RCV race is exactly the kind of contest that motivated the recent ColoradoRLA IRV extension.** Auditing RCV is harder than plurality (RAIRE-style assertions are required to define what counts as a discrepancy under elimination rounds); Democracy Developers added that support to `cdos-rla/colorado-rla` between 2023 and 2025 specifically so Colorado counties running RCV elections could continue to be audited.

## Background: what a Cast Vote Record actually is

A **Cast Vote Record (CVR)** is the electronic record of one voter's ballot selections as captured by a vote-capture device (typically a paper-ballot scanner; for Boulder County, the [Dominion ImageCast](https://www.dominionvoting.com/) line). Each row in a Boulder County CVR file corresponds to one *ballot sheet* (per [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)); single-sheet ballots yield one row per ballot.

The canonical reference is [NIST SP 1500-103, *Cast Vote Records Common Data Format Specification*](https://doi.org/10.6028/NIST.SP.1500-103). The practical reference for Dominion-flavored CVRs and audit workflow is [Lutz, *Auditing Elections Using Ballot Images and AuditEngine*](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf). Boulder publishes a Dominion XLSX (proprietary, not the NIST CDF), so the loader maps Dominion's columns to NIST concepts:

| Dominion column | NIST CDF attribute (SP 1500-103) | Notes |
| --- | --- | --- |
| `CvrNumber` | `CVR::UniqueId` (§3.5.1) | Per-CVR unique identifier within the report |
| `TabulatorNum` | `CVR::CreatingDevice.SerialNumber` (§3.5.6) | The scanner that captured this ballot |
| `BatchId` | `CVRSnapshot::BatchId` (§3.5.5) | Batch identifier — Dominion exports this; ES&S typically does not |
| `RecordId` | `CVRSnapshot::BatchSequenceId` (§3.5.5) | Position within the batch |
| `ImprintedId` | `CVR::BallotAuditId` (§3.5.4) | Composite `TabulatorNum-BatchId-RecordId` that the scanner can imprint on the paper ballot for ballot-level comparison auditing |
| `CountingGroup` | (Dominion-specific) | Regular / Provisional / Mail / etc. |
| `PrecinctPortion` | corresponds to `BallotStyleUnit` (§3.5.6) | Political-geography portion of the precinct served by this ballot style |
| `BallotType` | `CVR::BallotStyleId` (§3.5.4.1) | **The ballot *style* — which contests the voter was eligible to vote on.** NIST calls this *ballot style*; Dominion calls it *BallotType*. The two names refer to the same thing |

Each ballot-choice cell in the wide CSVs holds a `0`, `1`, or `NaN`:

* `1` ≈ the NIST `SelectionPosition::HasIndication` flag (NIST §3.4.2) = "the scanner detected a mark in this bubble."
* `0` = "this bubble was on the ballot for this style and was not marked."
* `NaN` = "this contest was not on the voter's ballot style."

NIST distinguishes `HasIndication` (a fact about the mark) from `IsAllocable` (a decision about whether the mark counts as a vote under contest rules). The Dominion interpreted-snapshot export collapses both into the same numeric value, so the wide CSV technically encodes the *tabulated* selection — voter intent as the scanner adjudicated it, before any later adjudicator-modified snapshot.

NIST defines three CVR snapshot types: **original** (raw scanner output), **interpreted** (after contest-rule application), and **modified** (after adjudication). Boulder's public redacted CVRs are the **interpreted** snapshot. The 2024 General also has a post-recount CVR that corresponds to the *modified* snapshot for ballots flagged in the recount; this pipeline uses the pre-recount version.

### Contest types observed in Boulder

Boulder CVRs include the following NIST contest types:

* **Single-choice** ("Vote For=1"): one bubble per candidate. Most contests.
* **Multi-choice** ("Vote For=N"): up to N bubbles can be marked. Council at-large contests use this.
* **Ranked-choice (RCV)**: per NIST §3.4, RCV represents each candidate-rank combination as a separate `SelectionPosition`. Dominion encodes this with one column per candidate-rank combination, with the rank as a `(N)` suffix on the candidate name — e.g. `Aaron Brockett(1)`, `Aaron Brockett(2)`, `Aaron Brockett(3)`, `Aaron Brockett(4)` for ranks 1–4. The 2023 Boulder Coordinated mayoral race is the only RCV contest in this archive.
* **Ballot measure**: a contest with `Yes`/`No` choices. Boulder uses these for municipal ballot issues.

### Privacy aggregation

Boulder aggregates ballots in small precincts to protect voter anonymity (cf. AuditEngine §3.1.2). The CVR file therefore contains some rows that do not correspond to any single voter:

* In **2023 and later**, aggregated rows carry a sentinel string in `CvrNumber` (`"RCV Redacted & Randomly Sorted"` or `"Redacted & Aggregated"`).
* In **2019–2022**, aggregated rows carry `NaN` in `CvrNumber` (one such row per ballot style).

The cleaner drops both. Aggregate rows are not analyzable as individual ballots and should never enter a clustering pipeline.

## Architecture

```
.
├── AGENT.md                          # this file
├── README.md                         # quickstart for end users
├── LICENSE
├── pyproject.toml                    # cvr-pipeline package metadata
├── requirements.txt                  # pinned analysis-stack mirror of pyproject
├── .gitattributes                    # Git LFS tracking for xlsx + csv + png
├── .gitignore
│
├── cvr_pipeline/                     # Python package — the data pipeline
│   ├── __init__.py
│   ├── sources.py                    # CvrSource manifest (1 entry per election)
│   ├── loader.py                     # load_raw_cvr() — header reconstruction
│   ├── cleaner.py                    # clean_city_cvr() — filter + tidy
│   ├── cli.py                        # `python -m cvr_pipeline build`
│   └── __main__.py
│
├── tests/                            # pytest suite (synthetic xlsx fixture)
│   ├── conftest.py
│   ├── test_loader.py
│   ├── test_cleaner.py
│   ├── test_sources.py
│   └── test_cli.py
│
├── scripts/
│   └── build_clusters_nb.py          # regenerates clusters.ipynb from source
│
├── clusters.ipynb                    # SINGLE analysis notebook
│
└── data/                             # ALL CVR data lives here; LFS-tracked
    ├── raw/                          # *.xlsx as published by Boulder County
    │   ├── 2019-CVR.xlsx
    │   ├── 2020-CVR.xlsx
    │   ├── 2021-CVR.xlsx
    │   ├── 2022-CVR.xlsx
    │   ├── 2023-Coordinated-CVR.xlsx
    │   ├── 2024-Primary-CVR.xlsx
    │   ├── 2024-General-CVR.xlsx
    │   └── 2025-Coordinated-CVR.xlsx
    └── clean/                        # generated; one CSV per election
        ├── <election>-city-of-boulder-wide.csv
        ├── <election>-cluster-profiles.csv
        ├── <election>-ballots-with-clusters.csv
        ├── _summary.csv
        ├── _cluster_robustness.csv
        └── city-of-boulder-cluster-smallmultiples.png
```

### Two-layer separation

The pipeline is a **Python package**; the analysis is a **single Jupyter notebook**.

This split is deliberate. The pipeline runs every time someone rebuilds the data — it should be testable, callable from a script or a notebook, and have a clear interface. A notebook is the wrong tool for that: cells encourage hidden state, top-of-cell imports get scattered, helper functions get duplicated. Code that other code depends on belongs in a package.

The clustering analysis is the opposite: it is read top-to-bottom by a critic who wants to retrace the empirical claim. Markdown narration between cells is the point of the artifact; it is the trust contract. Wrapping it in a CLI would defeat the purpose.

So:

- **`cvr_pipeline/`** — pure functions, no global state, no plotting, no Jupyter dependency. Imports `pandas`, `numpy`, `openpyxl`, `requests`. Drives every transformation that turns one ``data/raw/*.xlsx`` into one ``data/clean/*-city-of-boulder-wide.csv``.
- **`clusters.ipynb`** — narrative; imports the cleaned CSVs and `umap`, `hdbscan`, `sklearn`; never mutates `data/raw/`.

### Data flow

```
   ┌───────────────────┐    cvr_pipeline.loader.load_raw_cvr
   │  data/raw/*.xlsx  │ ─────────────────────────────────────►
   │  (LFS, immutable) │           rebuild MultiIndex
   └───────────────────┘
              │
              ▼
   cvr_pipeline.cleaner.clean_city_cvr
   (auto-detect city ballot types, drop redacted, drop NaN cols,
    integrity-check, flatten columns)
              │
              ▼
   ┌───────────────────────────────────────────────┐
   │  data/clean/<election>-city-of-boulder-wide.csv  │
   │  data/clean/_summary.csv                       │
   └───────────────────────────────────────────────┘
              │
              ▼
   clusters.ipynb
   ── per-election vote matrix (NaN→0)
   ── UMAP 10-D ──► HDBSCAN ──► cluster labels
   ── UMAP 2-D (separate) ──► coloured by labels
              │
              ▼
   data/clean/<election>-cluster-profiles.csv
   data/clean/<election>-ballots-with-clusters.csv
   data/clean/_cluster_robustness.csv
   data/clean/city-of-boulder-cluster-smallmultiples.png
```

## Design decisions

### Why a package + a notebook, not two notebooks?

Earlier drafts used `01_pipeline.ipynb` + `02_clusters.ipynb`. That was rejected because:

* Re-running the pipeline required executing a notebook end-to-end, which is slow on a fresh kernel and impossible to test.
* The cleaning logic could not be unit-tested without an integration test against the real (large, slow) xlsx files.
* The pipeline notebook contained boilerplate (downloads, header parsing, integrity checks) that did not belong in a trust-contract artifact.

The package + notebook split makes the cleaning logic CI-friendly (pytest passes in under a second on synthetic fixtures) and keeps the analysis notebook focused on what a human reader needs to follow.

### Why auto-detect City of Boulder ballot types?

The County's ballot-type coding has drifted across years:

| year | format | notes |
| --- | --- | --- |
| 2019, 2020, 2021, 2022, 2023 | `DS-NN` | string with `DS-` prefix |
| 2024 (Primary + General), 2025 | `'NN'` | zero-padded numeric string |
| | | (a few `int` values in 2024 Primary) |

And the *set* of ballot types that represent City of Boulder voters changes by election (one in 2023, multiple in 2019–2022). Rather than hardcode a year-by-year map that would silently rot, `cvr_pipeline.cleaner.detect_city_ballot_types` infers the city ballot types by finding which ballot types vote on at least one contest whose name contains `"City of Boulder"`. The same heuristic works for any year and is documented in code.

### Why Git LFS?

The eight raw xlsx files total ~340 MB; the cleaned CSVs another ~50 MB. Committing them as ordinary blobs would bloat the pack and slow every clone. Git LFS keeps the pointers in the tree and the actual bytes in a content store, so a `git clone` is fast and a `git lfs pull` is opt-in.

The `.gitattributes` patterns are:

```
data/raw/*.xlsx       filter=lfs ...
data/clean/*.csv      filter=lfs ...
data/clean/*.png      filter=lfs ...
```

CVR data and cleaned outputs live in the repo (and are versioned) so that the trust contract — "the data and code for replicating these analyses can be found on GitHub" — does not depend on a re-download from a third-party server that might delete or revise the file later.

### Why twin-path UMAP / HDBSCAN?

Two converging reasons:

* **Distance concentration.** In a 10–80-dimensional vote space the raw cosine and Euclidean distances compress toward a narrow band; HDBSCAN cannot reliably distinguish density there. UMAP to 5–50 dimensions reshapes the manifold so density-based clustering recovers signal.
* **2-D projections are lossy and brittle.** UMAP/t-SNE at `n_components=2` make hard tradeoffs about which neighborhood relationships to preserve; clusters genuinely separated in higher-d can collide in 2-D (or vice versa). Clustering on the 2-D coordinates that ended up in the chart would mean the analysis and the visualization are the same artifact — one brittle reduction doing double duty.

The McInnes pipeline (UMAP author, see [umap-learn docs](https://umap-learn.readthedocs.io/en/latest/clustering.html)) is the standard answer: cluster on a 10-D UMAP, visualize on a separate 2-D UMAP, color the 2-D scatter by the 10-D cluster labels. Both UMAP runs are seeded; the analysis runs a re-seeded robustness check (adjusted Rand index between two label sets) before any claim is made.

### Why filter to City of Boulder?

City of Boulder is the largest single municipal jurisdiction in the county and was the focus of the original exploration this pipeline cannibalizes. Restricting to one jurisdiction makes the vote matrix coherent (every ballot answers the same set of municipal contests) and the cluster analysis interpretable.

The auto-detection function in `cleaner.py` takes a `marker` parameter, so swapping the analysis to City of Longmont (`"City of Longmont"`) or Boulder Valley School District (`"Boulder Valley School District"`) is a one-line change.

## Contribution guidelines

### Adding a new election

1. Drop the raw `.xlsx` file into `data/raw/`.
2. Append a `CvrSource(...)` entry to `cvr_pipeline/sources.py` with the file's `election_key`, year, type, filename, and `public_url` (or `None` if it came from a CORA disclosure).
3. Run `python -m cvr_pipeline build`. The new election should appear in `data/clean/_summary.csv`.
4. Run `pytest`.
5. Re-execute `clusters.ipynb` to incorporate the new election into the small-multiples figure.
6. Commit the new raw xlsx (LFS will store the bytes), the regenerated clean CSVs, and the updated notebook.

### Adding a new analysis

Put new analysis notebooks at the repo root with a single descriptive name (e.g. `mayor-rcv-pivot.ipynb`). Use the cleaned wide CSVs in `data/clean/` as input; do not re-implement the cleaning logic.

If the analysis needs a new helper function that more than one notebook would use, add it to `cvr_pipeline/` as a new module and write a test.

### Running the test suite

```
pip install -e ".[test]"
pytest
```

All tests use a synthetic xlsx built on the fly in `tests/conftest.py`; they do not depend on the real CVR files. CI-friendly; runs in well under a second.

### Code conventions

* Python ≥ 3.10. Type hints encouraged but not enforced.
* `pandas` for tabular data; `numpy` for arrays; no other heavyweight deps in `cvr_pipeline/`.
* Notebooks follow the [public-interest-data-oped notebook discipline](https://github.com/anthropics/skills): single H1 (the title cell), `## H2` per major section, markdown before each code cell, explicit `f, ax = plt.subplots()` with axis labels and legends, random seeds set near use, no hard-coded absolute paths.
* Commit notebook outputs (cells executed top-to-bottom) so the GitHub blob view renders the figures and tables.

## Limitations

* **Anonymization.** Boulder County's redacted CVRs strip voter identifiers. A voter cannot be tracked across elections; cluster comparisons across years describe *populations* of voters, not the same voters. Any reading of cluster persistence across years is a population statement, not a panel statement.
* **Ballot-type coding drift.** The County has changed how ballot types are coded between 2023 and 2024 (DS-NN → zero-padded numeric). The auto-detection in `cleaner.py` is robust to this, but a future schema change (e.g. dropping `BallotType` entirely) would require a code update.
* **Header schema variance.** Pre-2023 CVRs include a `PrecinctPortion` column that 2023–2025 do not; 2024 General includes a third header row with party abbreviations that earlier years do not. `loader.py` handles every observed variant; an undocumented future variant could break it.
* **NaN semantics.** The wide CSV stores three values per ballot-choice cell: `1` (the scanner detected a mark in the bubble — NIST `HasIndication = yes`), `0` (the bubble was on the ballot for this style and not marked), and `NaN` (the contest was not on the voter's ballot style at all). The clustering notebook treats `NaN` as `0` for embedding. Analyses that need to distinguish *undervote* (was on the ballot, left blank) from *not eligible* (was not on the ballot) must preserve the `NaN`/`0` distinction by joining the per-ballot-style contest universe — `data/raw/*.xlsx` retains it.

* **HasIndication vs. IsAllocable.** What we store as `1` is NIST `HasIndication`, not `IsAllocable` — overvotes (more bubbles marked than allowed) and other rule-violations are still encoded as `1` in the source CVR. The Dominion interpreted-snapshot export does not separately flag allocability. Analyses sensitive to invalidated marks (overvote-rate estimates, recount comparisons) need either the original snapshot or the modified post-adjudication snapshot, neither of which Boulder publishes for the redacted archive.
* **Privacy redactions.** Small precincts have their ballots aggregated and the aggregate rows carry a sentinel `CvrNumber`; the cleaner drops them. The total dropped count is in `_summary.csv` per election.
* **City of Boulder only.** The analysis pipeline filters to City of Boulder ballots. Other jurisdictions can be analyzed by changing the `marker` parameter in `clean_city_cvr` or by writing a parallel analysis notebook.
* **2024 partisan primary.** Has zero City of Boulder municipal contests; the pipeline produces no wide CSV for it. It remains in `data/raw/` for completeness.
* **HDBSCAN sensitivity.** Cluster assignments depend on `min_cluster_size` and `min_samples`. The notebook uses a ballot-count-scaled default; the robustness check confirms the cluster count is stable across two random seeds, but does not vary the HDBSCAN hyperparameters. A piece that wants to claim a specific cluster count should report sensitivity to `min_cluster_size` too.

## Future work

* **Pre-2019 CORA disclosures.** If older Boulder County CVRs become retrievable (2017 Coordinated, 2016 General, etc.), append them to `sources.py` and the pipeline picks them up automatically.
* **Other Colorado counties.** Adapt the loader to Larimer / Denver / Arapahoe CVRs (same Dominion format) by relaxing the loader's filename and id-column assumptions.
* **Tabulator / batch geography.** Join `TabulatorNum` and `BatchId` to precinct geography (when the County publishes the crosswalk) so clusters can be mapped to neighborhoods.
* **Ranked-choice analysis.** The 2023 Coordinated has Boulder's first ranked-choice mayoral election. A dedicated notebook could analyze ranking patterns, exhausted ballots, and the simulated alternative-method outcomes.
* **Cross-election cluster matching.** Cluster *labels* are not comparable across years (cluster 3 in 2019 is not the same group as cluster 3 in 2024). A future analysis could match clusters across elections by contest-overlap signatures.
* **Methodology box.** When this work supports a published op-ed, write the methodology disclosure described in [public-interest-data-oped's journalism conventions §4](https://github.com/anthropics/skills) — the embedding model, the UMAP / HDBSCAN parameters used for clustering, the visualization UMAP parameters, the random seed, the robustness-check ARI.

## Provenance and license

Pipeline + analysis code: MIT (see `LICENSE`). CVR data: public records released by the Boulder County Clerk and Recorder (publicly posted 2023–2025; 2019–2022 obtained via CORA disclosure).

## References

### CVR data model

* [NIST Special Publication 1500-103, *Cast Vote Records Common Data Format Specification*, Version 1.0](https://doi.org/10.6028/NIST.SP.1500-103) (Wack et al., November 2019; updates 03-31-2020). The canonical CVR data model — UML, XML, JSON. The terminology used throughout this repository (HasIndication, IsAllocable, BallotStyle, snapshot types) follows this spec.
* [Lutz, *Auditing Elections Using Ballot Images and AuditEngine — General Background* (V2 2022-10-04)](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf). Practical reference for Dominion-flavored CVR workflows; §3.1.2 explains the privacy-aggregation conventions Boulder follows.

### Colorado Risk-Limiting Audit context

* [Colorado Secretary of State — Risk-Limiting Audit FAQ](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html). The state's own description of the RLA: authorizing statute (C.R.S. § 1-7-515, 2009), first statewide RLA in the 2017 Coordinated, 9% → 3% risk-limit reduction, role of CVRs in the comparison audit, bipartisan county audit boards.
* [`cdos-rla/colorado-rla`](https://github.com/cdos-rla/colorado-rla). The audit software that consumes Boulder County's Dominion CVR exports. Originally built by Free and Fair (Joey Dodds, Joseph Kiniry, Neal McBurnett, Daniel Zimmerman) in 2017; extended for IRV / ranked-choice contests by Democracy Developers (Michelle Blom, Andrew Conway, Vanessa Teague) in 2023–2025. Java/TypeScript; integrates with [`raire-service`](https://github.com/DemocracyDevelopers/raire-service) for IRV assertion generation.
* [Colorado Launches First-in-the-Nation Post-Election Audits, NPR, 22 Nov 2017](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits). Coverage of the inaugural statewide RLA in the 2017 Coordinated Election.
* [Colorado's Election Officials Lead a Nationwide Push for Better Audits, Politico, 17 Jul 2017](https://www.politico.com/story/2017/07/17/colorado-post-election-audits-cybersecurity-240631). The political and cybersecurity context — post-2016 election integrity concerns — that drove Colorado to actually turn on the statute it had passed in 2009.

### Data sources

* [Boulder County Elections — Past Election Results](https://bouldercounty.gov/elections/by-year/). Source of the publicly posted 2023–2025 CVRs.

### Methods

* [public-interest-data-oped notebook discipline](https://github.com/anthropics/skills). The notebook style guide this repository's `clusters.ipynb` follows.
* [umap-learn clustering documentation](https://umap-learn.readthedocs.io/en/latest/clustering.html). McInnes' canonical recommendation for the two-pass UMAP + HDBSCAN pipeline used in `clusters.ipynb`.
