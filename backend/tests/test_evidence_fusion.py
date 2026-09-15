"""Layer 4 fusion: empty paths, syndication, degradation, and the Layer 3 join."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.engines.nli import NliEngine
from app.layers.documentation import template_record
from app.layers.evidence import run_evidence
from app.layers.uncertainty import rule_based_uncertainty
from app.schemas.envelope import (
    Claim,
    ClassificationPayload,
    PairAnalysis,
    RunEnvelope,
)
from app.schemas.retrieval import IndependentSource, RetrievalPayload, SearchHit
from app.scoring.corroboration import build_payload, fuse_claim
from app.scoring.urls import grouping_url


def _settings(**kwargs) -> Settings:
    base = {
        "hf_token": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "google_api_key": "",
        "max_evidence_items": 50,
    }
    base.update(kwargs)
    return Settings(**base)


def _hit(
    *,
    url: str,
    domain: str | None = None,
    snippet: str | None = "Ministers announced a coastal defence programme on Tuesday.",
    title: str = "Coastal defence plan announced",
    wire: str | None = "Reuters",
) -> SearchHit:
    host = domain or url.split("/")[2]
    return SearchHit(
        url=url,
        canonical_url=url,
        title=title,
        snippet=snippet,
        body_hash="sha256:same",
        published_at="2026-09-12T08:30:00Z",
        publisher_domain=host,
        publisher_id=host,
        byline=None,
        wire_credit=wire,
        source_adapter="newsapi",
        query_id="q1",
        claim_id="c1",
        language="en",
        relevance_score=0.5,
    )


class FakeNLI:
    engine_name = "hf:fake-deberta"
    last_error = None

    def __init__(self, label: str = "entailment", score: float = 0.9):
        self.label = label
        self.score = score

    def can_detect_contradiction(self) -> bool:
        return not self.engine_name.startswith("lexical")

    async def score_pairs(self, pairs: list[tuple[str, str]]):
        probs = {self.label: self.score, "entailment": 0.0, "contradiction": 0.0, "neutral": 0.0}
        probs[self.label] = self.score
        return [(self.label, self.score, probs) for _ in pairs]


class UnavailableLLM:
    def provider_ready(self, provider: str) -> bool:
        return False

    async def chat_json_any(self, **kwargs):
        raise AssertionError("Engine B must not be called when no provider is ready")


class FakeLLM:
    def __init__(self, payload: dict, model: str = "gemini-2.5-flash"):
        self.payload = payload
        self.model = model
        self.user = None

    def provider_ready(self, provider: str) -> bool:
        return provider == "gemini"

    async def chat_json_any(self, *, attempts, system, user, temperature=0.1):
        self.user = user
        return self.payload, "gemini", self.model


async def _noop_emit(**kwargs) -> None:
    return None


def _run(envelope: RunEnvelope, *, nli=None, llm=None, settings=None) -> RunEnvelope:
    async def _go() -> None:
        await run_evidence(
            envelope,
            settings=settings or _settings(),
            nli=nli or FakeNLI(),
            llm=llm or UnavailableLLM(),
            emit=_noop_emit,
        )

    asyncio.run(_go())
    return envelope


def test_zero_pairs_is_not_assessed_never_no_corroboration_found() -> None:
    envelope = RunEnvelope(
        run_id="empty",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a plan.")]
        ),
        retrieval=RetrievalPayload(existence_class="not_found"),
    )
    _run(envelope)
    assert envelope.corroboration.pairs_scored is False
    assert envelope.corroboration.overall_state == "not_assessed"
    assert envelope.corroboration.overall_state != "no_corroboration_found"
    assert envelope.corroboration.unscored_reason == "no_documents"

    row = fuse_claim(
        claim_id="c1",
        pairs=[],
        gemini=None,
        evidence_by_id={},
        threshold=0.6,
        existence_class="not_found",
    )
    assert row.state == "not_assessed"
    payload = build_payload(
        claims=[row],
        independent_source_count=0,
        pairs_scored=False,
        unscored_reason="no_documents",
        existence_class="not_found",
    )
    assert payload.overall_state == "not_assessed"


def test_out_of_range_with_zero_documents_stays_distinct_from_not_found() -> None:
    missing = RunEnvelope(
        run_id="not-found",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a plan.")]
        ),
        retrieval=RetrievalPayload(existence_class="not_found"),
    )
    unreachable = RunEnvelope(
        run_id="out-of-range",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a plan.")]
        ),
        retrieval=RetrievalPayload(existence_class="out_of_range"),
    )
    _run(missing)
    _run(unreachable)
    assert missing.corroboration.overall_state == "not_assessed"
    assert unreachable.corroboration.overall_state == "not_assessed"
    assert missing.corroboration.existence_class == "not_found"
    assert unreachable.corroboration.existence_class == "out_of_range"
    assert missing.corroboration.existence_class != unreachable.corroboration.existence_class
    missing_note = template_record(missing).evidence_summary
    unreachable_note = template_record(unreachable).evidence_summary
    assert "no coverage found" in missing_note
    assert "could not cover" in unreachable_note


def test_syndicated_with_zero_stance_support_is_not_assessed_not_single_source() -> None:
    docs = [
        _hit(url=f"https://paper{i}.example/story", snippet=None, title="")
        for i in range(5)
    ]
    envelope = RunEnvelope(
        run_id="syndicated-empty",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a plan.")]
        ),
        retrieval=RetrievalPayload(
            documents=docs,
            independent_sources=[
                IndependentSource(
                    source_id="wire1",
                    representative_url=docs[0].url,
                    member_urls=[grouping_url(hit) for hit in docs],
                    publisher_ids=[hit.publisher_id for hit in docs],
                    merge_reason="same_wire",
                    merge_evidence="One Reuters report, five mastheads.",
                )
            ],
            existence_class="syndicated",
        ),
    )
    _run(envelope)
    assert envelope.corroboration.pairs_scored is False
    assert envelope.corroboration.overall_state == "not_assessed"
    assert envelope.corroboration.overall_state != "single_source"
    assert all(row.state != "single_source" for row in envelope.corroboration.claims)

    scored_neutral = fuse_claim(
        claim_id="c1",
        pairs=[
            PairAnalysis(claim_id="c1", source_id="s1", nli_label="neutral", nli_score=0.4)
        ],
        gemini=None,
        evidence_by_id={"s1": docs[0].url},
        threshold=0.6,
        existence_class="syndicated",
        source_groups={"s1": "wire1"},
    )
    assert scored_neutral.state != "single_source"
    assert scored_neutral.state == "no_corroboration_found"


def test_twenty_syndicated_documents_count_as_one_source() -> None:
    docs = [
        _hit(url=f"https://paper{i}.example/story/{i}", domain=f"paper{i}.example")
        for i in range(20)
    ]
    envelope = RunEnvelope(
        run_id="wire-twenty",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=docs,
            independent_sources=[
                IndependentSource(
                    source_id="wire1",
                    representative_url=docs[0].url,
                    member_urls=[grouping_url(hit) for hit in docs],
                    publisher_ids=[hit.publisher_id for hit in docs],
                    merge_reason="same_wire",
                    merge_evidence="Twenty mastheads, one Reuters report.",
                )
            ],
            existence_class="syndicated",
        ),
    )
    _run(envelope, nli=FakeNLI(label="entailment", score=0.92))
    assert envelope.corroboration.independent_source_count == 1
    assert len(envelope.analysis) == 20
    row = envelope.corroboration.claims[0]
    assert row.nli_support == 1
    assert row.independent_support_outlets == 1
    assert row.nli_support != 20
    assert row.independent_support_outlets != 20


def test_stance_window_caps_nli_pairs_at_max_evidence_items() -> None:
    docs = [
        _hit(url=f"https://paper{i}.example/story/{i}", domain=f"paper{i}.example")
        for i in range(20)
    ]
    envelope = RunEnvelope(
        run_id="capped",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=docs,
            independent_sources=[
                IndependentSource(
                    source_id="wire1",
                    representative_url=docs[0].url,
                    member_urls=[grouping_url(hit) for hit in docs],
                    publisher_ids=[hit.publisher_id for hit in docs],
                    merge_reason="same_wire",
                    merge_evidence="Twenty mastheads, one Reuters report.",
                )
            ],
            existence_class="syndicated",
        ),
    )
    _run(envelope, nli=FakeNLI(), settings=_settings(max_evidence_items=12))
    assert len(envelope.analysis) == 12
    assert envelope.corroboration.independent_source_count == 1
    row = envelope.corroboration.claims[0]
    assert row.nli_support == 1
    assert row.independent_support_outlets == 1
    assert row.nli_support != 20
    assert row.independent_support_outlets != 20


def test_ungrouped_document_increments_group_join_misses_and_is_surfaced() -> None:
    hit = _hit(url="https://example.com/story")
    envelope = RunEnvelope(
        run_id="join-miss",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src1",
                    representative_url="https://other.example/not-this",
                    member_urls=["https://other.example/not-this"],
                    publisher_ids=["other.example"],
                )
            ],
            existence_class="title_match",
        ),
    )
    _run(envelope, nli=FakeNLI())
    assert envelope.corroboration.group_join_misses == 1
    unknowns = " ".join(rule_based_uncertainty(envelope).unknowns)
    assert "did not join an IndependentSource" in unknowns
    assert "upper bound" in unknowns
    record = template_record(envelope)
    assert "join missed 1" in record.evidence_summary


def test_gemini_unavailable_is_nli_only_and_visible() -> None:
    hit = _hit(url="https://example.com/story")
    envelope = RunEnvelope(
        run_id="no-llm",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src1",
                    representative_url=hit.url,
                    member_urls=[grouping_url(hit)],
                    publisher_ids=[hit.publisher_id],
                )
            ],
            existence_class="title_match",
        ),
    )
    _run(envelope, nli=FakeNLI(), llm=UnavailableLLM())
    assert envelope.corroboration.claims[0].agreement == "nli_only"
    assert envelope.engines_used["evidence_llm"] == "skipped"
    assert envelope.corroboration.evidence_llm_model is None
    assert envelope.gemini_analysis == []


def test_all_hallucinated_llm_response_is_a_non_response() -> None:
    hit = _hit(url="https://example.com/story")
    envelope = RunEnvelope(
        run_id="hallucinated",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src1",
                    representative_url=hit.url,
                    member_urls=[grouping_url(hit)],
                    publisher_ids=[hit.publisher_id],
                )
            ],
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
    _run(envelope, nli=FakeNLI(), llm=llm, settings=_settings(gemini_api_key="test"))
    assert envelope.engines_used["evidence_llm"] == "skipped"
    assert envelope.corroboration.llm_dropped_id_count == 2
    assert envelope.corroboration.claims[0].agreement == "nli_only"
    assert envelope.corroboration.claims[0].llm_support == 0
    assert envelope.gemini_analysis[0].supported_by == []
    assert envelope.gemini_analysis[0].dropped_source_ids == ["s99", "s100"]


def test_lexical_fallback_does_not_report_zero_contradictions_as_a_finding() -> None:
    hit = _hit(url="https://example.com/story")
    envelope = RunEnvelope(
        run_id="lexical",
        classification=ClassificationPayload(
            claims=[Claim(id="c1", text="Ministers announced a coastal defence programme.")]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src1",
                    representative_url=hit.url,
                    member_urls=[grouping_url(hit)],
                    publisher_ids=[hit.publisher_id],
                )
            ],
            existence_class="title_match",
        ),
    )
    nli = NliEngine(_settings(), client=None)
    _run(envelope, nli=nli)
    assert envelope.corroboration.nli_can_detect_contradiction is False
    assert envelope.corroboration.nli_engine == "lexical-nli-fallback"
    notes = template_record(envelope).cross_source_notes
    assert "contradict=unavailable (lexical NLI)" in notes
    assert "NLI support=" in notes
    unknowns = " ".join(rule_based_uncertainty(envelope).unknowns)
    assert "Contradiction detection was unavailable" in unknowns
    assert "zero contradiction count is not a finding" in unknowns
