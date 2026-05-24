"""Tests for the vectorized contest-fill fingerprint."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.cleaner import _row_fingerprints


def test_empty_input_returns_empty_array():
    out = _row_fingerprints(np.zeros((0, 5), dtype=bool))
    assert out.shape == (0,)
    assert out.dtype == np.int64


def test_single_row_returns_single_code():
    out = _row_fingerprints(np.array([[True, False, True, False]]))
    assert out.shape == (1,)
    assert out.dtype == np.int64


def test_identical_rows_share_fingerprint():
    notna = np.array([
        [True, False, True, False],
        [True, False, True, False],
        [True, False, True, False],
    ])
    out = _row_fingerprints(notna)
    assert len(set(out.tolist())) == 1


def test_different_rows_get_different_fingerprints():
    notna = np.array([
        [True, False, True, False],   # pattern A
        [False, True, False, True],   # pattern B (disjoint)
        [True, False, True, False],   # pattern A again
        [True, True, True, True],     # pattern C (full)
    ])
    out = _row_fingerprints(notna)
    assert out[0] == out[2]
    assert out[0] != out[1]
    assert out[0] != out[3]
    assert out[1] != out[3]
    # Three distinct patterns → three distinct codes
    assert len(set(out.tolist())) == 3


def test_codes_are_dense_zero_indexed_integers():
    """numpy.unique with return_inverse gives codes 0..K-1 for K distinct rows."""
    notna = np.array([
        [True, False],   # A
        [False, True],   # B
        [True, False],   # A
        [False, False],  # C
    ])
    out = _row_fingerprints(notna)
    assert set(out.tolist()) == {0, 1, 2}


def test_handles_wide_array_more_than_64_columns():
    """Packed-bytes approach must work for row widths > 64 (multiple int64s)."""
    n_rows, n_cols = 100, 200
    rng = np.random.default_rng(seed=42)
    notna = rng.random((n_rows, n_cols)) > 0.5
    out = _row_fingerprints(notna)
    assert out.shape == (n_rows,)
    # Sanity: rows that are identical should produce identical codes
    notna[1] = notna[0]
    out2 = _row_fingerprints(notna)
    assert out2[0] == out2[1]


def test_handles_non_bool_input():
    """Should coerce a 0/1 int array to bool before packing."""
    notna_int = np.array([
        [1, 0, 1, 0],
        [0, 1, 0, 1],
        [1, 0, 1, 0],
    ], dtype=np.int8)
    out = _row_fingerprints(notna_int)
    assert out[0] == out[2]
    assert out[0] != out[1]


def test_deterministic_across_calls():
    """Same input must produce identical codes on repeated calls."""
    rng = np.random.default_rng(seed=7)
    notna = rng.random((500, 30)) > 0.3
    out1 = _row_fingerprints(notna)
    out2 = _row_fingerprints(notna)
    np.testing.assert_array_equal(out1, out2)


def test_scales_to_large_input_quickly():
    """Smoke-test the vectorized path on ~400k rows × 165 cols (the 2024
    General CVR shape). The pre-vectorization per-row hashlib.md5 loop took
    ~60 s on this size; the vectorized path should complete in well under
    a few seconds."""
    import time
    rng = np.random.default_rng(seed=0)
    notna = rng.random((400_000, 165)) > 0.7
    t0 = time.perf_counter()
    out = _row_fingerprints(notna)
    elapsed = time.perf_counter() - t0
    assert out.shape == (400_000,)
    # Generous ceiling; on real hardware this runs in << 1 s
    assert elapsed < 10.0, f"vectorized fingerprint too slow: {elapsed:.2f}s"


def test_packing_boundary_at_8_columns():
    """np.packbits packs into bytes; verify rows that differ only past the
    first byte get distinct codes."""
    # Two rows that agree on the first 8 cols, differ on column 9
    a = np.array([[True] * 8 + [True, False, False, False]])
    b = np.array([[True] * 8 + [False, False, False, False]])
    out = _row_fingerprints(np.vstack([a, b]))
    assert out[0] != out[1]
