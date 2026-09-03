#!/usr/bin/env python3
"""Self-check for the vector index. No network: vectors are supplied directly.
Run: uv run python scripts/test_vector_index.py"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vector_index as V  # noqa: E402


def test_search_is_cosine_and_ordered():
    vecs = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype="float32")
    index = V.from_vectors(vecs)
    hits = V.search(index, np.array([[1.0, 0.0]], dtype="float32"), k=3)[0]
    ids = [i for i, _ in hits]
    assert ids[0] == 0, ids
    assert ids[1] == 1, ids
    assert abs(hits[0][1] - 1.0) < 1e-5, hits[0]
    assert hits[0][1] > hits[1][1] > hits[2][1]
    assert hits[2][1] < 0.2, "orthogonal vector should score near zero"


def test_roundtrip(tmp: Path):
    vecs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    path = tmp / "t.faiss"
    V.save(V.from_vectors(vecs), path)
    hits = V.search(V.load(path), np.array([[0.0, 1.0]], dtype="float32"), k=1)[0]
    assert hits[0][0] == 1, hits


import tempfile  # noqa: E402

test_search_is_cosine_and_ordered()
print("  ok  test_search_is_cosine_and_ordered")
with tempfile.TemporaryDirectory() as d:
    test_roundtrip(Path(d))
print("  ok  test_roundtrip")
print("vector index: all checks passed")
