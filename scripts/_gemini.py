"""Minimal Gemini client: embeddings and a cheap flash model, both cached.

Embeddings are the expensive half and the corpus is re-embedded on every run
of the normaliser, so every vector is cached on disk by hash of its text. The
cache lives in .workbench/, which is gitignored: it is derived from NHS prose
and stays out of the repository on the same reasoning as the page cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".workbench" / "gemini"
API = "https://generativelanguage.googleapis.com/v1beta/models"
EMBED_MODEL = "gemini-embedding-2"
FLASH_MODEL = "gemini-flash-lite-latest"
DIMS = 768  # 3072 is the default; 768 costs a quarter of the disk and scores the same here.


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY")
    if not k:
        raise SystemExit("GEMINI_API_KEY is not set in the environment")
    return k


def _post(model: str, method: str, body: dict, tries: int = 5) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}/{model}:{method}", data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 429 is the free-tier rate limit and 5xx is transient; both retry.
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise SystemExit(f"{model}:{method} failed {e.code}: {e.read()[:400]!r}")
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    raise SystemExit("unreachable")


def _cache_path(text: str) -> Path:
    h = hashlib.sha256(f"{EMBED_MODEL}:{DIMS}:{text}".encode()).hexdigest()
    return CACHE / h[:2] / f"{h}.vec"


def embed(texts: list[str], task: str = "SEMANTIC_SIMILARITY",
          batch: int = 100, progress: bool = False) -> list[list[float]]:
    """Vectors for texts, in order. Cached hits cost nothing."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out: list[list[float] | None] = [None] * len(texts)
    todo: list[int] = []
    for i, t in enumerate(texts):
        p = _cache_path(t)
        if p.exists():
            raw = p.read_bytes()
            out[i] = list(struct.unpack(f"{len(raw) // 4}f", raw))
        else:
            todo.append(i)
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        body = {"requests": [
            {"model": f"models/{EMBED_MODEL}",
             "content": {"parts": [{"text": texts[i]}]},
             "taskType": task,
             "outputDimensionality": DIMS} for i in chunk]}
        res = _post(EMBED_MODEL, "batchEmbedContents", body)
        for i, emb in zip(chunk, res["embeddings"]):
            v = emb["values"]
            out[i] = v
            p = _cache_path(texts[i])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(struct.pack(f"{len(v)}f", *v))
        if progress:
            print(f"  embedded {min(start + batch, len(todo))}/{len(todo)} new", flush=True)
    return out  # type: ignore[return-value]


def ask(prompt: str, schema: dict | None = None, temperature: float = 0.0):
    """One flash call. With a schema the reply is parsed JSON, else text."""
    cfg: dict = {"temperature": temperature}
    if schema is not None:
        cfg["responseMimeType"] = "application/json"
        cfg["responseSchema"] = schema
    res = _post(FLASH_MODEL, "generateContent",
                {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg})
    try:
        text = res["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise SystemExit(f"flash returned no text: {json.dumps(res)[:400]}")
    return json.loads(text) if schema is not None else text
