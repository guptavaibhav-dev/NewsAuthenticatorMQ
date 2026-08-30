from __future__ import annotations

import asyncio
from typing import Literal

from app.config import Settings
from app.engines.hf_inference import hf_infer
from app.logutil import get_logger, short_error
from app.schemas.envelope import NliLabel

NliResult = tuple[NliLabel, float, dict[str, float]]

log = get_logger("nli")


class NliEngine:
    """Non-generative NLI. Prefers HF DeBERTa, else BART MNLI, else lexical overlap."""

    def __init__(self, settings: Settings, client):
        self.settings = settings
        self.client = client
        self.engine_name = "lexical-nli-fallback"
        self.last_error: str | None = None
        self._payload_index: int | None = None

    async def score_pair(self, premise: str, hypothesis: str) -> NliResult:
        results = await self.score_pairs([(premise, hypothesis)])
        return results[0]

    async def score_pairs(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        if not pairs:
            return []
        models: list[str] = []
        if self.settings.nli_model:
            models.append(self.settings.nli_model)
        fallback = getattr(self.settings, "nli_fallback_model", "") or "facebook/bart-large-mnli"
        if fallback not in models:
            models.append(fallback)

        if self.settings.hf_token:
            for model in models:
                try:
                    self._payload_index = None
                    scored = await self._hf_mnli(pairs, model)
                    self.engine_name = f"hf:{model}"
                    self.last_error = None
                    return scored
                except Exception as exc:
                    self.last_error = short_error(exc)
                    log.warning("hf nli model=%s failed: %s", model, self.last_error)
        else:
            self.last_error = "HF_TOKEN not set"

        self.engine_name = "lexical-nli-fallback"
        log.warning("nli using lexical fallback (%s)", self.last_error or "no HF token")
        return [lexical_nli(p, h) for p, h in pairs]

    async def _hf_mnli(self, pairs: list[tuple[str, str]], model: str) -> list[NliResult]:
        timeout_s = float(getattr(self.settings, "hf_timeout_s", 60.0) or 60.0)
        first = await self._hf_one(pairs[0][0], pairs[0][1], model, timeout_s)
        if len(pairs) == 1:
            return [first]

        sem = asyncio.Semaphore(6)

        async def one(premise: str, hypothesis: str) -> NliResult:
            async with sem:
                return await self._hf_one(premise, hypothesis, model, timeout_s)

        rest = await asyncio.gather(
            *[one(p, h) for p, h in pairs[1:]],
        )
        return [first, *rest]

    async def _hf_one(
        self, premise: str, hypothesis: str, model: str, timeout_s: float
    ) -> NliResult:
        payloads = [
            {
                "inputs": premise[:2000],
                "parameters": {
                    "candidate_labels": ["entailment", "contradiction", "neutral"],
                    "hypothesis_template": hypothesis[:400] + " is {}.",
                    "multi_label": False,
                },
                "options": {"wait_for_model": True},
            },
            {
                "inputs": {"text": premise[:2000], "text_pair": hypothesis[:500]},
                "options": {"wait_for_model": True},
            },
            {
                "inputs": [premise[:2000], hypothesis[:500]],
                "options": {"wait_for_model": True},
            },
        ]
        order = list(range(len(payloads)))
        if self._payload_index is not None:
            order = [self._payload_index] + [i for i in order if i != self._payload_index]
        last_error: Exception | None = None
        for index in order:
            log.debug("nli model=%s payload=%s", model, index)
            try:
                data = await hf_infer(
                    self.client,
                    self.settings.hf_token,
                    model,
                    payloads[index],
                    timeout_s=timeout_s,
                )
                parsed = _parse_hf_nli(data)
                self._payload_index = index
                return parsed
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError(f"HF NLI returned no parseable scores for {model}")


def _parse_hf_nli(payload: object) -> NliResult:
    labels: dict[str, float] = {"entailment": 0.0, "contradiction": 0.0, "neutral": 0.0}
    rows: list[dict] = []
    if isinstance(payload, list):
        if payload and isinstance(payload[0], list):
            rows = payload[0]
        elif payload and isinstance(payload[0], dict):
            rows = payload  # type: ignore[assignment]
    elif isinstance(payload, dict):
        names = payload.get("labels") or payload.get("candidate_labels") or []
        scores = payload.get("scores") or []
        rows = [{"label": n, "score": s} for n, s in zip(names, scores)]
    for row in rows:
        raw = str(row.get("label", "")).lower()
        score = float(row.get("score", 0.0))
        if (
            "entail" in raw
            or "support" in raw
            or raw.endswith("entailment")
            or raw in {"label_0", "0"}
        ):
            labels["entailment"] = max(labels["entailment"], score)
        elif "contrad" in raw or "refut" in raw or raw in {"label_2", "2"}:
            labels["contradiction"] = max(labels["contradiction"], score)
        elif "neutral" in raw or "unrelated" in raw or raw in {"label_1", "1"}:
            labels["neutral"] = max(labels["neutral"], score)
    if sum(labels.values()) == 0:
        raise ValueError("unrecognised NLI payload")
    label: NliLabel = max(labels, key=labels.get)  # type: ignore[arg-type]
    return label, labels[label], labels


def lexical_nli(premise: str, hypothesis: str) -> NliResult:
    """Conservative fallback: overlap → entailment-leaning, antonym cues → contradiction."""
    p = set(_words(premise))
    h = set(_words(hypothesis))
    if not p or not h:
        return "neutral", 0.5, {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8}
    overlap = len(p & h) / max(len(h), 1)
    neg_cues = {"not", "never", "false", "denied", "hoax", "untrue", "no"}
    contradiction_hit = bool(neg_cues & p) != bool(neg_cues & h) and overlap > 0.3
    if contradiction_hit:
        probs = {"entailment": 0.15, "contradiction": 0.6, "neutral": 0.25}
        return "contradiction", 0.6, probs
    if overlap >= 0.45:
        conf = min(0.58 + overlap * 0.3, 0.85)
        return "entailment", conf, {
            "entailment": conf,
            "contradiction": 0.1,
            "neutral": max(0.05, 1 - conf - 0.1),
        }
    return "neutral", max(0.4, 1 - overlap), {
        "entailment": overlap,
        "contradiction": 0.1,
        "neutral": max(0.4, 1 - overlap - 0.1),
    }


def _words(text: str) -> list[str]:
    return [w for w in text.lower().split() if len(w) > 2]


LabelName = Literal["entailment", "contradiction", "neutral"]
