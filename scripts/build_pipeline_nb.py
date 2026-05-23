"""Assemble 01_pipeline.ipynb from a list of cells."""
import json
from pathlib import Path

cells = []

def md(src):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)})

def code(src):
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": src.splitlines(keepends=True),
    })

md("""# Cast Vote Records: Pipeline
[Brian C. Keegan, Ph.D.](http://www.brianckeegan.com)
May 2026

Released under a [MIT License](https://opensource.org/licenses/MIT).
""")

md("""This notebook downloads, inspects, cleans, and tidies the redacted Cast Vote Records (CVRs) published by the [Boulder County Clerk and Recorder](https://bouldercounty.gov/elections/). For each election with a publicly available CVR, it produces a wide-format CSV in `data/clean/` containing one row per City of Boulder ballot and one column per contest-choice.

Boulder County began publishing redacted ballot-level CVRs with the [2023 Coordinated Election](https://bouldercounty.gov/elections/by-year/2023-election/); earlier elections (2019–2022) are not posted on the County's by-year pages. The companion [`02_clusters.ipynb`](02_clusters.ipynb) consumes these wide CSVs and runs a twin-path UMAP / HDBSCAN analysis on City of Boulder voting patterns.

**Uncommon libraries.** Only `openpyxl` (for `.xlsx` reading) and `requests` (for downloads) beyond the standard data stack. Install via `pip install -r requirements.txt`.
""")

code("""import pandas as pd
import numpy as np

pd.options.display.max_columns = 100

%matplotlib inline
import seaborn as sb
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

import requests
from pathlib import Path
""")

md("""## Data sources

Three CVRs are publicly published by the Boulder County Clerk on `assets.bouldercounty.gov`:

- **2023 Coordinated** — [Redacted-2023Coordinated-CVR.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx) ([source page](https://bouldercounty.gov/elections/by-year/2023-election/))
- **2024 General** (pre-recount) — [2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx) ([source page](https://bouldercounty.gov/elections/by-year/2024-election/))
- **2025 Coordinated** — [Redacted-CVR-PUBLIC.xlsx](https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx) ([source page](https://bouldercounty.gov/elections/by-year/2025-election/))

The download cell below fetches each xlsx into `data/raw/`, which is gitignored. Re-running the cell is a no-op when the file already exists. The 2024 Primary, Presidential Primary, and General Recount CVRs exist but are excluded from this pipeline by design — see the README.
""")

code("""RAW_DIR = Path('data/raw')
CLEAN_DIR = Path('data/clean')
RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DIR.mkdir(parents=True, exist_ok=True)

CVR_SOURCES = {
    '2023-Coordinated': {
        'url': 'https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx',
        'filename': '2023-Coordinated-CVR.xlsx',
        'city_ballot_type': 'DS-01',
    },
    '2024-General': {
        'url': 'https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx',
        'filename': '2024-General-CVR.xlsx',
        'city_ballot_type': '01',
    },
    '2025-Coordinated': {
        'url': 'https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx',
        'filename': '2025-Coordinated-CVR.xlsx',
        'city_ballot_type': '01',
    },
}

def download_cvr(election_key):
    src = CVR_SOURCES[election_key]
    dest = RAW_DIR / src['filename']
    if dest.exists() and dest.stat().st_size > 0:
        print(f'  already present: {dest} ({dest.stat().st_size/1e6:.1f} MB)')
        return dest
    print(f'  downloading {src[\"url\"]}')
    r = requests.get(src['url'], timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f'  saved: {dest} ({dest.stat().st_size/1e6:.1f} MB)')
    return dest

for key in CVR_SOURCES:
    download_cvr(key)
""")

md("""## Header reconstruction

Every Boulder County CVR has the same four-row prelude before the data starts:

| row | content |
| --- | --- |
| 0 | election title and Dominion software version |
| 1 | contest name (repeated across the columns belonging to that contest) |
| 2 | candidate or choice name |
| 3 | ID column labels (`CvrNumber`, `TabulatorNum`, `BatchId`, `RecordId`, `ImprintedId`, optional `CountingGroup`, `BallotType`) for the first 6–7 columns; party abbreviation (`DEM`, `REP`, etc.) for partisan contest columns in some years; `NaN` otherwise |

Data begins at row 4. The function below reconstructs a clean `MultiIndex` of `('_ID', label)` for identification columns and `(contest, candidate)` for ballot-choice columns, then strips the header rows out of the data frame.

The two-pass header is deliberate: 2023 and 2025 have `NaN` at row 3 over the contest columns, but 2024 has party abbreviations there. Treating *only* the seven canonical ID strings as ID columns makes the parser robust across years.
""")

