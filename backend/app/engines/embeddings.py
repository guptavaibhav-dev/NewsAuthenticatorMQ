from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from app.engines.hf_inference import hf_infer
from app.logutil import get_logger, short_error

log = get_logger("embed")

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    compact = re.sub(r"\s+", " ", text.lower()).strip()
    if len(compact) < n:
        return Counter([compact]) if compact else Counter()
    return Counter(compact[i : i + n] for i in range(len(compact) - n + 1))


def cosine_sparse(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b[k] for k in a.keys() & b.keys())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


class EmbeddingEngine:
    """Independent (non-LLM) similarity. Prefers HF Inference, else n-grams."""

    def __init__(self, settings, client):
        self.settings = settings
        self.client = client
        self.engine_name = "char-ngram-cosine"

    async def similarity(self, a: str, b: str) -> float:
        vectors = await self.embed([a, b])
        return cosine_dense(vectors[0], vectors[1])

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        cleaned = [t[:4000] if t else "" for t in texts]
        if self.settings.hf_token:
            try:
                vectors = await self._hf_embed(cleaned)
                self.engine_name = f"hf:{self.settings.embedding_model}"
                return vectors
            except Exception as exc:
                log.warning("hf embeddings failed: %s", short_error(exc))
        self.engine_name = "char-ngram-cosine"
        return [ngram_vector(text) for text in cleaned]

    async def _hf_embed(self, texts: list[str]) -> list[np.ndarray]:
        timeout_s = float(getattr(self.settings, "hf_timeout_s", 60.0) or 60.0)
        payload = await hf_infer(
            self.client,
            self.settings.hf_token,
            self.settings.embedding_model,
            {"inputs": texts, "options": {"wait_for_model": True}},
            timeout_s=timeout_s,
            pipeline="feature-extraction",
        )
        return _vectors_from_hf(payload)


def ngram_vector(text: str) -> np.ndarray:
    counts = _char_ngrams(text)
    # stable hashed bag so we can still use dense cosine
    dim = 512
    vec = np.zeros(dim, dtype=np.float32)
    for gram, count in counts.items():
        vec[hash(gram) % dim] += float(count)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def cosine_dense(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _vectors_from_hf(payload: object) -> list[np.ndarray]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("Hugging Face embeddings returned an empty payload")
    # Single text can come back as one vector or as token vectors.
    if payload and isinstance(payload[0], (int, float)):
        payload = [payload]
    vectors: list[np.ndarray] = []
    for item in payload:
        arr = np.array(item, dtype=np.float32)
        if arr.ndim == 2:
            arr = arr.mean(axis=0)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        vectors.append(arr)
    return vectors


def token_jaccard(a: str, b: str) -> float:
    sa, sb = set(_tokens(a)), set(_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
