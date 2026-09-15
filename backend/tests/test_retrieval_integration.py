"""Layer 3 end to end, through the real orchestrator.

These tests drive `execute_layer(state, 3, ...)` rather than calling
`run_retrieval` directly, so they cover the orchestrator switch, the snapshot
and re-run machinery, and the compat shim that keeps seven downstream consumers
alive — the parts most likely to break quietly.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.pipeline.orchestrator import LAYER_TITLES, execute_layer
from app.pipeline.store import RunState
from app.schemas.envelope import (
    Claim,
    ClassificationPayload,
    Entity,
    InputPayload,
    RunEnvelope,
)

ARTICLE = (
    "Ministers announced a coastal defence programme on Tuesday. The department "
    "said work would begin in March and run for four years at a cost of 1.2 "
    "billion pounds, with the first sites already selected."
)

HEADLINE = "Ministers announce coastal defence programme"


def _settings(**kwargs) -> Settings:
    base = {
        "newsapi_key": "k-newsapi",
        "guardian_api_key": "k-guardian",
        "gnews_api_key": "k-gnews",
        "newsdata_api_key": "k-newsdata",
        "factcheck_api_key": "k-factcheck",
        # No LLM or HF credentials: the planner stays deterministic and the
        # embedding engine uses its local fallback, so nothing leaves the test.
        "openai_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "google_api_key": "",
        "hf_token": "",
    }
    base.update(kwargs)
    return Settings(**base)


def _envelope(*, headline: str | None = HEADLINE) -> RunEnvelope:
    envelope = RunEnvelope(run_id="11111111-2222-3333-4444-555555555555")
    envelope.input = InputPayload(
        raw_text=ARTICLE,
        url="https://theguardian.com/uk/coastal-defence",
        fetched_title=headline,
        canonical_url="https://theguardian.com/uk/coastal-defence",
        publisher_domain="theguardian.com",
        publisher_id="theguardian.com",
        fetch_status="ok",
        fetch_reason="ok",
    )
    envelope.classification = ClassificationPayload(
        content_type="article",
        headline=headline,
        claims=[
            Claim(
                id="c1",
                text="Coastal defence work will begin in March and cost 1.2 billion pounds.",
                kind="fact",
                checkworthy=True,
            ),
            Claim(
                id="c2",
                text="The first sites have already been selected.",
                kind="fact",
                checkworthy=True,
            ),
        ],
        entities=[
            Entity(text="Ministers", type="ORG"),
            Entity(text="March", type="DATE"),
        ],
    )
    envelope.completed_layer = 2
    envelope.current_layer = 2
    return envelope


def _state(envelope: RunEnvelope) -> RunState:
    state = RunState(envelope=envelope)
    # Keep the test off the shared .runs/ directory.
    state.save = lambda: None  # type: ignore[method-assign]
    return state


NEWSAPI_ROWS = [
    {
        "url": "https://www.smh.com.au/world/coastal-defence-20260912",
        "title": "Ministers announce coastal defence programme",
        "description": ARTICLE,
        "publishedAt": "2026-09-12T22:05:00Z",
        "author": "Reuters",
        "source": {"name": "The Sydney Morning Herald"},
    },
    {
        "url": "https://www.theage.com.au/world/coastal-defence-20260912",
        "title": "Ministers announce coastal defence programme",
        "description": ARTICLE,
        "publishedAt": "2026-09-12T22:30:00Z",
        "author": "Reuters",
        "source": {"name": "The Age"},
    },
]


def _default_handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if "newsapi.org" in host:
        return httpx.Response(200, json={"articles": NEWSAPI_ROWS})
    if "guardianapis.com" in host:
        return httpx.Response(
            200,
            json={
                "response": {
                    "results": [
                        {
                            "webUrl": "https://www.theguardian.com/uk/coastal-defence",
                            "webTitle": HEADLINE,
                            "fields": {
                                "headline": HEADLINE,
                                "trailText": "Work starts in March.",
                                "bodyText": ARTICLE,
                                "byline": "A Reporter",
                                "firstPublicationDate": "2026-09-12T08:30:00Z",
                            },
                        }
                    ]
                }
            },
        )
    if "gnews.io" in host:
        return httpx.Response(200, json={"articles": []})
    if "newsdata.io" in host:
        return httpx.Response(200, json={"results": []})
    if "gdeltproject.org" in host:
        return httpx.Response(200, json={"articles": []})
    if "factchecktools" in host:
        return httpx.Response(
            200,
            json={
                "claims": [
                    {
                        "text": "Coastal defence funding was signed off.",
                        "claimReview": [
                            {
                                "url": "https://factcheck.test/reviews/1",
                                "title": "Funding claim checked",
                                "textualRating": "Missing context",
                                "publisher": {"name": "Example Fact Check"},
                            }
                        ],
                    }
                ]
            },
        )
    if "wikidata.org" in host:
        return httpx.Response(200, json={"search": []})
    if "wikipedia.org" in host:
        return httpx.Response(
            200, json={"query": {"search": [{"title": "Ministers", "snippet": "A post."}]}}
        )
    return httpx.Response(404, json={"message": "unexpected host"})


def _run_layer3(state: RunState, handler, *, settings: Settings | None = None, restore=False):
    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await execute_layer(
                state,
                3,
                settings=settings or _settings(),
                client=client,
                restore=restore,
            )

    asyncio.run(_go())
    return state.envelope


# --- the run completes -------------------------------------------------------


def test_full_layer_three_run_reaches_awaiting_decision() -> None:
    envelope = _run_layer3(_state(_envelope()), _default_handler)

    assert envelope.error is None
    assert envelope.status == "running"
    assert envelope.phase == "awaiting_decision"
    assert envelope.completed_layer == 3


def test_retrieval_payload_and_all_six_legacy_fields_are_populated() -> None:
    envelope = _run_layer3(_state(_envelope()), _default_handler)

    retrieval = envelope.retrieval
    assert retrieval is not None
    assert retrieval.planned_queries
    assert retrieval.documents
    assert retrieval.independent_sources
    assert retrieval.coverage.adapters

    # The shim, which stage 6 deletes.
    assert envelope.queries.quoted_headline
    assert envelope.evidence_items
    assert envelope.wiki_hits
    assert envelope.tool_results
    assert envelope.corroboration.existence.existence_class
    assert envelope.corroboration.fact_checks

    assert envelope.engines_used["verification_planner"]
    assert envelope.engines_used["embeddings"]


def test_syndicated_copies_collapse_to_one_independent_source() -> None:
    envelope = _run_layer3(_state(_envelope()), _default_handler)
    retrieval = envelope.retrieval
    assert retrieval is not None

    # Two Reuters-credited papers plus the Guardian original.
    assert retrieval.document_count > retrieval.independent_source_count
    assert any(
        source.merge_reason == "same_wire" for source in retrieval.independent_sources
    )


def test_trace_events_still_use_the_verification_layer_id() -> None:
    envelope = _run_layer3(_state(_envelope()), _default_handler)
    layer_three = [e for e in envelope.trace if e.layer == "verification"]

    # The frontend filters on this exact string; the display title changed but
    # the id must not.
    assert layer_three
    assert LAYER_TITLES[3] == "Retrieval and Independence"


def test_evidence_source_ids_are_unique_and_resolvable() -> None:
    envelope = _run_layer3(_state(_envelope()), _default_handler)
    ids = [item.source_id for item in envelope.evidence_items]
    assert len(ids) == len(set(ids))
    assert all(item.url for item in envelope.evidence_items)


# --- queries are frozen before dispatch --------------------------------------


def test_planned_queries_exist_before_the_first_http_call() -> None:
    state = _state(_envelope())
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Inspect live envelope state at the moment of the first request.
        retrieval = state.envelope.retrieval
        seen.append(len(retrieval.planned_queries) if retrieval else -1)
        return _default_handler(request)

    _run_layer3(state, handler)

    assert seen, "expected at least one HTTP call"
    # -1 would mean envelope.retrieval was still None when we dispatched.
    assert seen[0] > 0
    assert all(count == seen[0] for count in seen)


def test_rerun_issues_byte_identical_planned_queries() -> None:
    state = _state(_envelope())
    first = _run_layer3(state, _default_handler)
    before = [query.model_dump(mode="json") for query in first.retrieval.planned_queries]

    # The real re-run path: restore the layer-3 snapshot, then execute again.
    second = _run_layer3(state, _default_handler, restore=True)
    after = [query.model_dump(mode="json") for query in second.retrieval.planned_queries]

    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)


def test_rerun_does_not_accumulate_documents_or_trace_across_runs() -> None:
    state = _state(_envelope())
    first = _run_layer3(state, _default_handler)
    first_docs = first.retrieval.document_count
    first_tools = len(first.tool_results)

    second = _run_layer3(state, _default_handler, restore=True)

    assert second.retrieval.document_count == first_docs
    assert len(second.tool_results) == first_tools


def test_replayed_plan_is_reused_when_the_envelope_still_holds_one() -> None:
    from app.retrieval.run import _stored_plan

    state = _state(_envelope())
    envelope = _run_layer3(state, _default_handler)

    # Without a snapshot rewind the frozen plan is still there and is reused
    # verbatim rather than re-planned.
    replayed = _stored_plan(envelope)
    assert replayed is not None
    assert [q.query_id for q in replayed] == [
        q.query_id for q in envelope.retrieval.planned_queries
    ]


# --- failure containment -----------------------------------------------------


def test_one_failing_adapter_does_not_abort_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "newsapi.org" in request.url.host:
            return httpx.Response(500, json={"message": "newsapi is down"})
        return _default_handler(request)

    envelope = _run_layer3(_state(_envelope()), handler)

    assert envelope.error is None
    assert envelope.phase == "awaiting_decision"
    reports = {r.adapter: r for r in envelope.retrieval.coverage.adapters}
    assert reports["newsapi"].status == "error"
    assert reports["newsapi"].http_status == 500
    # The other adapters still delivered.
    assert envelope.retrieval.documents


def test_every_adapter_failing_still_produces_a_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "everything is down"})

    envelope = _run_layer3(_state(_envelope()), handler)

    assert envelope.error is None
    assert envelope.retrieval is not None
    assert envelope.retrieval.document_count == 0
    assert envelope.retrieval.independent_source_count == 0
    # We searched and found nothing we could use. Never a verdict.
    assert envelope.retrieval.existence_class in {"not_found", "out_of_range"}
    assert envelope.retrieval.planned_queries


def test_network_errors_are_contained_by_the_adapter_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    envelope = _run_layer3(_state(_envelope()), handler)
    assert envelope.error is None
    assert all(r.status == "error" for r in envelope.retrieval.coverage.adapters)


def test_adapter_contract_is_that_search_never_raises() -> None:
    """The gather relies on this, so assert it rather than assume it."""
    from app.retrieval.adapters import news_adapters
    from app.retrieval.adapters.base import ArticleContext
    from app.schemas.retrieval import PlannedQuery

    class Exploding(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise RuntimeError("a transport that misbehaves in an unexpected way")

    query = PlannedQuery(
        query_id="q_exist_1",
        kind="existence",
        query_text='"anything"',
        template_id="exist_exact",
    )
    settings = _settings()

    async def _go():
        async with httpx.AsyncClient(transport=Exploding()) as client:
            for adapter in news_adapters(settings):
                hits, report = await adapter.search(
                    client, query, settings=settings, context=ArticleContext()
                )
                assert hits == []
                assert report.status == "error"

    asyncio.run(_go())


# --- the lossy shim mapping --------------------------------------------------


def _empty_handler(request: httpx.Request) -> httpx.Response:
    """Every source answers successfully with nothing."""
    host = request.url.host
    if "guardianapis.com" in host:
        return httpx.Response(200, json={"response": {"results": []}})
    if "newsdata.io" in host:
        return httpx.Response(200, json={"results": []})
    if "factchecktools" in host:
        return httpx.Response(200, json={"claims": []})
    if "wikipedia.org" in host or "wikidata.org" in host:
        return httpx.Response(200, json={"query": {"search": []}, "search": []})
    return httpx.Response(200, json={"articles": []})


def test_out_of_range_becomes_not_found_in_the_shim_only() -> None:
    # No headline means no existence query was ever built, so we never looked.
    envelope = _run_layer3(_state(_envelope(headline=None)), _empty_handler)
    retrieval = envelope.retrieval
    assert retrieval is not None

    assert retrieval.coverage.existence_search == "not_planned"
    assert retrieval.coverage.existence_rungs_planned == 0
    # The truth survives on envelope.retrieval …
    assert retrieval.existence_class == "out_of_range"
    # … and is flattened only for the legacy consumers, because the old enum
    # cannot express "we could not look". This dies with the shim in stage 6.
    assert envelope.corroboration.existence.existence_class == "not_found"


@pytest.mark.parametrize(
    "modern, legacy",
    [
        ("exact_url", "exact_url_match"),
        ("title_match", "title_match"),
        ("near_duplicate", "near_duplicate"),
        ("syndicated", "syndicated_or_reprint"),
        ("not_found", "not_found"),
        ("out_of_range", "not_found"),
    ],
)
def test_legacy_existence_mapping(modern, legacy) -> None:
    from app.retrieval.run import legacy_existence_class

    assert legacy_existence_class(modern) == legacy


def test_documentation_template_reads_independent_sources_not_pages() -> None:
    """Layer 7 must survive a real retrieval payload — it used to crash on
    IndependentSource.publisher_id, a field that does not exist."""
    from app.layers.documentation import template_record

    envelope = _run_layer3(_state(_envelope()), _default_handler)
    record = template_record(envelope)
    retrieval = envelope.retrieval
    assert retrieval is not None
    assert str(retrieval.independent_source_count) in record.source_assessment
    assert str(retrieval.document_count) in record.source_assessment
    assert "not as falsity" not in record.source_assessment or retrieval.document_count == 0


def test_coverage_reports_that_the_age_check_never_ran() -> None:
    # Nothing on InputPayload carries a publication date, so every adapter with
    # an archive limit records that its age gate was skipped.
    envelope = _run_layer3(_state(_envelope()), _default_handler)
    notes = " ".join(envelope.retrieval.coverage.capability_notes)
    assert "age check skipped" in notes
    assert envelope.retrieval.coverage.language_checks_applied is False
    assert envelope.retrieval.coverage.article_language is None