code("""ID_LABELS = {
    'CvrNumber', 'TabulatorNum', 'BatchId', 'RecordId',
    'ImprintedId', 'CountingGroup', 'BallotType',
}

REDACTED_VALUES = {
    'RCV Redacted & Randomly Sorted',
    'Redacted & Aggregated',
}

def load_raw_cvr(path):
    \"\"\"Read a Boulder County redacted CVR xlsx into a wide DataFrame.

    The columns are a MultiIndex: ('_ID', label) for identification columns,
    (contest, candidate) for ballot-choice columns. Rows are ballots.
    \"\"\"
    raw = pd.read_excel(path, header=None)
    contest_row = raw.iloc[1]
    candidate_row = raw.iloc[2]
    label_row = raw.iloc[3]

    cols = []
    for i in range(len(raw.columns)):
        lab = label_row.iloc[i]
        if pd.notna(lab) and lab in ID_LABELS:
            cols.append(('_ID', lab))
        else:
            cols.append((contest_row.iloc[i], candidate_row.iloc[i]))

    df = raw.iloc[4:].reset_index(drop=True)
    df.columns = pd.MultiIndex.from_tuples(cols)
    return df
""")

md("""## City of Boulder filter and tidy

The City of Boulder ballot is the ballot style that contains every City of Boulder municipal contest. Across years, this corresponds to a different code:

| year | City of Boulder ballot type | n ballots |
| --- | --- | --- |
| 2023 Coordinated | `'DS-01'` | ~34,100 |
| 2024 General | `'01'` | ~85,000 |
| 2025 Coordinated | `'01'` | ~34,000 |

Boulder County also publishes a small number of *aggregated* and *RCV-randomly-sorted* rows that aggregate small-precinct ballots for privacy; these are dropped (they cannot represent any single voter). After filtering and dropping ballot-choice columns that are all-`NaN` for the City subset, every remaining column corresponds to a contest that City of Boulder voters could actually vote on.
""")

code("""def clean_city_cvr(raw_df, city_ballot_type, election_key):
    \"\"\"Filter a raw CVR to City of Boulder ballots and return a tidied wide DataFrame.

    Steps:
        1. drop privacy-redacted aggregate rows
        2. filter rows where BallotType == the city's code for that year
        3. drop ballot-choice columns that are entirely NaN for the city subset
        4. integrity-check row count and ID columns
        5. flatten the MultiIndex columns to 'Contest::Choice' (with '_ID/<name>' for IDs)
    \"\"\"
    df = raw_df.copy()

    # 1. Drop privacy-redacted aggregate rows (CvrNumber holds the redaction string)
    cvr_col = ('_ID', 'CvrNumber')
    before = len(df)
    df = df[~df[cvr_col].astype(str).isin(REDACTED_VALUES)]
    n_redacted = before - len(df)

    # 2. Filter to City of Boulder ballot type
    bt_col = ('_ID', 'BallotType')
    bt_values = df[bt_col].astype(str)
    city_mask = bt_values == str(city_ballot_type)
    city_df = df[city_mask].copy()

    # 3. Drop ballot-choice columns that are entirely NaN for the city subset
    keep = []
    for c in city_df.columns:
        if c[0] == '_ID':
            keep.append(c)
        elif city_df[c].notna().any():
            keep.append(c)
    city_df = city_df.loc[:, keep]

    # 4. Integrity checks
    assert len(city_df) > 0, f'no rows after filter for {election_key}'
    for required in ('CvrNumber', 'TabulatorNum', 'BallotType'):
        assert ('_ID', required) in city_df.columns, f'{election_key} missing {required}'
    assert (city_df[bt_col].astype(str) == str(city_ballot_type)).all(), \
        f'{election_key} has non-city ballot types after filter'

    # 5. Flatten columns
    flat_cols = []
    for c in city_df.columns:
        if c[0] == '_ID':
            flat_cols.append(f'_ID/{c[1]}')
        else:
            flat_cols.append(f'{c[0]}::{c[1]}')
    out = city_df.copy()
    out.columns = flat_cols

    print(f'  {election_key}: dropped {n_redacted} redacted row(s); '
          f'{city_mask.sum():,} city ballots; '
          f'{sum(1 for c in flat_cols if not c.startswith(\"_ID/\")):,} ballot-choice columns')
    return out
""")

