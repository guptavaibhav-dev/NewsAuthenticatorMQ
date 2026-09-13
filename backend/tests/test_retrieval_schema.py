from __future__ import annotations

import pytest

from app.config import Settings
from app.schemas.envelope import RunEnvelope
from app.schemas.retrieval import (
    AdapterReport,
    Capability,
    CoverageReport,
    EntityGrounding,
    FactCheckRecord,
    IndependentSource,
    PlannedQuery,
    RetrievalPayload,
    SearchHit,
)


def _planned_queries() -> list[PlannedQuery]:
    return [
        PlannedQuery(
            query_id="q_exist_1",
            kind="existence",
            claim_id=None,
            query_text='"Ministers announce coastal defence plan"',
            template_id="exist.quoted_title.v1",
            attempt=1,
            date_from="2026-08-01",
            date_to="2026-09-13",
        ),
        PlannedQuery(
            query_id="q_claim_c3",
            kind="claim",
            claim_id="c3",
            query_text="coastal defence funding three-year Treasury",
            template_id="claim.entities_and_nouns.v1",
            attempt=2,
            date_from="2026-08-01",
            date_to="2026-09-13",
        ),
        PlannedQuery(
            query_id="q_fc_c3",
            kind="factcheck",
            claim_id="c3",
            query_text="Treasury confirmed coastal defence funding",
            template_id="factcheck.paraphrase.v1",
            attempt=1,
            date_from=None,
            date_to=None,
        ),
        PlannedQuery(
            query_id="q_entity_0",
            kind="entity",
            claim_id=None,
            query_text="Department for Coastal Resilience",
            template_id="entity.literal.v1",
            attempt=1,
            date_from=None,
            date_to=None,
        ),
    ]


def _documents() -> list[SearchHit]:
    return [
        SearchHit(
            url="https://www.theguardian.com/uk/2026/sep/12/coastal-defence?utm_source=x",
            canonical_url="https://theguardian.com/uk/2026/sep/12/coastal-defence",
            title="Ministers announce coastal defence plan",
            snippet="The department said work would start in March.",
            body_hash="sha256:6f1c2ab0",
            published_at="2026-09-12T08:30:00Z",
            publisher_domain="theguardian.com",
            publisher_id="theguardian.com",
            byline="A Reporter",
            wire_credit=None,
            source_adapter="guardian",
            query_id="q_exist_1",
            claim_id=None,
            language="en",
            relevance_score=0.91,
        ),
        SearchHit(
            url="https://www.smh.com.au/world/coastal-defence-20260912",
            canonical_url="https://smh.com.au/world/coastal-defence-20260912",
            title="Coastal defence plan announced",
            snippet="Work is due to start in March, the department said.",
            body_hash="sha256:6f1c2ab0",
            published_at="2026-09-12T22:05:00Z",
            publisher_domain="smh.com.au",
            publisher_id="smh.com.au",
            byline=None,
            wire_credit="Reuters",
            source_adapter="newsapi",
            query_id="q_claim_c3",
            claim_id="c3",
            language="en",
            relevance_score=0.74,
        ),
        SearchHit(
            url="https://example-local-news.test/story/4821",
            canonical_url="https://example-local-news.test/story/4821",
            title="Councils briefed on defence works a fortnight ago",
            snippet=None,
            body_hash=None,
            published_at=None,
            publisher_domain="example-local-news.test",
            publisher_id="example-local-news.test",
            byline=None,
            wire_credit=None,
            source_adapter="gnews",
            query_id="q_claim_c3",
            claim_id="c3",
            language=None,
            relevance_score=None,
        ),
    ]


def _payload() -> RetrievalPayload:
    return RetrievalPayload(
        planned_queries=_planned_queries(),
        planner_model="claude-sonnet-4-6",
        planner_template_version="2026.09.1",
        documents=_documents(),
        document_count=3,
        independent_sources=[
            IndependentSource(
                source_id="src-1",
                representative_url="https://theguardian.com/uk/2026/sep/12/coastal-defence",
                member_urls=["https://theguardian.com/uk/2026/sep/12/coastal-defence"],
                publisher_ids=["theguardian.com"],
                merge_reason="none",
                merge_evidence="Original reporting; nothing collapsed into it.",
            ),
            IndependentSource(
                source_id="src-2",
                representative_url="https://smh.com.au/world/coastal-defence-20260912",
                member_urls=[
                    "https://smh.com.au/world/coastal-defence-20260912",
                    "https://example-local-news.test/story/4821",
                ],
                publisher_ids=["smh.com.au", "example-local-news.test"],
                merge_reason="same_wire",
                merge_evidence="Both carry the same Reuters credit and body hash.",
            ),
        ],
        independent_source_count=2,
        existence_class="title_match",
        title_match_strength="loose",
        factchecks=[
            FactCheckRecord(
                claim_id="c3",
                reviewer_name="Example Fact Check",
                rating_text="Missing context",
                review_url="https://factcheck.test/reviews/coastal-defence",
                reviewed_claim_text="Treasury has signed off the three-year funding figure.",
            )
        ],
        entity_grounding=[
            EntityGrounding(
                entity_text="Department for Coastal Resilience",
                entity_type="ORG",
                entity_is_well_known=False,
                matched_title=None,
                near_match_suggestion="Department for Coastal Resilience and Flooding",
            )
        ],
        ranking_method="embedding_cosine",
        ranking_engine_name="char-ngram-cosine",
        coverage=CoverageReport(
            claims_total=6,
            claims_searched=["c1", "c3", "c4"],
            claims_skipped=["c2", "c5", "c6"],
            article_language="en",
            language_checks_applied=True,
            languages_covered=["en"],
            earliest_reachable_date="2026-08-15",
            adapters=[
                AdapterReport(
                    adapter="guardian",
                    status="ok",
                    queries_run=2,
                    hits_returned=1,
                    reason=None,
                    http_status=200,
                ),
                AdapterReport(
                    adapter="newsapi",
                    status="skipped_out_of_range",
                    queries_run=0,
                    hits_returned=0,
                    reason="Developer plan reaches back 29 days; article is older.",
                    http_status=None,
                ),
                AdapterReport(
                    adapter="factcheck",
                    status="skipped_no_key",
                    queries_run=0,
                    hits_returned=0,
                    reason="FACTCHECK_API_KEY is not set.",
                    http_status=None,
                ),
                AdapterReport(
                    adapter="gnews",
                    status="error",
                    queries_run=1,
                    hits_returned=0,
                    reason="HTTP 429 rate limited.",
                    http_status=429,
                ),
            ],
            scoring_fields_missing=["published_at", "body_hash"],
        ),
    )


