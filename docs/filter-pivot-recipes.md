# Filter and pivot recipes

The wide CSVs in ``data/processed/`` are one row per ballot, one column per contest-choice. These recipes show how to slice and reshape them.

## Load one election

### pandas

```python
import pandas as pd
df = pd.read_csv("data/processed/2023-Coordinated-city-of-boulder-wide.csv",
                 low_memory=False)
df.shape
```

### R / tidyverse

```r
library(readr)
df <- read_csv("data/processed/2023-Coordinated-city-of-boulder-wide.csv",
               show_col_types = FALSE)
```

### DuckDB

```sql
SELECT * FROM read_csv_auto('data/processed/2023-Coordinated-city-of-boulder-wide.csv') LIMIT 5;
```

## Vote share for one contest

### pandas

```python
mayor_cols = [c for c in df.columns
              if c.startswith("City of Boulder Mayoral Candidates")]
df[mayor_cols].mean().sort_values(ascending=False)
```

### R / tidyverse

```r
library(dplyr); library(tidyr)
df |>
  select(starts_with("City of Boulder Mayoral Candidates")) |>
  summarise(across(everything(), \(x) mean(x, na.rm = TRUE))) |>
  pivot_longer(everything(), names_to = "choice", values_to = "share") |>
  arrange(desc(share))
```

## Wide → tidy long

### pandas

```python
id_cols     = [c for c in df.columns if c.startswith("_ID/")]
choice_cols = [c for c in df.columns if not c.startswith("_ID/")]

long = (df.melt(id_vars=id_cols, value_vars=choice_cols,
                var_name="contest_choice", value_name="mark")
          .dropna(subset=["mark"]))
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
for path in sorted(Path("data/processed").glob("*-city-of-boulder-wide.csv")):
    election = path.name.removesuffix("-city-of-boulder-wide.csv")
    df = pd.read_csv(path, low_memory=False)
    id_cols     = [c for c in df.columns if c.startswith("_ID/")]
    choice_cols = [c for c in df.columns if not c.startswith("_ID/")]
    long = (df.melt(id_vars=id_cols, value_vars=choice_cols,
                    var_name="contest_choice", value_name="mark")
              .dropna(subset=["mark"]))
    long["election"] = election
    frames.append(long)
all_long = pd.concat(frames, ignore_index=True)
```

## Undervote vs ineligible

`0` = eligible-but-blank; `NaN` = not on the ballot:

```python
contest = "City of Boulder Ballot Issue 2A (Vote For=1)::Yes"
df[contest].value_counts(dropna=False)
```
