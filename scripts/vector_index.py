#!/usr/bin/env python3
"""FAISS over the normalised symptom vocabulary.

IndexFlatIP on unit-normalised vectors, so inner product is cosine. Exact,
not HNSW: 1300 x 768 floats is four megabytes, an exhaustive scan is
immediate, and an exact index has no recall loss to caveat.

FAISS stores no payload. Row order in the index is row order in
data/candidates/symptoms-v2.tsv, and that is the only join. A sidecar
<name>.meta.json next to the index records the phrase count and a SHA-256
of the phrase list as indexed; load() recomputes it against the current
vocabulary and refuses a stale index instead of returning silently wrong
row ids.

    vector_index.py --build     embed the vocabulary and write the index
"""
from __future__ import annotations

import hashlib
import json
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


def _meta_path(path: Path) -> Path:
    return path.with_name(path.stem + ".meta.json")


def _digest(phrase_list: list[str]) -> str:
    return hashlib.sha256("\n".join(phrase_list).encode()).hexdigest()


def save(index: faiss.Index, path: Path = INDEX_PATH,
         phrase_list: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))
    if phrase_list is not None:
        meta = {"count": len(phrase_list), "sha256": _digest(phrase_list)}
        _meta_path(path).write_text(json.dumps(meta))


def load(path: Path = INDEX_PATH, phrase_list: list[str] | None = None) -> faiss.Index:
    if not path.exists():
        raise SystemExit(f"no index at {path}; run vector_index.py --build")
    if phrase_list is None:
        phrase_list = phrases()
    meta_path = _meta_path(path)
    want = {"count": len(phrase_list), "sha256": _digest(phrase_list)}
    have = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if have != want:
        raise SystemExit(
            "the vocabulary changed since the index was built; "
            "run vector_index.py --build")
    return faiss.read_index(str(path))


def phrases() -> list[str]:
    """Core phrases in row order. The index and this list must agree."""
    return [ln.split("\t")[1] for ln in SYMPTOMS.read_text().splitlines()[1:] if ln]


def build() -> None:
    import _gemini as G

    texts = phrases()
    vecs = np.array(G.embed(texts, progress=True), dtype="float32")
    save(from_vectors(vecs), phrase_list=texts)
    print(f"{len(texts)} phrases indexed at {INDEX_PATH}")


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    else:
        raise SystemExit("give --build")
