"""Manifest of every CVR processed by the pipeline.

Each :class:`CvrSource` names one election's CVR file in ``data/original/``
and records its provenance (CORA disclosure or public URL). When a new
election becomes available, append a new entry; the CLI picks it up
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

ELECTION_TYPES: tuple[str, ...] = ("general", "primary", "coordinated")
"""Shared election-type vocabulary with Election-Results."""


@dataclass(frozen=True)
class CvrSource:
    """One election's CVR file and provenance."""

    election_key: str
    """``{year}-{election_type}``, lowercase (e.g. ``2023-coordinated``): the
    same key format as BoulderPublicData/Election-Results. Used in output
    filenames, ``_summary.csv``/``provenance.csv`` and the CLI ``-e`` flag."""

    year: int
    election_type: str
    """One of :data:`ELECTION_TYPES`: ``coordinated`` (odd-year, municipal),
    ``general`` or ``primary``."""

    filename: str
    """Filename inside ``data/original/`` (not a path)."""

    public_url: str | None
    """Direct download URL on ``assets.bouldercounty.gov`` if the County has
    posted this CVR publicly; ``None`` if the file came from a Colorado Open
    Records Act (CORA) disclosure and is not on the County website."""

    notes: str = ""

    obtained_at: str = ""
    """For CORA disclosures: the date the County released the file, entered by
    hand from the CORA response (ISO 8601). Blank when not recorded; the
    manifest's ``first_committed_at`` is then the best available upper bound."""


@dataclass(frozen=True)
class ArchivedOriginal:
    """A file kept in ``data/original/`` for provenance but not processed."""

    filename: str
    notes: str
    obtained_at: str = ""


ARCHIVED_ORIGINALS: tuple[ArchivedOriginal, ...] = (
    ArchivedOriginal(
        "2023-CVR.xlsx",
        notes=(
            "CORA copy of the 2023 Coordinated CVR. Same 118,787 rows, columns "
            "and ballots as the public 2023-Coordinated-CVR.xlsx: the two files "
            "hold an identical multiset of rows once CvrNumber (a row sequence "
            "number) is ignored, but in a different row order, and the workbook "
            "was re-saved 2023-12-01 (public copy: 2023-11-28). Not processed, "
            "because it would duplicate the public file; kept so the CORA "
            "release is archived."
        ),
    ),
)
"""Originals that are archived but deliberately not in :data:`SOURCES`."""


SOURCES: tuple[CvrSource, ...] = (
    CvrSource(
        "2019-coordinated", 2019, "coordinated",
        "2019-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2020-general", 2020, "general",
        "2020-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2021-coordinated", 2021, "coordinated",
        "2021-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2022-general", 2022, "general",
        "2022-CVR.xlsx",
        public_url=None,
        notes="CORA disclosure; not on bouldercounty.gov by-year pages.",
    ),
    CvrSource(
        "2023-coordinated", 2023, "coordinated",
        "2023-Coordinated-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2023/11/Redacted-2023Coordinated-CVR.xlsx",
        notes="First publicly posted Boulder County CVR.",
    ),
    CvrSource(
        "2024-primary", 2024, "primary",
        "2024-Primary-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2024/07/2024-Boulder-County-June-Primary-Election-CVR.xlsx",
        notes=(
            "Partisan state primary; no City of Boulder contests (City-level "
            "analyses skip it). Countywide rows retained."
        ),
    ),
    CvrSource(
        "2024-general", 2024, "general",
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
        "2025-coordinated", 2025, "coordinated",
        "2025-Coordinated-CVR.xlsx",
        public_url="https://assets.bouldercounty.gov/wp-content/uploads/2025/12/Redacted-CVR-PUBLIC.xlsx",
        notes="",
    ),
)


def get_source(election_key: str) -> CvrSource:
    """Return the :class:`CvrSource` for ``election_key`` or raise ``KeyError``.

    An old-style key (``2024-General``) raises with a hint naming the new one.
    """
    for src in SOURCES:
        if src.election_key == election_key:
            return src
    lowered = election_key.lower()
    if any(src.election_key == lowered for src in SOURCES):
        raise KeyError(f"{election_key!r}: election keys are lowercase now; use {lowered!r}")
    known = ", ".join(s.election_key for s in SOURCES)
    raise KeyError(f"{election_key!r} is not a known election ({known})")


def sources_for_years(years) -> tuple[CvrSource, ...]:
    """Every source whose ``year`` is in ``years``."""
    years = {int(y) for y in years}
    return tuple(s for s in SOURCES if s.year in years)
