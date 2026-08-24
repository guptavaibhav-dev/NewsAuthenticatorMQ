from __future__ import annotations

from typing import Literal

import httpx

from app.config import Settings
from app.schemas.envelope import NliLabel

NliResult = tuple[NliLabel, float, dict[str, float]]


class NliEngine:
    """Non-generative NLI. Prefers HF DeBERTa, else lexical overlap."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.engine_name = "lexical-nli-fallback"

    async def score_pair(self, premise: str, hypothesis: str) -> NliResult:
        results = await self.score_pairs([(premise, hypothesis)])
        return results[0]

    async def score_pairs(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        if not pairs:
            return []
        if self.settings.hf_token:
            try:
                scored = await self._hf_mnli(pairs)
                self.engine_name = f"hf:{self.settings.nli_model}"
                return scored
            except Exception:
                pass
        self.engine_name = "lexical-nli-fallback"
        return [lexical_nli(p, h) for p, h in pairs]

    async def _hf_mnli(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        out: list[NliResult] = []
        # HF zero-shot / MNLI often expects one pair per call for this model.
        for premise, hypothesis in pairs:
            response = await self.client.post(
                f"https://api-inference.huggingface.co/models/{self.settings.nli_model}",
                headers={"Authorization": f"Bearer {self.settings.hf_token}"},
                json={
                    "inputs": {"text": premise[:2000], "text_pair": hypothesis[:500]},
                    "options": {"wait_for_model": True},
                },
            )
            if response.status_code >= 400:
                # some hosts want the zero-shot classification pipeline
                response = await self.client.post(
                    f"https://api-inference.huggingface.co/models/{self.settings.nli_model}",
                    headers={"Authorization": f"Bearer {self.settings.hf_token}"},
                    json={
                        "inputs": premise[:2000],
                        "parameters": {
                            "candidate_labels": [
                                "entailment",
                                "contradiction",
                                "neutral",
                            ],
                            "hypothesis_template": hypothesis[:400] + " {}",
                        },
                        "options": {"wait_for_model": True},
                    },
                )
            response.raise_for_status()
            out.append(_parse_hf_nli(response.json()))
        return out


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
        if "entail" in raw or raw.endswith("entailment") or raw in {"label_0", "0"}:
            labels["entailment"] = max(labels["entailment"], score)
        elif "contrad" in raw or raw in {"label_2", "2"}:
            labels["contradiction"] = max(labels["contradiction"], score)
        elif "neutral" in raw or raw in {"label_1", "1"}:
            labels["neutral"] = max(labels["neutral"], score)
    if sum(labels.values()) == 0:
        return lexical_nli("", "")
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
    if overlap >= 0.55:
        conf = min(0.55 + overlap * 0.3, 0.85)
        return "entailment", conf, {
            "entailment": conf,
            "contradiction": 0.1,
            "neutral": 1 - conf - 0.1,
        }
    return "neutral", 0.55, {"entailment": overlap, "contradiction": 0.1, "neutral": 0.55}


def _words(text: str) -> list[str]:
    return [w for w in text.lower().split() if len(w) > 2]


LabelName = Literal["entailment", "contradiction", "neutral"]
