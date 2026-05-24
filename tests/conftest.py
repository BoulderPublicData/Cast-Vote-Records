"""Synthetic CVR fixtures.

The fixtures build a minimal xlsx that mirrors the four-row Boulder County
header layout, so loader/cleaner tests do not depend on the (large, public)
real files in ``data/original/``.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np

import pandas as pd
import pytest


def _build_minimal_cvr(path: Path) -> None:
    """Write a small synthetic CVR xlsx to ``path``.

    Structure mirrors a coordinated-election CVR:
        * 6 ID columns ending with BallotType
        * 1 City of Boulder contest (3 candidates)
        * 1 Longmont contest (2 candidates)
        * 12 City of Boulder ballots (``DS-01``), 6 Longmont ballots
          (``DS-02``), 1 sentinel-string redacted row, 1 NaN-CvrNumber
          aggregate row, 1 NaN-TabulatorNum 2021-style summary row
    """
    rows: list[list[object]] = []
    nan = np.nan

    rows.append(["Synthetic Test Election", "5.17.17.1", nan, nan, nan, nan,
                 nan, nan, nan, nan, nan])
    cob = "City of Boulder Council Candidates (Vote For=1)"
    lmt = "City of Longmont - Mayor (Vote For=1)"
    rows.append([nan, nan, nan, nan, nan, nan,
                 cob, cob, cob, lmt, lmt])
    rows.append([nan, nan, nan, nan, nan, nan,
                 "Alice", "Bob", "Carol", "Dana", "Eve"])
    rows.append(["CvrNumber", "TabulatorNum", "BatchId", "RecordId",
                 "ImprintedId", "BallotType",
                 nan, nan, nan, nan, nan])

    # 12 City of Boulder voters (DS-01)
    city_votes = [
        (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0),
        (0, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0),
        (0, 1, 0), (0, 0, 1), (1, 0, 0), (0, 1, 0),
    ]
    for i, (a, b, c) in enumerate(city_votes, start=1):
        rows.append([str(i), "100", "1", str(i), f"100-1-{i}", "DS-01",
                     a, b, c, nan, nan])

    # 6 Longmont voters (DS-02)
    long_votes = [(1, 0), (0, 1), (1, 0), (0, 1), (1, 0), (0, 1)]
    for j, (d, e) in enumerate(long_votes, start=20):
        rows.append([str(j), "100", "1", str(j), f"100-1-{j}", "DS-02",
                     nan, nan, nan, d, e])

    # 1 redacted privacy aggregate row (sentinel string CvrNumber)
    rows.append(["RCV Redacted & Randomly Sorted", nan, nan, nan, nan, "DS-01",
                 0, 0, 0, nan, nan])
    # 1 privacy aggregate row with NaN CvrNumber (2022-style)
    rows.append([nan, nan, nan, nan, nan, "DS-02",
                 0, 0, 0, nan, nan])
    # 1 2021-style per-style summary row (NaN TabulatorNum, CvrNumber holds
    # the ballot-style code)
    rows.append(["DS-01", nan, nan, nan, nan, "DS-01",
                 0, 0, 0, nan, nan])

    df = pd.DataFrame(rows)
    df.to_excel(path, header=False, index=False)


@pytest.fixture()
def minimal_cvr_path(tmp_path: Path) -> Path:
    p = tmp_path / "mini.xlsx"
    _build_minimal_cvr(p)
    return p


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
