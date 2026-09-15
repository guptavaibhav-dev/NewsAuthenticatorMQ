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
        self._hf_disabled = False

    def can_detect_contradiction(self) -> bool:
        """False on the lexical path, which has no real polarity model."""
        return not self.engine_name.startswith("lexical")

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

        if self.settings.hf_token and not self._hf_disabled:
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
            self._hf_disabled = True
        else:
            if not self.settings.hf_token:
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
                "options": {"wait_for_model": False},
            },
            {
                "inputs": {"text": premise[:2000], "text_pair": hypothesis[:500]},
                "options": {"wait_for_model": False},
            },
            {
                "inputs": [premise[:2000], hypothesis[:500]],
                "options": {"wait_for_model": False},
            },
        ]
        order = _payload_order(model)
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


def _payload_order(model: str) -> list[int]:
    """Which HF JSON shape to try first.

    DeBERTa MNLI is a text-pair classifier. Trying the zero-shot shape first
    cold-starts the wrong pipeline and can sit on 503 for tens of seconds
    *per pair*. BART-MNLI is commonly served as zero-shot, so it keeps
    candidate_labels first.
    """
    name = (model or "").lower()
    if "deberta" in name or "fever" in name:
        return [1, 2, 0]
    return [0, 1, 2]


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


# Heuristic and unvalidated. These numbers are not MNLI probabilities; they
# were chosen by hand so the fallback returns the same three labels as the
# hosted engines. A zero-contradiction result from this path does not mean
# contradiction was absent — the engine cannot detect it in general.
LEXICAL_EMPTY_SCORE = 0.5
LEXICAL_EMPTY_PROBS = {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8}
LEXICAL_NEGATION_CUES = frozenset(
    {"not", "never", "false", "denied", "hoax", "untrue", "no"}
)
LEXICAL_CONTRADICTION_OVERLAP = 0.3
LEXICAL_CONTRADICTION_SCORE = 0.6
LEXICAL_CONTRADICTION_PROBS = {
    "entailment": 0.15,
    "contradiction": 0.6,
    "neutral": 0.25,
}
LEXICAL_ENTAILMENT_OVERLAP = 0.45
LEXICAL_ENTAILMENT_BASE = 0.58
LEXICAL_ENTAILMENT_SLOPE = 0.3
LEXICAL_ENTAILMENT_CAP = 0.85
LEXICAL_BACKGROUND_CONTRADICTION = 0.1
LEXICAL_NEUTRAL_SCORE_FLOOR = 0.4
LEXICAL_REMAINDER_FLOOR = 0.05


def lexical_nli(premise: str, hypothesis: str) -> NliResult:
    """Conservative fallback: overlap → entailment-leaning, antonym cues → contradiction.

    Heuristic and unvalidated. This is not MNLI: it cannot represent polarity
    in general, and a zero-contradiction result from this path is not a finding
    that no contradiction exists.
    """
    p = set(_words(premise))
    h = set(_words(hypothesis))
    if not p or not h:
        return "neutral", LEXICAL_EMPTY_SCORE, dict(LEXICAL_EMPTY_PROBS)
    overlap = len(p & h) / max(len(h), 1)
    contradiction_hit = (
        bool(LEXICAL_NEGATION_CUES & p) != bool(LEXICAL_NEGATION_CUES & h)
        and overlap > LEXICAL_CONTRADICTION_OVERLAP
    )
    if contradiction_hit:
        return "contradiction", LEXICAL_CONTRADICTION_SCORE, dict(LEXICAL_CONTRADICTION_PROBS)
    if overlap >= LEXICAL_ENTAILMENT_OVERLAP:
        conf = min(
            LEXICAL_ENTAILMENT_BASE + overlap * LEXICAL_ENTAILMENT_SLOPE,
            LEXICAL_ENTAILMENT_CAP,
        )
        return "entailment", conf, {
            "entailment": conf,
            "contradiction": LEXICAL_BACKGROUND_CONTRADICTION,
            "neutral": max(LEXICAL_REMAINDER_FLOOR, 1 - conf - LEXICAL_BACKGROUND_CONTRADICTION),
        }
    return "neutral", max(LEXICAL_NEUTRAL_SCORE_FLOOR, 1 - overlap), {
        "entailment": overlap,
        "contradiction": LEXICAL_BACKGROUND_CONTRADICTION,
        "neutral": max(
            LEXICAL_NEUTRAL_SCORE_FLOOR,
            1 - overlap - LEXICAL_BACKGROUND_CONTRADICTION,
        ),
    }


def _words(text: str) -> list[str]:
    return [w for w in text.lower().split() if len(w) > 2]


LabelName = Literal["entailment", "contradiction", "neutral"]