def test_fully_populated_payload_round_trips() -> None:
    payload = _payload()
    dumped = payload.model_dump(mode="json")
    restored = RetrievalPayload.model_validate(dumped)
    assert restored == payload
    assert restored.model_dump(mode="json") == dumped


def test_json_dump_contains_no_python_objects() -> None:
    # mode="json" must produce something the store and the SSE stream can
    # serialise without a custom encoder.
    import json

    dumped = _payload().model_dump(mode="json")
    assert json.loads(json.dumps(dumped)) == dumped


def test_every_nested_model_survives_the_round_trip() -> None:
    restored = RetrievalPayload.model_validate(_payload().model_dump(mode="json"))
    assert [q.query_id for q in restored.planned_queries] == [
        "q_exist_1",
        "q_claim_c3",
        "q_fc_c3",
        "q_entity_0",
    ]
    assert restored.planned_queries[1].attempt == 2
    assert restored.documents[2].relevance_score is None
    assert restored.documents[2].language is None
    assert restored.independent_sources[1].merge_reason == "same_wire"
    assert restored.factchecks[0].rating_text == "Missing context"
    assert restored.entity_grounding[0].entity_is_well_known is False
    assert restored.coverage.adapters[3].http_status == 429


def test_document_count_and_independent_source_count_are_separate() -> None:
    # The whole point of the split: three pages, two newsrooms. Nothing in the
    # schema may collapse these into one number.
    payload = _payload()
    assert payload.document_count == len(payload.documents) == 3
    assert payload.independent_source_count == len(payload.independent_sources) == 2
    assert payload.document_count > payload.independent_source_count


def test_unknown_language_disables_language_checks() -> None:
    coverage = CoverageReport()
    assert coverage.article_language is None
    assert coverage.language_checks_applied is False


def test_empty_payload_defaults_are_safe() -> None:
    payload = RetrievalPayload()
    assert payload.existence_class == "not_found"
    assert payload.title_match_strength == "none"
    assert payload.document_count == 0
    assert payload.independent_source_count == 0
    assert payload.coverage.adapters == []
    assert RetrievalPayload.model_validate(payload.model_dump(mode="json")) == payload


@pytest.mark.parametrize(
    "field, value",
    [
        ("existence_class", "exact_url"),
        ("existence_class", "title_match"),
        ("existence_class", "near_duplicate"),
        ("existence_class", "syndicated"),
        ("existence_class", "not_found"),
        ("existence_class", "out_of_range"),
        ("title_match_strength", "exact"),
        ("title_match_strength", "loose"),
        ("title_match_strength", "keyword"),
        ("title_match_strength", "none"),
    ],
)
def test_enum_values_are_accepted(field: str, value: str) -> None:
    payload = RetrievalPayload(**{field: value})
    assert getattr(payload, field) == value


@pytest.mark.parametrize(
    "status",
    ["ok", "empty", "skipped_out_of_range", "skipped_no_key", "error"],
)
def test_adapter_status_values_are_accepted(status: str) -> None:
    report = AdapterReport(adapter="guardian", status=status)  # type: ignore[arg-type]
    assert AdapterReport.model_validate(report.model_dump(mode="json")).status == status


def test_capability_requires_every_reach_limit_to_be_stated() -> None:
    # None must be chosen deliberately, not inherited from a default, because
    # None means "unlimited / any" and would silently widen our claimed reach.
    with pytest.raises(ValueError):
        Capability(searches_full_text=True, requires_key=True)  # type: ignore[call-arg]
    cap = Capability(
        max_age_days=29,
        languages=["en"],
        regions=None,
        searches_full_text=False,
        requires_key=True,
    )
    assert Capability.model_validate(cap.model_dump(mode="json")) == cap


def test_envelope_carries_retrieval_without_disturbing_legacy_fields() -> None:
    envelope = RunEnvelope(run_id="test-run")
    assert envelope.retrieval is None
    envelope.retrieval = _payload()
    restored = RunEnvelope.model_validate(envelope.model_dump(mode="json"))
    assert restored.retrieval is not None
    assert restored.retrieval.independent_source_count == 2
    # Stage 5 migrates these; until then they must still exist and default.
    assert restored.queries.planner_mode == "deterministic"
    assert restored.evidence_items == []
    assert restored.wiki_hits == []
    assert restored.tool_results == []
    assert restored.corroboration.existence.existence_class == "not_found"


def test_legacy_envelopes_without_retrieval_still_validate() -> None:
    envelope = RunEnvelope.model_validate({"run_id": "old-run"})
    assert envelope.retrieval is None


def test_top_k_claims_setting_exists() -> None:
    assert Settings(retrieval_top_k_claims=3).retrieval_top_k_claims == 3
    assert Settings().retrieval_top_k_claims == 5
