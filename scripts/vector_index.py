#!/usr/bin/env python3
"""FAISS over the normalised symptom vocabulary.

IndexFlatIP on unit-normalised vectors, so inner product is cosine. Exact,
not HNSW: 1300 x 768 floats is four megabytes, an exhaustive scan is
immediate, and an exact index has no recall loss to caveat.

FAISS stores no payload. Row order in the index is row order in
data/candidates/symptoms-v2.tsv, and that is the only join.

    vector_index.py --build     embed the vocabulary and write the index
"""
from __future__ import annotations

import sys
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

INDEX_PATH = ROOT / ".workbench" / "index" / "symptoms-v2.faiss"
SYMPTOMS = ROOT / "data" / "candidates" / "symptoms-v2.tsv"


def _unit(vecs: np.ndarray) -> np.ndarray:
    v = np.ascontiguousarray(vecs, dtype="float32")
    faiss.normalize_L2(v)
    return v


def from_vectors(vecs: np.ndarray) -> faiss.Index:
    v = _unit(vecs)
    index = faiss.IndexFlatIP(v.shape[1])
    index.add(v)
    return index


def search(index: faiss.Index, queries: np.ndarray, k: int = 5
           ) -> list[list[tuple[int, float]]]:
    scores, ids = index.search(_unit(queries), k)
    return [[(int(i), float(s)) for i, s in zip(row_i, row_s) if i != -1]
            for row_i, row_s in zip(ids, scores)]


def save(index: faiss.Index, path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def load(path: Path = INDEX_PATH) -> faiss.Index:
    if not path.exists():
        raise SystemExit(f"no index at {path}; run vector_index.py --build")
    return faiss.read_index(str(path))


def phrases() -> list[str]:
    """Core phrases in row order. The index and this list must agree."""
    return [ln.split("\t")[1] for ln in SYMPTOMS.read_text().splitlines()[1:] if ln]


def build() -> None:
    import _gemini as G

    texts = phrases()
    vecs = np.array(G.embed(texts, progress=True), dtype="float32")
    save(from_vectors(vecs))
    print(f"{len(texts)} phrases indexed at {INDEX_PATH}")


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    else:
        raise SystemExit("give --build")
