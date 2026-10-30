# AGENTS.md — Cast Vote Records

Maintainer-facing brief. Consumers should read [`README.md`](README.md) instead.

## What this project is

A reproducible Python pipeline that liberates Boulder County, Colorado redacted Cast Vote Records (2017–2025) from the County's Dominion exports (XLSX; CSV for the 2017 and 2018 CORA releases) into tidy, documented, wide-format countywide per-voter CSVs, plus a single analysis notebook that runs a McInnes-style two-pass UMAP + HDBSCAN clustering per election.

Follows the [data-liberation](https://github.com/brianckeegan/data-liberation-skill) convention pragmatically:

* `scripts/` is the package (not `cvr_pipeline/`, not `src/`).
* `data/original/` holds immutable raw downloads (LFS-tracked) + `manifest.json` with per-file SHA-256.
* `data/processed/` holds one subfolder per dataset, as in Election-Results: `cast-vote-records/` (per-voter CSVs + `_summary.csv` + `provenance.csv`) and `clusters/` (notebook outputs + their `provenance.csv`). All LFS-tracked.
* `data/audit/` holds auto-generated reports.
* `data/lookups/` is reserved for crosswalks (currently empty — single-source).

The pragmatic choice: avoid a Source ABC layer (a single source doesn't warrant it). Tooling matches the sibling [Election-Results](https://github.com/BoulderPublicData/Election-Results) repo: uv with a committed `uv.lock`, hatchling, Python ≥ 3.11 (`.python-version`), and the same ruff config. Otherwise the data-liberation conventions apply — manifest, provenance, pandera schema validation, Markdown audit report, reconcile script, optional Datasette publishing, opt-in scheduled refresh.

## Quickstart

```bash
git lfs pull                          # the originals and processed CSVs are LFS objects
uv sync --all-extras                  # core + analysis + publish extras + dev group (pytest, ruff)
uv run ruff check .
uv run ruff format --check .           # CI enforces formatting; `ruff format .` fixes it
uv run pytest                         # a few seconds; synthetic fixtures only
uv run python -m scripts.pipeline     # fetch (verify hashes) → clean → audit
uv run python -m scripts.pipeline reconcile [--sov ../Election-Results/data/processed/statements-of-votes]
uv run jupyter nbconvert --to notebook --execute --inplace clusters.ipynb
```

The CLI exposes phases individually too: `python -m scripts.pipeline {fetch|clean|audit|reconcile|publish|list}`. Shared options (`-q`, `-e/--election 2024-general`, `--year 2024`, `--force`, `--fail-on-empty`, `--update-manifest`) work before or after the subcommand; one the subcommand doesn't use is an error.

## Checks by change type

Run the cheapest check that can catch a mistake in what you changed, and say in the PR which one you ran. A full notebook run proves nothing about a docs edit and costs half an hour; skipping `reconcile` after a cleaner change can ship wrong counts.

| Change touches | Run | Time |
|---|---|---|
| docs, comments, recipes, CI config | `ruff check .`, `ruff format --check .`, `pytest` | < 1 min |
| `scripts/` other than the loader, cleaner and sources | + `pipeline reconcile` | ~3 min |
| `loader.py`, `cleaner.py`, `sources.py`, `data/original/` | + full `pipeline` (or `clean -e <key>` while iterating, ~15 s–3 min per election), then `reconcile --sov …` | ~15 min |
| paths, keys or file names only (renames) | + the notebook's load and write cells on the new paths (smoke test) | ~2 min |
| cluster inputs, `clusters.ipynb` logic, UMAP/HDBSCAN parameters | + one full `nbconvert --execute`; a second run only to prove reproducibility after changing seeds or parameters | 20–30 min |

The per-voter CSVs should come out byte-identical whenever a change isn't meant to move counts; compare hashes before and after rather than re-reading the data.

## Long runs

The full pipeline (~15 min) and `clusters.ipynb` (20–30 min) rewrite tracked files as they go. If a commit-on-stop hook or file watcher is active, don't run them inside the working tree. Run them against a copy and commit once at the end, so a half-finished `data/` is never committed and new facts arriving mid-run don't force a restart:

```bash
mkdir -p /tmp/cvr && cp -r data /tmp/cvr/
CVR_DATA_DIR=/tmp/cvr/data uv run python -m scripts.pipeline
CVR_DATA_DIR=/tmp/cvr/data uv run jupyter nbconvert --to notebook --execute --inplace clusters.ipynb
cp -r /tmp/cvr/data/. data/ && git add data && git commit
```

`CVR_DATA_DIR` moves every path in `scripts/config.py`, and the notebook reads it too. Provenance still records `data/...` paths. Run `git lfs pull` first: a checkout made with LFS smudging off leaves pointer files, and the copy inherits them.

## Layout

| Path | Responsibility |
| --- | --- |
| `scripts/config.py` | Path constants (`ORIGINAL_DIR`, `PROCESSED_DIR`, `CVR_DIR`, `CLUSTERS_DIR`, ...) |
| `scripts/sources.py` | `CvrSource` dataclass + `SOURCES` manifest tuple (election keys are lowercase `{year}-{type}`, type ∈ `ELECTION_TYPES` = general/primary/coordinated, shared with Election-Results; `data/original/` filenames are unchanged and mapped here); `ARCHIVED_ORIGINALS` for files kept but not processed (the CORA copy of 2023) |
| `scripts/loader.py` | `load_raw_cvr()` — reconstructs the Dominion 4-row header into a MultiIndex DataFrame; repairs mojibake in contest/candidate names (`ftfy.fix_encoding`); refuses LFS pointer files |
| `scripts/cleaner.py` | `clean_countywide()` — normalizes `BallotType` to text, rejects non-numeric contest cells, `split_redacted()` drops multi-ballot aggregates and keeps single redacted ballots (`_ID/redacted`), `combine_multisheet()` merges each voter's sheets (forward runs, then complementary/out-of-order runs), drops all-NaN contest cols, casts marks to `Int8`, integrity-checks, flattens columns. `detect_city_ballot_types()` is kept as a downstream helper. |
| `scripts/schema.py` | Pandera `ID_BLOCK_SCHEMA` (unique `voter_id`, `n_sheets >= 1`, text `BallotType`, IDs required on non-redacted rows) + `validate_id_block` + `validate_contest_columns` (blank/0/1 only; text fails). `scripts.clean` calls both. |
| `scripts/fetch.py` | Idempotent downloader. Stops with "run `git lfs pull`" if an original is an LFS pointer; **verifies** every file against `data/original/manifest.json` and fails on a mismatch (`--update-manifest` to accept a deliberate change); records `retrieved_at` at download, plus `obtained_at` (CORA, hand-entered), `first_committed_at` and the workbook's own timestamps. Never uses file mtimes. |
| `scripts/clean.py` | Orchestrator: walks each source, runs loader + cleaner + both validators, writes per-voter wide CSV, and **upserts** `provenance.csv` + `_summary.csv` by `election_key` (a `--election` subset run keeps the other rows). One failing election doesn't stop the rest; the run exits non-zero. |
| `scripts/audit.py` | Summary stats per processed CSV → `data/audit/summary.md` + `docs/variables.{md,csv}` |
| `scripts/reconcile.py` | Re-reads each original with calamine, re-applies the redaction rule, checks `_summary.csv` and every processed CSV (row count, unique `voter_id`, Σ `n_sheets`, redacted count, per-column mark totals); non-zero exit on mismatch. `--sov DIR` adds an informational Statement of Votes cross-check against Election-Results. |
| `scripts/publish.py` | Builds `data/processed/cast_vote_records.db` for Datasette + auto-generates `metadata.yaml` (opt-in) |
| `scripts/pipeline.py` | argparse CLI: `fetch|clean|audit|reconcile|publish|list`; default = full run |
| `tests/` | pytest suite on synthetic fixtures (xlsx and in-memory frames); no real-file dependency. Run `uv run pytest` for the current count rather than trusting a number written here. |
| `docs/data-dictionary.md` | Hand-maintained per-column documentation |
| `docs/filter-pivot-recipes.md` | pandas / R / SQL recipes for slicing the wide CSVs |
| `docs/methodology.md` | How the data is extracted, end-to-end |
| `docs/changelog.md` | Per-vintage notes (format drift, parser changes) |
| `docs/variables.{md,csv}` | Auto-generated column profile (do not hand-edit) |
| `data/original/` | LFS-tracked source xlsx + `manifest.json` |
| `data/processed/cast-vote-records/` | LFS-tracked per-voter CSVs `{year}-{type}-county-wide-by-voter.csv` + `_summary.csv` + `provenance.csv` |
| `data/processed/clusters/` | LFS-tracked `clusters.ipynb` outputs (`{key}-ballots-with-clusters.csv`, `{key}-cluster-profiles.csv`, the small-multiples PNG) + `provenance.csv` |
| `data/processed/` (root) | `cast_vote_records.db` + `metadata.yaml` when `publish build` runs (not committed) |
| `data/audit/` | Latest `summary.md` and `reconcile.md` (committed); per-run timestamped copies (gitignored) |
| `data/lookups/` | Crosswalks / code systems (empty for now) |
| `clusters.ipynb` | The McInnes two-pass UMAP + HDBSCAN small-multiples analysis |
| `.github/workflows/tests.yml` | Always-on: ruff + pytest on Python 3.11–3.13. No LFS objects. |
| `.github/workflows/reconcile.yml` | `reconcile` (plus the Election-Results SoV cross-check when that repo is reachable). Runs only when `data/original/`, `data/processed/cast-vote-records/`, `scripts/`, `pyproject.toml`, `uv.lock` or `.gitattributes` change, or by hand (`workflow_dispatch`). Pulls only the LFS files reconcile reads (~560 MB, not the clusters or the archived CORA copy of 2023) and caches them, so an unchanged-data run downloads nothing from LFS. |
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

## Redaction

The County protects ballot secrecy in two ways, and the cleaner treats them differently (`scripts.cleaner.split_redacted`; full table in [`docs/methodology.md` § Redaction](docs/methodology.md#redaction)):

* **Single redacted ballots** — identifiers blanked, marks intact. `CvrNumber` is `"Redacted"` (2024 Primary, 2025), `"RCV Redacted & Randomly Sorted"` (2023; mayoral RCV contest only), or `NaN` with every cell 0/1. **Kept**, flagged `_ID/redacted = True`, `voter_id = redacted-NNNNN`, never sheet-merged (no Tab/Batch/RecordId).
* **Aggregates** — several ballots summed into one row. `CvrNumber` contains "Consolidated"/"Aggregated" (2023+), or is the comma-separated list of the summed CVR numbers (2017, 2018 Primary), or any contest cell is > 1 (the `NaN`-label per-style rows of 2019–2022 and the 2021 `"DS-01"` summaries). **Dropped.**

`_summary.csv` reports both (`n_redacted_kept`, `n_aggregate_rows_dropped`). Never re-create blanked identifiers or restore the scan order of redacted rows; see the re-identification caveat in the methodology. The `min_ballots=5` threshold in `detect_city_ballot_types` is a defensive backstop against single aggregate rows.

## Design decisions

* **`scripts/` package, single analysis notebook.** The data-liberation convention is `scripts/` (not `src/` or the project name). The pipeline is callable, testable, and CI-friendly; the analysis is one notebook a critic can read top-to-bottom.
* **Per-voter primary output, not per-sheet.** Dominion CVRs export one row per ballot sheet ([NIST SP 1500-103 §3.5.2](https://doi.org/10.6028/NIST.SP.1500-103)). Multi-sheet ballots — the 2024 Boulder General used a two-sheet ballot for nearly every style — would over-count voters by their average sheet-count if kept per-sheet. The cleaner infers sheet identity per BallotType from contest-fill fingerprints, then walks `(Tab, Batch, RecordId)` order to merge each consecutive `(sheet K, sheet K+1)` run into one voter, then merges adjacent incomplete runs with complementary sheets (back page scanned first). Rare fingerprints (< 5% of a style) stay one-sheet voters and are counted in `_summary.csv`; styles with 3+ frequent fingerprints merge as 3+-sheet voters (none exist 2017–2025). Bookkeeping columns `_ID/n_sheets`, `_ID/voter_id` and `_ID/redacted` carry the merge metadata.
* **Countywide, not jurisdiction-filtered.** The pipeline emits every ballot in the county. Jurisdiction filtering (City of Boulder, Longmont, etc.) is done downstream in the analysis layer. `scripts.cleaner.detect_city_ballot_types` is kept available for the inverse operation (ballot-style → membership); `clusters.ipynb` does not use it, and filters by contest name instead.
* **Single loader, not vintage bands.** The Dominion export is structurally stable across 2017–2025; the 2017 and 2018 CORA releases are the same export saved as CSV, and `load_raw_cvr` picks the reader by extension. The only drift is the ID-column set (which `ID_LABELS` auto-detects) and the 2024 third-row party tags (which fall through the "not a known ID label" branch). One parser is defensible because the format actually didn't change.
* **Wide as the primary storage shape.** Per the data-liberation convention's note on ballot-level data, wide-by-key is correct when the ballot is the observation. A tidy long-form derivative is shown in `docs/filter-pivot-recipes.md`.
* **Empirical sheet-order wins over heuristics.** Within each BallotType, sheet 1 is whichever fingerprint appears first by RecordId in `(Tab, Batch)` groups (trusting the scanner). The contest-count heuristic (more non-null columns = sheet 1) is a sanity check; disagreement logs a warning rather than overriding.
* **Per-extract provenance, not per-row.** `data/processed/cast-vote-records/provenance.csv` keyed on `election_key`; `data/processed/clusters/provenance.csv` keyed on output file.
* **One key format across repos.** `election_key` is `{year}-{type}` in lowercase, exactly as in BoulderPublicData/Election-Results (`2024-general`), so the two datasets join without a crosswalk; `reconcile --sov` relies on it.
* **Reconcile at the published grain, with a second reader.** `reconcile` re-reads every original with calamine (the loader uses openpyxl) and re-applies the redaction rule from scratch. It then checks the totals of every contest-choice column against the raw file, and exits non-zero on any mismatch. Before 2026-10 it could not fail: a processed CSV truncated to its header still passed (#8). A new output column or table needs a matching reconcile check before it ships.
* **Immutable originals.** Files in `data/original/` are write-only from `scripts.fetch`. Re-running the cleaner does not touch them.
* **Errors durable, not fatal.** The CLI's `--fail-on-empty` flag turns silent regressions loud.

## How to add a new election

1. Place the xlsx in `data/original/<filename>` (or rely on `scripts.fetch` if it has a public URL).
2. Append a `CvrSource(...)` to `SOURCES` in `scripts/sources.py`.
3. Run `uv run python -m scripts.pipeline`, then `uv run python -m scripts.pipeline reconcile`.
4. Run `uv run pytest`.
5. Update `docs/changelog.md` with any vintage-specific notes.
6. Re-execute `clusters.ipynb` if you want the new election in the small-multiples.
7. Commit; LFS handles the binary blobs.

## Known limitations

* **Voter anonymity prevents panel analysis.** The redacted CVRs strip voter identifiers; the same voter cannot be tracked across years.
* **`HasIndication` vs `IsAllocable`; overvotes are invisible.** The cell value `1` is `HasIndication` as interpreted by contest rules. Across the eight 2019–2025 files (about 27 million contest-ballots; the 2017–2018 files are being checked) no contest ever has more marks than its "Vote For" limit, so an overvoted contest appears to be exported as all `0`s, indistinguishable from an undervote. Analyses of invalidated marks need the *original* or *modified* snapshot, neither of which Boulder publishes.
* **NaN-vs-0 semantics.** `NaN` = "contest not on this voter's ballot style"; `0` = "contest was on the ballot, voter did not mark this choice." The clustering pipeline collapses `NaN → 0` for embedding; preserve the distinction from the wide CSV when undervote analysis matters.
* **Schema drift across vintages.** ID column sets differ across years; the pandera schema is permissive on optional ID columns.
* **The 2018 and 2024 Primaries have no City of Boulder contests.** They are partisan state primaries, so City-level analyses (e.g. `clusters.ipynb`) skip them. The countywide per-voter CSVs are complete (2018: 84,977 voters × 53 contest-choice columns; 2024: 65,787 voters × 30).
* **No 2020 or 2022 Primary, or 2024 Presidential Primary.** They haven't been requested or added (the 2024 Presidential Primary CVR is on the County's 2024 page).
* **Reconcile checks the CVR against itself, not the official count.** `scripts.reconcile` re-derives row counts and per-column mark totals from the originals with a second parser and fails on any difference. The Statement of Votes comparison (`--sov`, against Election-Results) is informational only: the SoV counts aggregated ballots that are not in the per-voter rows.
* **Redacted ballots are not sheet-merged.** They have no scan position, so a redacted sheet of a multi-sheet ballot stays its own row (`n_redacted_in_multisheet_styles`, 0 in 2019–2025).

## Future work

* **Tidy long derivative** in `data/processed/cast_vote_records.parquet`.
* **Per-contest vote-total reconciliation in CI** against the official Statement of Votes (the `--sov` cross-check exists; it needs the Election-Results CSVs checked out alongside).
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

Code: MIT. Data: public records released by the Boulder County Clerk and Recorder (publicly posted 2023–2025; 2017–2022 obtained via Colorado Open Records Act disclosure). Per data-liberation convention, the data is republished here under CC-BY-4.0.