md("""## 2023 Coordinated Election

The 2023 Coordinated was the first Boulder County election with a publicly published CVR. The City of Boulder ballot (`DS-01`) carried four ranked-choice rounds for mayor (Brockett / Speer / Yates / Tweedlie), a four-seat at-large council race, two municipal ballot questions, and Boulder Valley School District board races.
""")

code("""raw_2023 = load_raw_cvr('data/raw/2023-Coordinated-CVR.xlsx')
print(f'2023 Coordinated raw shape: {raw_2023.shape[0]:,} ballots × {raw_2023.shape[1]} columns')
raw_2023[('_ID', 'BallotType')].value_counts(dropna=False).head(10)
""")

code("""clean_2023 = clean_city_cvr(raw_2023, city_ballot_type='DS-01', election_key='2023-Coordinated')
clean_2023.to_csv('data/clean/2023-Coordinated-city-of-boulder-wide.csv', index=False)
print(f'  saved: data/clean/2023-Coordinated-city-of-boulder-wide.csv')
clean_2023.iloc[:5, :8]
""")

md("""## 2024 Boulder County General Election

The 2024 General was a high-turnout federal/state cycle with a presidential race, County Commissioner contests, three City of Boulder ballot questions (2C, 2D, 2E), and judicial retention votes. City of Boulder ballots are coded `'01'` in this CVR. The pre-recount version is used; the [post-recount CVR](https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Recount-Redacted-Cast-Vote-Record.xlsx) exists separately.
""")

code("""raw_2024 = load_raw_cvr('data/raw/2024-General-CVR.xlsx')
print(f'2024 General raw shape: {raw_2024.shape[0]:,} ballots × {raw_2024.shape[1]} columns')
raw_2024[('_ID', 'BallotType')].value_counts(dropna=False).head(10)
""")

code("""clean_2024 = clean_city_cvr(raw_2024, city_ballot_type='01', election_key='2024-General')
clean_2024.to_csv('data/clean/2024-General-city-of-boulder-wide.csv', index=False)
print(f'  saved: data/clean/2024-General-city-of-boulder-wide.csv')
clean_2024.iloc[:5, :8]
""")

md("""## 2025 Coordinated Election

The 2025 Coordinated had a four-seat City of Boulder Council race, two City of Boulder ballot issues (2A, 2B), and two county-wide measures (1A, 1B). City of Boulder ballots are again coded `'01'`.
""")

code("""raw_2025 = load_raw_cvr('data/raw/2025-Coordinated-CVR.xlsx')
print(f'2025 Coordinated raw shape: {raw_2025.shape[0]:,} ballots × {raw_2025.shape[1]} columns')
raw_2025[('_ID', 'BallotType')].value_counts(dropna=False).head(10)
""")

code("""clean_2025 = clean_city_cvr(raw_2025, city_ballot_type='01', election_key='2025-Coordinated')
clean_2025.to_csv('data/clean/2025-Coordinated-city-of-boulder-wide.csv', index=False)
print(f'  saved: data/clean/2025-Coordinated-city-of-boulder-wide.csv')
clean_2025.iloc[:5, :8]
""")

md("""## Summary

The three cleaned wide CSVs are the input to [`02_clusters.ipynb`](02_clusters.ipynb). The table below pins the headline shape of each: `n_ballots` is the number of City of Boulder ballots and `n_contest_cols` is the number of distinct contest-choice columns (a ranked-choice race contributes `n_candidates × n_rounds` columns).
""")

code("""summary = []
for election_key, df_clean in [
    ('2023-Coordinated', clean_2023),
    ('2024-General',     clean_2024),
    ('2025-Coordinated', clean_2025),
]:
    n_id = sum(1 for c in df_clean.columns if c.startswith('_ID/'))
    n_contest = df_clean.shape[1] - n_id
    contests = sorted({c.split('::')[0] for c in df_clean.columns if not c.startswith('_ID/')})
    summary.append({
        'election': election_key,
        'n_ballots': len(df_clean),
        'n_id_cols': n_id,
        'n_contest_cols': n_contest,
        'n_distinct_contests': len(contests),
    })
summary_df = pd.DataFrame(summary).set_index('election')
summary_df
""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
Path('/Users/briankeegan/Documents/GitHub/Cast-Vote-Records/01_pipeline.ipynb').write_text(json.dumps(nb, indent=1))
print(f'wrote 01_pipeline.ipynb with {len(cells)} cells')
