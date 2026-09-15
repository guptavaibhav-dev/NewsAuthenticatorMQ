"""Engine A selection: DeBERTa, then BART, then lexical — and what lexical cannot do."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import Settings
from app.engines.nli import LEXICAL_NEGATION_CUES, NliEngine, lexical_nli


DEBERTA = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
BART = "facebook/bart-large-mnli"

ENTAILMENT = {
    "labels": ["entailment", "neutral", "contradiction"],
    "scores": [0.91, 0.06, 0.03],
}


def _settings(**kwargs) -> Settings:
    base = {
        "hf_token": "",
        "nli_model": DEBERTA,
        "nli_fallback_model": BART,
        "openai_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "google_api_key": "",
    }
    base.update(kwargs)
    return Settings(**base)


def _score(nli: NliEngine, handler) -> list:
    async def _go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            nli.client = client
            return await nli.score_pairs(
                [("Ministers announced a plan on Tuesday.", "Ministers announced a plan.")]
            )

    return asyncio.run(_go())


def test_deberta_is_used_when_it_responds() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=ENTAILMENT)

    nli = NliEngine(_settings(hf_token="hf-test"), client=None)
    results = _score(nli, handler)
    assert nli.engine_name == f"hf:{DEBERTA}"
    assert nli.can_detect_contradiction() is True
    assert results[0][0] == "entailment"
    assert any(DEBERTA in url for url in seen)
    assert not any(BART in url for url in seen)


def test_bart_is_used_when_deberta_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if DEBERTA in url:
            return httpx.Response(404, json={"error": "missing model"})
        if BART in url:
            return httpx.Response(200, json=ENTAILMENT)
        return httpx.Response(404, json={"error": "unexpected url"})

    nli = NliEngine(_settings(hf_token="hf-test"), client=None)
    results = _score(nli, handler)
    assert nli.engine_name == f"hf:{BART}"
    assert nli.can_detect_contradiction() is True
    assert results[0][0] == "entailment"


def test_lexical_is_used_when_both_hosted_engines_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    nli = NliEngine(_settings(hf_token="hf-test"), client=None)
    results = _score(nli, handler)
    assert nli.engine_name == "lexical-nli-fallback"
    assert nli.can_detect_contradiction() is False
    assert results
    assert nli.last_error


def test_lexical_is_used_when_there_is_no_hf_token() -> None:
    nli = NliEngine(_settings(hf_token=""), client=None)

    async def _go():
        return await nli.score_pairs(
            [("Ministers announced a plan on Tuesday.", "Ministers announced a plan.")]
        )

    results = asyncio.run(_go())
    assert nli.engine_name == "lexical-nli-fallback"
    assert nli.can_detect_contradiction() is False
    assert nli.last_error == "HF_TOKEN not set"
    assert results[0][0] in {"entailment", "neutral", "contradiction"}


def test_lexical_nli_returns_contradiction_only_on_its_cue_list() -> None:
    for cue in sorted(c for c in LEXICAL_NEGATION_CUES if len(c) > 2):
        label, _, _ = lexical_nli(
            "Ministers announced the coastal defence plan.",
            f"Ministers {cue} announced the coastal defence plan.",
        )
        assert label == "contradiction", f"cue {cue!r} should fire"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "lexical_nli has no polarity model. 'posted a profit' vs 'posted a loss' "
        "is contradiction to a reader, but none of the seven cue words appear, "
        "so the fallback cannot say so. This failure is the documented limit, "
        "not a passing grade for the heuristic."
    ),
)
def test_lexical_nli_cannot_see_antonym_contradiction() -> None:
    label, _, _ = lexical_nli(
        "The company posted a profit this quarter.",
        "The company posted a loss this quarter.",
    )
    assert label == "contradiction"
