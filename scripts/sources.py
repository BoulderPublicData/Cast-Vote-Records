"""Manifest of every CVR processed by the pipeline.

Each :class:`CvrSource` names one election's CVR file in ``data/original/``
and records its provenance (CORA disclosure or public URL). When a new
election becomes available, append a new entry; the CLI picks it up
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CvrSource:
    """One election's CVR file and provenance."""

    election_key: str
    """Slug used in output filenames (e.g. ``2023-Coordinated``)."""

    year: int
    election_type: str
    """``'Coordinated'`` (odd-year, municipal) or ``'General'`` / ``'Primary'``."""

    filename: str
    """Filename inside ``data/original/`` (not a path)."""

    public_url: Optional[str]
    """Direct download URL on ``assets.bouldercounty.gov`` if the County has
    posted this CVR publicly; ``None`` if the file came from a Colorado Open
    Records Act (CORA) disclosure and is not on the County website."""

    notes: str = ""


SOURCES: tuple[CvrSource, ...] = (
    CvrSource(
        "2019-Coordinated", 2019, "Coordinated",
        "2019-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2020-General", 2020, "General",
        "2020-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2021-Coordinated", 2021, "Coordinated",
        "2021-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2022-General", 2022, "General",
        "2022-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2023-Coordinated", 2023, "Coordinated",
        "2023-Coordinated-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx",
        notes="First publicly posted Boulder County CVR.",
    ),
    CvrSource(
        "2024-Primary", 2024, "Primary",
        "2024-Primary-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx",
        notes="Partisan state primary; contains no City of Boulder municipal contests, so the pipeline produces an empty clean CSV.",
    ),
    CvrSource(
        "2024-General", 2024, "General",
        "2024-General-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2025/01/2024-Boulder-County-General-Redacted-Cast-Vote-Record.xlsx",
        notes=(
            "Pre-recount version. In NIST CDF terms (SP 1500-103 §3.3) this is "
            "the *interpreted* snapshot; the County also published a separate "
            "post-recount CVR that would correspond to the *modified* snapshot "
            "(adjudication-driven changes). Excluded by design — the pre-recount "
            "version is the input most other published analyses use."
        ),
    ),
    CvrSource(
        "2025-Coordinated", 2025, "Coordinated",
        "2025-Coordinated-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx",
        notes="",
    ),
)


def get_source(election_key: str) -> CvrSource:
    """Return the :class:`CvrSource` for ``election_key`` or raise ``KeyError``."""
    for src in SOURCES:
        if src.election_key == election_key:
            return src
    raise KeyError(election_key)
