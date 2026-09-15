"""Layer 4 degraded paths must be visible, not indistinguishable from a healthy run."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.engines.llm_router import _gemini_generation, pins_temperature
from app.engines.nli import (
    LEXICAL_CONTRADICTION_SCORE,
    NliEngine,
    lexical_nli,
)
from app.layers.evidence import join_independent_sources, run_evidence
from app.layers.uncertainty import rule_based_uncertainty
from app.schemas.envelope import (
    Claim,
    ClassificationPayload,
    GeminiClaimAnalysis,
    PairAnalysis,
    RunEnvelope,
)
from app.schemas.retrieval import IndependentSource, RetrievalPayload, SearchHit
from app.scoring.corroboration import fuse_claim, llm_row_participated
from app.scoring.urls import canonical_url, grouping_url


def _settings(**kwargs) -> Settings:
    base = {
        "hf_token": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "test",
        "google_api_key": "",
        "max_evidence_items": 50,
    }
    base.update(kwargs)
    return Settings(**base)


def _hit(*, url: str, canonical_url_value: str = "", snippet: str = "Ministers announced a plan.") -> SearchHit:
    return SearchHit(
        url=url,
        canonical_url=canonical_url_value,
        title="Coastal defence plan announced",
        snippet=snippet,
        body_hash=None,
        published_at="2026-09-12T08:30:00Z",
        publisher_domain="example.com",
        publisher_id="example.com",
        byline=None,
        wire_credit=None,
        source_adapter="newsapi",
        query_id="q1",
        claim_id=None,
        language="en",
        relevance_score=None,
    )


class FakeLLM:
    def __init__(self, payload: dict, model: str = "gemini-3.6-flash"):
        self.payload = payload
        self.model = model
        self.temperature: float | None = None

    def provider_ready(self, provider: str) -> bool:
        return provider == "gemini"

    async def chat_json_any(self, *, attempts, system, user, temperature=0.1):
        self.temperature = temperature
        return self.payload, "gemini", self.model


async def _noop_emit(**kwargs) -> None:
    return None


def test_grouping_url_matches_when_canonical_is_empty() -> None:
    raw = "https://www.example.com/story?utm_source=share"
    hit = _hit(url=raw, canonical_url_value="")
    assert grouping_url(hit) == canonical_url(raw)
    assert grouping_url(hit) != raw


def test_join_miss_when_member_urls_use_a_different_key() -> None:
    hit = _hit(url="https://example.com/a", canonical_url_value="")
    envelope = RunEnvelope(run_id="join-miss")
    envelope.retrieval = RetrievalPayload(
        documents=[hit],
        independent_sources=[
            IndependentSource(
                source_id="src1",
                representative_url="https://example.com/a",
                member_urls=["https://other.example/not-this"],
                publisher_ids=["example.com"],
            )
        ],
        independent_source_count=1,
        document_count=1,
    )
    groups, misses = join_independent_sources(envelope)
    assert misses == 1
    assert groups == {}


def test_join_hits_when_both_sides_use_grouping_url() -> None:
    hit = _hit(
        url="https://www.example.com/story?utm_source=x",
        canonical_url_value="",
    )
    key = grouping_url(hit)
    envelope = RunEnvelope(run_id="join-hit")
    envelope.retrieval = RetrievalPayload(
        documents=[hit],
        independent_sources=[
            IndependentSource(
                source_id="src1",
                representative_url=key,
                member_urls=[key],
                publisher_ids=["example.com"],
            )
        ],
        independent_source_count=1,
        document_count=1,
    )
    groups, misses = join_independent_sources(envelope)
    assert misses == 0
    assert groups == {"s1": "src1"}


def test_empty_llm_row_is_a_non_response() -> None:
    empty = GeminiClaimAnalysis(claim_id="c1", dropped_source_ids=["s99"])
    assert llm_row_participated(empty) is False
    row = fuse_claim(
        claim_id="c1",
        pairs=[
            PairAnalysis(
                claim_id="c1",
                source_id="s1",
                nli_label="entailment",
                nli_score=0.9,
            )
        ],
        gemini=empty,
        evidence_by_id={"s1": "https://example.com/a"},
        threshold=0.6,
        existence_class="not_found",
        source_groups={"s1": "src1"},
    )
    assert row.agreement == "nli_only"
    assert row.llm_support == 0
    assert row.llm_contradict == 0


def test_lexical_contradiction_score_equals_named_constant() -> None:
    label, score, probs = lexical_nli(
        "Ministers announced the plan.",
        "Ministers never announced the plan.",
    )
    assert label == "contradiction"
    assert score == LEXICAL_CONTRADICTION_SCORE
    assert probs["contradiction"] == LEXICAL_CONTRADICTION_SCORE


def test_pins_temperature_false_for_gemini_3() -> None:
    assert pins_temperature("gemini", "gemini-3.6-flash") is False
    assert pins_temperature("gemini", "gemini-2.5-flash") is True
    assert "temperature" not in _gemini_generation("gemini-3.6-flash", 0.0, True)
    assert _gemini_generation("gemini-2.5-flash", 0.0, True)["temperature"] == 0.0


def test_run_evidence_records_degraded_nli_and_hallucinated_llm() -> None:
    hit = _hit(
        url="https://www.example.com/story?utm_source=x",
        canonical_url_value="",
        snippet="Ministers announced a coastal defence programme on Tuesday.",
    )
    key = grouping_url(hit)
    envelope = RunEnvelope(
        run_id="visibility",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src1",
                    representative_url=key,
                    member_urls=[key],
                    publisher_ids=["example.com"],
                )
            ],
            independent_source_count=1,
            document_count=1,
            existence_class="title_match",
        ),
    )
    llm = FakeLLM(
        {
            "claims": [
                {
                    "claim_id": "c1",
                    "supported_by": ["s99"],
                    "contradicted_by": ["s100"],
                    "unrelated": [],
                    "inconsistencies": [],
                    "missing_slots": [],
                }
            ]
        }
    )
    nli = NliEngine(_settings(), client=None)
    events: list[dict] = []

    async def emit(**kwargs) -> None:
        events.append(kwargs)

    asyncio.run(run_evidence(envelope, settings=_settings(), nli=nli, llm=llm, emit=emit))

    assert llm.temperature == 0.0
    assert envelope.engines_used["nli"] == "lexical-nli-fallback"
    assert envelope.engines_used["evidence_llm"] == "skipped"
    assert envelope.corroboration.nli_engine == "lexical-nli-fallback"
    assert envelope.corroboration.nli_can_detect_contradiction is False
    assert envelope.corroboration.group_join_misses == 0
    assert envelope.corroboration.llm_dropped_id_count == 2
    assert envelope.corroboration.evidence_llm_model == "gemini-3.6-flash"
    assert envelope.corroboration.evidence_llm_temperature == 0.0
    assert envelope.corroboration.evidence_llm_temperature_pinned is False
    assert envelope.gemini_analysis[0].dropped_source_ids == ["s99", "s100"]
    assert envelope.gemini_analysis[0].supported_by == []
    assert envelope.corroboration.claims[0].agreement == "nli_only"
    pair_emits = [
        event
        for event in events
        if event.get("parameter") == "claim[c1]" and event.get("tool") == "lexical-nli"
    ]
    assert pair_emits
    assert all(event["status"] == "skipped" for event in pair_emits)

    unknown_text = " ".join(rule_based_uncertainty(envelope).unknowns)
    assert "Contradiction detection was unavailable" in unknown_text
    assert "cited 2 source id" in unknown_text
    assert "sampling was not pinned" in unknown_text
