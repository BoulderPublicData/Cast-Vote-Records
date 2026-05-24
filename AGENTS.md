# AGENTS.md — Cast Vote Records

Maintainer-facing brief. Consumers should read [`README.md`](README.md) instead.

## What this project is

A reproducible Python pipeline that liberates Boulder County, Colorado redacted Cast Vote Records (2019–2025) from the County's Dominion XLSX exports into tidy, documented, wide-format CSVs of City-of-Boulder ballots, plus a single analysis notebook that runs a McInnes-style two-pass UMAP + HDBSCAN clustering per election.

Follows the [data-liberation](https://github.com/brianckeegan/data-liberation-skill) convention pragmatically:

* `scripts/` is the package (not `cvr_pipeline/`, not `src/`).
* `data/original/` holds immutable raw downloads (LFS-tracked) + `manifest.json` with per-file SHA-256.
* `data/processed/` holds tidy outputs + `provenance.csv` sidecar (LFS-tracked).
* `data/audit/` holds auto-generated reports.
* `data/lookups/` is reserved for crosswalks (currently empty — single-source).

The pragmatic choices: keep setuptools (not hatchling/uv) and avoid a Source ABC layer (a single source doesn't warrant it). Otherwise the data-liberation conventions apply — manifest, provenance, pandera schema validation, Markdown audit report, reconcile script, optional Datasette publishing, opt-in scheduled refresh.

## Quickstart

```bash
pip install -e ".[analysis,test]"
pytest                                # 27 tests, < 1 second
python -m scripts.pipeline            # fetch → clean → audit
jupyter notebook clusters.ipynb
```

The CLI exposes phases individually too: `python -m scripts.pipeline {fetch|clean|audit|reconcile|publish|list}`.

## Layout

| Path | Responsibility |
| --- | --- |
| `scripts/config.py` | Path constants (`ORIGINAL_DIR`, `PROCESSED_DIR`, ...) |
| `scripts/sources.py` | `CvrSource` dataclass + `SOURCES` manifest tuple |
| `scripts/loader.py` | `load_raw_cvr()` — reconstructs the Dominion 4-row header into a MultiIndex DataFrame |
| `scripts/cleaner.py` | `clean_city_cvr()` — auto-detects city ballot styles, drops the three flavours of privacy-aggregated rows, drops all-NaN contest cols, integrity-checks, flattens columns |
| `scripts/schema.py` | Pandera `ID_BLOCK_SCHEMA` + `validate_id_block` + `validate_contest_columns` |
| `scripts/fetch.py` | Idempotent downloader; writes `data/original/manifest.json` with per-file SHA-256 |
| `scripts/clean.py` | Orchestrator: walks each source, runs loader + cleaner, writes wide CSV + `provenance.csv` + `_summary.csv` |
| `scripts/audit.py` | Summary stats per processed CSV → `data/audit/summary.md` + `docs/variables.{md,csv}` |
| `scripts/reconcile.py` | Independent raw-row count check vs `_summary.csv`; non-zero exit on mismatch |
| `scripts/publish.py` | Builds `data/processed/cast_vote_records.db` for Datasette + auto-generates `metadata.yaml` (opt-in) |
| `scripts/pipeline.py` | argparse CLI: `fetch|clean|audit|reconcile|publish|list`; default = full run |
| `tests/` | 27-test pytest suite using a synthetic xlsx fixture; no real-file dependency |
| `docs/data-dictionary.md` | Hand-maintained per-column documentation |
| `docs/filter-pivot-recipes.md` | pandas / R / SQL recipes for slicing the wide CSVs |
| `docs/methodology.md` | How the data is extracted, end-to-end |
| `docs/changelog.md` | Per-vintage notes (format drift, parser changes) |
| `docs/variables.{md,csv}` | Auto-generated column profile (do not hand-edit) |
| `data/original/` | LFS-tracked source xlsx + `manifest.json` |
| `data/processed/` | LFS-tracked wide CSVs + `provenance.csv` + `_summary.csv` (+ `cast_vote_records.db` when built) |
| `data/audit/` | Latest `summary.md` and `reconcile.md` (committed); per-run timestamped copies (gitignored) |
| `data/lookups/` | Crosswalks / code systems (empty for now) |
| `clusters.ipynb` | The McInnes two-pass UMAP + HDBSCAN small-multiples analysis |
| `.github/workflows/tests.yml` | Always-on: pytest on push and PR |
| `.github/workflows/{refresh,publish,gh-pages}.yml.disabled` | Opt-in CI for scheduled refresh, Datasette deploy, Quarto site |

## Background: what a Cast Vote Record actually is

A **Cast Vote Record (CVR)** is the electronic record of one voter's ballot selections as captured by a vote-capture device (for Boulder County, the [Dominion ImageCast](https://www.dominionvoting.com/) scanner line). Each row in a Boulder County CVR file corresponds to one *ballot sheet* (per [NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)).

The canonical reference is [NIST SP 1500-103, *Cast Vote Records Common Data Format Specification*](https://doi.org/10.6028/NIST.SP.1500-103). The practical reference for Dominion-flavored CVRs and audit workflow is [Lutz, *Auditing Elections Using Ballot Images and AuditEngine*](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf). The full Dominion-column → NIST-CDF mapping lives in [`docs/data-dictionary.md`](docs/data-dictionary.md); the headline:

* `CvrNumber` → `CVR::UniqueId` (NIST §3.5.1)
* `BallotType` → `CVR::BallotStyleId` (NIST §3.5.4.1) — **this is the ballot *style*, not the NIST "ballot type" concept**
* cell value → `SelectionPosition::HasIndication` (NIST §3.4.2)

NIST defines three CVR snapshot types: **original** (pre-interpretation), **interpreted** (post-rule), **modified** (post-adjudication). Boulder's redacted exports are the **interpreted** snapshot.

## Why Boulder publishes CVRs in the first place — Colorado's RLA mandate

Colorado was the first state to require **risk-limiting audits (RLAs)** of every election. The General Assembly authorized RLAs in 2009 via [C.R.S. § 1-7-515](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html); the [2017 Coordinated Election](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits) was the first statewide RLA. Colorado started at a 9% risk limit and has tightened it to 3%.

The audit is a *comparison audit*: counties export CVRs from the voting system, the state's RLA software ([cdos-rla/colorado-rla](https://github.com/cdos-rla/colorado-rla) — Free and Fair, 2017; IRV extension by Democracy Developers, 2023–2025) draws a random sample, and bipartisan county audit boards physically pull those paper ballots and reproduce the interpretation in the software. **Without the RLA mandate, the public CVRs in this archive would not exist.**

## Privacy aggregation

Boulder uses three conventions to aggregate ballots in small precincts:

* **2023+** — sentinel strings in `CvrNumber` (`"RCV Redacted & Randomly Sorted"` or `"Redacted & Aggregated"`).
* **2019–2022** — `NaN` in `CvrNumber` for one aggregated row per ballot style.
* **2021 specifically** also has per-ballot-style summary rows where `TabulatorNum` is `NaN` and the ballot-style code is stuffed into `CvrNumber`.

`scripts.cleaner.clean_city_cvr` drops all three. The `min_ballots=5` threshold in `detect_city_ballot_types` is a defensive backstop against single aggregate rows that slip past the redaction filter.

## Design decisions

* **`scripts/` package, single analysis notebook.** The data-liberation convention is `scripts/` (not `src/` or the project name). The pipeline is callable, testable, and CI-friendly; the analysis is one notebook a critic can read top-to-bottom.
* **Single loader, not vintage bands.** The Dominion XLSX format is structurally stable across 2019–2025. The only drift is the ID-column set (which `ID_LABELS` auto-detects) and the 2024 third-row party tags (which fall through the "not a known ID label" branch). One parser is defensible because the format actually didn't change.
* **Wide as the primary storage shape.** Per the data-liberation convention's note on ballot-level data, wide-by-key is correct when the ballot is the observation. A tidy long-form derivative is shown in `docs/filter-pivot-recipes.md`.
* **Auto-detect City of Boulder ballot styles.** The County's coding has drifted (`DS-NN` strings → zero-padded numeric strings); auto-detection by contest-content avoids per-year hardcoding.
* **Per-extract provenance, not per-row.** `data/processed/provenance.csv` keyed on `election_key`.
* **Immutable originals.** Files in `data/original/` are write-only from `scripts.fetch`. Re-running the cleaner does not touch them.
* **Errors durable, not fatal.** The CLI's `--fail-on-empty` flag turns silent regressions loud.

## How to add a new election

1. Place the xlsx in `data/original/<filename>` (or rely on `scripts.fetch` if it has a public URL).
2. Append a `CvrSource(...)` to `SOURCES` in `scripts/sources.py`.
3. Run `python -m scripts.pipeline`.
4. Run `pytest`.
5. Update `docs/changelog.md` with any vintage-specific notes.
6. Re-execute `clusters.ipynb` if you want the new election in the small-multiples.
7. Commit; LFS handles the binary blobs.

## Known limitations

* **Voter anonymity prevents panel analysis.** The redacted CVRs strip voter identifiers; the same voter cannot be tracked across years.
* **`HasIndication` vs `IsAllocable`.** The cell value `1` is `HasIndication`. Overvotes are still encoded as `1`; the Dominion interpreted-snapshot collapses the rule-based countability decision into the same value. Analyses sensitive to invalidated marks need the *original* or *modified* snapshot, neither of which Boulder publishes.
* **NaN-vs-0 semantics.** `NaN` = "contest not on this voter's ballot style"; `0` = "contest was on the ballot, voter did not mark this choice." The clustering pipeline collapses `NaN → 0` for embedding; preserve the distinction from the wide CSV when undervote analysis matters.
* **Schema drift across vintages.** ID column sets differ across years; the pandera schema is permissive on optional ID columns.
* **2024 Primary is empty.** Partisan primaries have no City of Boulder municipal contests; the cleaner correctly emits zero rows.
* **Reconcile is shallow.** `scripts.reconcile` checks raw row counts against the original xlsx; it does not (yet) reconcile per-contest vote totals against the County's Statement of Votes.

## Future work

* **Tidy long derivative** in `data/processed/cast_vote_records.parquet`.
* **Per-contest vote-total reconciliation** against the official Statement of Votes XLSX.
* **Datasette deployment** — `scripts.publish.build` is scaffolded; enable `publish.yml` once `VERCEL_TOKEN` is in repo secrets.
* **Quarto site** under `docs/` — rendered to GitHub Pages via the disabled `gh-pages.yml`.
* **2024 General Recount diff** — comparing it to the pre-recount version is precisely the NIST CDF *modified-snapshot* delta.
* **Pre-2019 elections** if CORA-retrievable.

## References

### CVR data model

* [NIST SP 1500-103, *Cast Vote Records Common Data Format Specification* v1.0](https://doi.org/10.6028/NIST.SP.1500-103) (Wack et al., NIST 2019).
* [Lutz, *Auditing Elections Using Ballot Images and AuditEngine — General Background* (2022)](https://copswiki.org/w/pub/Common/M1986/Auditing%20Elections%20Using%20Ballot%20Images%20and%20AuditEngine%20--%20General%20Background.pdf).

### Colorado RLA context

* [Colorado Secretary of State — Risk-Limiting Audit FAQ](https://www.coloradosos.gov/pubs/elections/RLA/faqs.html).
* [`cdos-rla/colorado-rla`](https://github.com/cdos-rla/colorado-rla).
* [Colorado Launches First-in-the-Nation Post-Election Audits — NPR, 22 Nov 2017](https://www.npr.org/2017/11/22/566039611/colorado-launches-first-in-the-nation-post-election-audits).
* [Politico — Colorado's Election Officials Lead a Nationwide Push for Better Audits (17 Jul 2017)](https://www.politico.com/story/2017/07/17/colorado-post-election-audits-cybersecurity-240631).

### Data-liberation conventions

* [`data-liberation` skill](https://github.com/brianckeegan/data-liberation-skill).
* [BoulderPublicData/Election-Results](https://github.com/BoulderPublicData/Election-Results).

### Methods

* [umap-learn clustering documentation](https://umap-learn.readthedocs.io/en/latest/clustering.html).
* [public-interest-data-oped notebook discipline](https://github.com/brianckeegan/public-interest-data-oped-skill).

### Data sources

* [Boulder County Elections — Past Election Results](https://bouldercounty.gov/elections/by-year/).

## License

Code: MIT. Data: public records released by the Boulder County Clerk and Recorder (publicly posted 2023–2025; 2019–2022 obtained via Colorado Open Records Act disclosure). Per data-liberation convention, the data is republished here under CC-BY-4.0.
