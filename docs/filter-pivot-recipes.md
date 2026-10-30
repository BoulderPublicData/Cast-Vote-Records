# Filter and pivot recipes

The wide CSVs in ``data/processed/cast-vote-records/`` (`<election>-county-wide-by-voter.csv`, where `<election>` is a lowercase key such as `2024-general`) have one row per **voter** (all of that voter's ballot sheets merged) and one column per contest-choice. Every file is **countywide**, so filter to a jurisdiction yourself (below). These recipes show how to slice and reshape them.

Two typing notes for every recipe:

* Read `_ID/BallotType` as **text**. Codes like `01` otherwise become the number `1`.
* `_ID/TabulatorNum`, `_ID/BatchId` and `_ID/RecordId` are blank on redacted ballots (`_ID/redacted = True`). pandas therefore reads them as floats. Pass `dtype=str` for those columns too if you need them as identifiers.

## Load one election

### pandas

```python
import pandas as pd

df = pd.read_csv(
    "data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv",
    dtype={"_ID/BallotType": str},
    low_memory=False,
)
df.shape
```

### R / tidyverse

```r
library(readr)
df <- read_csv("data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv",
               col_types = cols(`_ID/BallotType` = col_character()),
               show_col_types = FALSE)
```

### DuckDB

```sql
SELECT * FROM read_csv('data/processed/cast-vote-records/2023-coordinated-county-wide-by-voter.csv',
                       types = {'_ID/BallotType': 'VARCHAR'}) LIMIT 5;
```

## Filter to City of Boulder voters

A voter is a City of Boulder voter when at least one City of Boulder contest was on their ballot style, i.e. that contest's cells are not blank. Filtering by contest name avoids the ballot-style codes, which change every year.

### pandas

```python
city_cols = [c for c in df.columns if "City of Boulder" in c]
city = df[df[city_cols].notna().any(axis=1)]
```

### R / tidyverse

```r
library(dplyr)
city_cols <- grep("City of Boulder", names(df), value = TRUE)
city <- df |> filter(if_any(all_of(city_cols), \(x) !is.na(x)))
```

Replace `"City of Boulder"` with `"City of Longmont"`, `"Town of Superior"`, and so on, for other jurisdictions. The 2024 Primary has no City of Boulder contests, so this filter returns no rows there.

To leave out redacted ballots (identifiers blanked by the County; in 2023 they hold only the mayoral ranking), add `city = city[~city["_ID/redacted"]]`.

## Vote share for one contest

The share among voters who had the contest on their ballot. Blank cells (not on the ballot) are skipped by `mean`:

### pandas

```python
mayor_cols = [c for c in city.columns if c.startswith("City of Boulder Mayoral Candidates")]
city[mayor_cols].mean().sort_values(ascending=False)
```

### R / tidyverse

```r
library(dplyr); library(tidyr)
city |>
  select(starts_with("City of Boulder Mayoral Candidates")) |>
  summarise(across(everything(), \(x) mean(x, na.rm = TRUE))) |>
  pivot_longer(everything(), names_to = "choice", values_to = "share") |>
  arrange(desc(share))
```

## Wide → tidy long

### pandas

```python
id_cols = [c for c in df.columns if c.startswith("_ID/")]
choice_cols = [c for c in df.columns if not c.startswith("_ID/")]

long = df.melt(
    id_vars=id_cols, value_vars=choice_cols, var_name="contest_choice", value_name="mark"
).dropna(subset=["mark"])
long[["contest", "choice"]] = long["contest_choice"].str.split("::", n=1, expand=True)
long = long.drop(columns="contest_choice")
```

### R / tidyverse

```r
library(tidyr)
long <- df |>
  pivot_longer(cols = -starts_with("_ID/"),
               names_to = "contest_choice", values_to = "mark",
               values_drop_na = TRUE) |>
  separate(contest_choice, into = c("contest", "choice"), sep = "::")
```

## Pool across elections

### pandas

```python
from pathlib import Path

frames = []
for path in sorted(Path("data/processed/cast-vote-records").glob("*-county-wide-by-voter.csv")):
    election = path.name.removesuffix("-county-wide-by-voter.csv")
    df = pd.read_csv(path, dtype={"_ID/BallotType": str}, low_memory=False)
    id_cols = [c for c in df.columns if c.startswith("_ID/")]
    choice_cols = [c for c in df.columns if not c.startswith("_ID/")]
    long = df.melt(
        id_vars=id_cols, value_vars=choice_cols, var_name="contest_choice", value_name="mark"
    ).dropna(subset=["mark"])
    long["election"] = election
    frames.append(long)
all_long = pd.concat(frames, ignore_index=True)
```

The long table of all eleven elections has tens of millions of rows. Filter each election (e.g. to City of Boulder) before melting if memory is tight.

## Undervote vs ineligible

`0` = eligible but left blank; blank cell = not on the ballot:

```python
contest = "City of Boulder Ballot Issue 2A (Vote For=1)::Yes/For"
df[contest].value_counts(dropna=False)
```

A contest-level undervote is a voter whose cells for that contest are **all** `0`. In these exports, an overvoted contest also appears as all `0`, so the two cannot be told apart (see the glossary in the [README](../README.md#glossary)).

## Join cluster labels

```python
clusters = pd.read_csv(
    "data/processed/clusters/2023-coordinated-ballots-with-clusters.csv",
    usecols=["_ID/voter_id", "cluster"],
)
df = df.merge(clusters, on="_ID/voter_id", how="left")  # NaN cluster = not clustered
```
