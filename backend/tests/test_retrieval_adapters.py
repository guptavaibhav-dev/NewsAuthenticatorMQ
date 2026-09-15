from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import Settings
from app.retrieval.adapters import (
    ArticleContext,
    GdeltAdapter,
    GNewsAdapter,
    GoogleFactCheckAdapter,
    GuardianAdapter,
    NewsApiAdapter,
    NewsdataAdapter,
    WikipediaAdapter,
    news_adapters,
)
from app.retrieval.adapters.base import (
    article_age_days,
    build_hit,
    detect_wire_credit,
)
from app.retrieval.ladder import LadderResult, existence_queries, run_existence_ladder
from app.schemas.retrieval import PlannedQuery
from app.scoring.urls import canonical_url


def _settings(**kwargs) -> Settings:
    base = {
        "newsapi_key": "test-newsapi",
        "guardian_api_key": "test-guardian",
        "gnews_api_key": "test-gnews",
        "newsdata_api_key": "test-newsdata",
        "factcheck_api_key": "test-factcheck",
        "google_api_key": "",
        "gemini_api_key": "",
    }
    base.update(kwargs)
    return Settings(**base)


def _context(**kwargs) -> ArticleContext:
    base = {
        "published_at": _days_ago(2),
        "article_language": None,
        "canonical_url": "https://theguardian.com/uk/2026/sep/12/coastal-defence",
        "publisher_domain": "theguardian.com",
    }
    base.update(kwargs)
    return ArticleContext(**base)


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _query(
    query_id: str = "q_exist_1",
    *,
    kind: str = "existence",
    template_id: str = "exist_exact",
    attempt: int = 1,
    text: str = '"Ministers announce coastal defence plan"',
    claim_id: str | None = None,
) -> PlannedQuery:
    return PlannedQuery(
        query_id=query_id,
        kind=kind,  # type: ignore[arg-type]
        claim_id=claim_id,
        query_text=text,
        template_id=template_id,
        attempt=attempt,
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _run(adapter, handler, *, settings=None, context=None, query=None):
    async def _go():
        async with _client(handler) as client:
            return await adapter.search(
                client,
                query or _query(),
                settings=settings or _settings(),
                context=context or _context(),
            )

    return asyncio.run(_go())


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


NEWSAPI_OK = {
    "articles": [
        {
            "url": "https://www.smh.com.au/world/coastal-defence-20260912?utm_source=x",
            "title": "Coastal defence plan announced",
            "description": "Work is due to start in March.",
            "publishedAt": "2026-09-12T22:05:00Z",
            "author": "Staff writers with Reuters",
            "source": {"name": "The Sydney Morning Herald"},
        }
    ]
}


# --- capability gate ---------------------------------------------------------


def test_two_year_old_article_is_out_of_range_not_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the gate must run before any HTTP request")

    hits, report = _run(
        NewsApiAdapter.from_settings(_settings()),
        handler,
        context=_context(published_at=_days_ago(730)),
    )

    assert hits == []
    assert report.status == "skipped_out_of_range"
    assert report.hits_returned == 0
    assert report.queries_run == 0
    # The whole point of the rewrite: a reach limit is never an absence finding.
    assert report.status != "not_found"
    assert "not_found" not in (report.reason or "")
    assert "730 days old" in (report.reason or "")
    assert "30 days" in (report.reason or "")


def test_recent_article_passes_the_age_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    hits, report = _run(
        NewsApiAdapter.from_settings(_settings()),
        handler,
        context=_context(published_at=_days_ago(3)),
    )
    assert report.status == "ok"
    assert len(hits) == 1


def test_published_at_none_does_not_trigger_the_age_gate() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _json(NEWSAPI_OK)

    hits, report = _run(
        NewsApiAdapter.from_settings(_settings()),
        handler,
        context=_context(published_at=None),
    )

    assert seen, "an unknown date must not stop us from asking"
    assert report.status == "ok"
    assert len(hits) == 1
    assert "age check skipped" in (report.reason or "")


def test_unparseable_published_at_does_not_trigger_the_age_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    _hits, report = _run(
        NewsApiAdapter.from_settings(_settings()),
        handler,
        context=_context(published_at="last Tuesday-ish"),
    )
    assert report.status == "ok"
    assert "age check skipped" in (report.reason or "")


def test_article_language_none_does_not_trigger_the_language_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"response": {"results": []}})

    _hits, report = _run(
        GuardianAdapter(),
        handler,
        context=_context(article_language=None),
    )
    # Guardian declares languages=["en"], but an unknown language must not skip.
    assert report.status == "empty"
    assert "language check skipped" in (report.reason or "")


def test_known_unsupported_language_does_skip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the gate must run before any HTTP request")

    hits, report = _run(
        GuardianAdapter(),
        handler,
        context=_context(article_language="fr"),
    )
    assert hits == []
    assert report.status == "skipped_out_of_range"
    assert "fr" in (report.reason or "")


def test_missing_api_key_returns_skipped_no_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made without a key")

    hits, report = _run(
        NewsApiAdapter.from_settings(_settings(newsapi_key="")),
        handler,
        settings=_settings(newsapi_key=""),
    )
    assert hits == []
    assert report.status == "skipped_no_key"
    assert report.queries_run == 0
    assert "newsapi" in (report.reason or "")


def test_keyless_adapter_never_reports_skipped_no_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    _hits, report = _run(
        GdeltAdapter(),
        handler,
        settings=_settings(newsapi_key="", guardian_api_key=""),
    )
    assert report.status == "empty"


def test_age_gate_is_checked_before_the_key_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    _hits, report = _run(
        NewsApiAdapter.from_settings(_settings(newsapi_key="")),
        handler,
        settings=_settings(newsapi_key=""),
        context=_context(published_at=_days_ago(900)),
    )
    assert report.status == "skipped_out_of_range"


# --- error and empty handling ------------------------------------------------


def test_http_500_becomes_error_with_status_and_no_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "server exploded"})

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)

    assert hits == []
    assert report.status == "error"
    assert report.http_status == 500
    assert "server exploded" in (report.reason or "")


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
def test_error_statuses_never_raise(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert hits == []
    assert report.status == "error"
    assert report.http_status == status


def test_network_failure_becomes_error_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns went away")

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert hits == []
    assert report.status == "error"
    assert report.http_status is None


def test_timeout_becomes_error_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    _hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert report.status == "error"
    assert "timed out" in (report.reason or "")


def test_malformed_json_becomes_error_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert report.status == "error"


def test_successful_response_with_zero_results_is_empty_not_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert hits == []
    assert report.status == "empty"
    assert report.http_status == 200
    assert report.queries_run == 1


def test_gdelt_non_json_200_is_error_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Unrecognized query syntax")

    hits, report = _run(GdeltAdapter(), handler)
    assert hits == []
    assert report.status == "error"
    assert "non-JSON" in (report.reason or "")


# --- normalisation -----------------------------------------------------------


def test_hits_are_normalised_with_the_layer_1_canonicaliser() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    hits, _report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    hit = hits[0]

    raw = "https://www.smh.com.au/world/coastal-defence-20260912?utm_source=x"
    assert hit.url == raw
    # Not reimplemented here: the same function Layer 1 uses.
    assert hit.canonical_url == canonical_url(raw)
    assert "utm_source" not in hit.canonical_url
    assert hit.publisher_domain == "smh.com.au"
    assert hit.publisher_id == "smh.com.au"
    assert hit.source_adapter == "newsapi"
    assert hit.query_id == "q_exist_1"
    assert hit.claim_id is None


def test_claim_id_is_carried_onto_every_hit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    query = _query("q_claim_c3", kind="claim", template_id="claim_event", claim_id="c3")
    hits, _report = _run(NewsApiAdapter.from_settings(_settings()), handler, query=query)
    assert hits[0].claim_id == "c3"
    assert hits[0].query_id == "q_claim_c3"


def test_rows_without_a_url_are_dropped_not_crashed_on() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": [{"title": "No URL here"}, NEWSAPI_OK["articles"][0]]})

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert len(hits) == 1
    assert report.status == "ok"


def test_guardian_body_produces_a_body_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "response": {
                    "results": [
                        {
                            "webUrl": "https://www.theguardian.com/uk/2026/sep/12/coast",
                            "webTitle": "Coastal defence plan",
                            "fields": {
                                "headline": "Coastal defence plan",
                                "trailText": "Work starts in March.",
                                "bodyText": "The department said work would start in March.",
                                "byline": "A Reporter",
                                "firstPublicationDate": "2026-09-12T08:30:00Z",
                            },
                        }
                    ]
                }
            }
        )

    hits, _report = _run(GuardianAdapter(), handler)
    assert hits[0].body_hash is not None
    assert hits[0].body_hash.startswith("sha256:")
    assert hits[0].byline == "A Reporter"


def test_missing_body_leaves_body_hash_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    hits, _report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    # NewsAPI never returns body text, so reprint detection is simply blocked.
    assert hits[0].body_hash is None


# --- wire credit -------------------------------------------------------------


def test_wire_credit_matches_ap_as_a_token_but_not_inside_a_word() -> None:
    assert detect_wire_credit("By AP") == "AP"
    assert detect_wire_credit(None, "Reporting by AP.") == "AP"
    assert detect_wire_credit("(AP)") == "AP"

    assert detect_wire_credit("Cheap seats were available") is None
    assert detect_wire_credit("APPLE reported earnings") is None
    assert detect_wire_credit("The capital was quiet") is None
    assert detect_wire_credit("a shape appeared") is None


def test_longer_wire_names_win_over_bare_ap() -> None:
    assert detect_wire_credit("By The Associated Press") == "Associated Press"
    assert detect_wire_credit("Agence France-Presse reported") == "Agence France-Presse"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Reporting by Reuters", "Reuters"),
        ("AFP contributed", "AFP"),
        ("PA Media reports", "PA Media"),
        ("Bloomberg reported first", "Bloomberg"),
        ("ANI news agency", "ANI"),
        ("PTI wire copy", "PTI"),
        ("Staff reporter", None),
        ("", None),
        (None, None),
    ],
)
def test_wire_services_are_detected(text, expected) -> None:
    assert detect_wire_credit(text) == expected


def test_wire_credit_is_set_on_hits_from_the_byline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    hits, _report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    assert hits[0].wire_credit == "Reuters"


# --- other adapters ----------------------------------------------------------


def test_gnews_and_newsdata_normalise_into_search_hits() -> None:
    def gnews_handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "articles": [
                    {
                        "url": "https://example-news.test/a",
                        "title": "A story",
                        "description": "Body.",
                        "publishedAt": "2026-09-12T10:00:00Z",
                        "source": {"name": "Example News"},
                    }
                ]
            }
        )

    def newsdata_handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "results": [
                    {
                        "link": "https://example-news.test/b",
                        "title": "Another story",
                        "description": "Body.",
                        "pubDate": "2026-09-12 10:00:00",
                        "creator": ["R Reporter"],
                        "language": "english",
                    }
                ]
            }
        )

    hits, report = _run(GNewsAdapter.from_settings(_settings()), gnews_handler)
    assert report.status == "ok" and hits[0].source_adapter == "gnews"

    hits, report = _run(NewsdataAdapter.from_settings(_settings()), newsdata_handler)
    assert report.status == "ok" and hits[0].source_adapter == "newsdata"
    assert hits[0].byline == "R Reporter"


def test_gdelt_needs_no_key_and_parses_seendate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.gdeltproject.org" in str(request.url)
        return _json(
            {
                "articles": [
                    {
                        "url": "https://example-world.test/story",
                        "title": "Coastal defence",
                        "seendate": "20260912T120000Z",
                        "domain": "example-world.test",
                        "language": "English",
                    }
                ]
            }
        )

    hits, report = _run(GdeltAdapter(), handler, settings=_settings(newsapi_key=""))
    assert report.status == "ok"
    assert hits[0].published_at is not None
    assert hits[0].published_at.startswith("2026-09-12")
    assert hits[0].language == "English"


def test_factcheck_records_keep_the_reviewer_rating_verbatim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "claims": [
                    {
                        "text": "Treasury signed off the funding.",
                        "claimReview": [
                            {
                                "url": "https://factcheck.test/reviews/1",
                                "title": "Funding claim checked",
                                "textualRating": "Missing context",
                                "reviewDate": "2026-09-10",
                                "publisher": {"name": "Example Fact Check"},
                            }
                        ],
                    }
                ]
            }
        )

    adapter = GoogleFactCheckAdapter()
    query = _query("q_fc_c3", kind="factcheck", template_id="factcheck", claim_id="c3")

    async def _go():
        async with _client(handler) as client:
            return await adapter.search_records(
                client, query, settings=_settings(), context=_context()
            )

    records, report = asyncio.run(_go())
    assert report.status == "ok"
    assert records[0].rating_text == "Missing context"
    assert records[0].reviewer_name == "Example Fact Check"
    assert records[0].claim_id == "c3"


def test_factcheck_records_go_through_the_capability_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made without a key")

    adapter = GoogleFactCheckAdapter()
    settings = _settings(factcheck_api_key="", google_api_key="", gemini_api_key="")

    async def _go():
        async with _client(handler) as client:
            return await adapter.search_records(
                client, _query(), settings=settings, context=_context()
            )

    records, report = asyncio.run(_go())
    assert records == []
    assert report.status == "skipped_no_key"


def test_wikipedia_falls_back_to_wikidata_when_no_article_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "wikidata.org" in str(request.url):
            return _json(
                {
                    "search": [
                        {
                            "label": "Rachel Vance",
                            "description": "British civil servant",
                            "concepturi": "http://www.wikidata.org/entity/Q1",
                        }
                    ]
                }
            )
        return _json({"query": {"search": []}})

    hits, report = _run(
        WikipediaAdapter(),
        handler,
        query=_query("q_entity_0", kind="entity", template_id="entity_lookup", text="Rachel Vance"),
    )
    assert report.status == "ok"
    assert hits[0].title == "Rachel Vance"


def test_every_news_adapter_is_listed_even_without_keys() -> None:
    adapters = news_adapters(
        _settings(newsapi_key="", guardian_api_key="", gnews_api_key="", newsdata_api_key="")
    )
    names = [a.name for a in adapters]
    assert names == ["guardian", "newsapi", "gnews", "newsdata", "gdelt"]


def test_newsapi_max_age_comes_from_settings() -> None:
    assert Settings().newsapi_max_age_days == 30
    adapter = NewsApiAdapter.from_settings(_settings(newsapi_max_age_days=7))
    assert adapter.capabilities.max_age_days == 7


def test_article_age_days_handles_junk() -> None:
    assert article_age_days(None) is None
    assert article_age_days("") is None
    assert article_age_days("not a date") is None
    assert article_age_days(_days_ago(5)) == 5


# --- existence ladder --------------------------------------------------------


def _ladder(count: int = 3) -> list[PlannedQuery]:
    rungs = [
        _query("q_exist_1", template_id="exist_exact", attempt=1, text='"headline"'),
        _query("q_exist_2", template_id="exist_loose", attempt=2, text="headline"),
        _query("q_exist_3", template_id="exist_keyword", attempt=3, text="coastal defence"),
    ]
    return rungs[:count]


def _run_ladder(queries, handler, *, adapters=None, settings=None):
    async def _go():
        async with _client(handler) as client:
            return await run_existence_ladder(
                client,
                queries,
                adapters or [NewsApiAdapter.from_settings(_settings())],
                settings=settings or _settings(),
                context=_context(),
            )

    return asyncio.run(_go())


def test_ladder_stops_at_the_first_attempt_that_returns_hits() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params).get("q", "")
        seen.append(query)
        if query == '"headline"':
            return _json({"articles": []})
        return _json(NEWSAPI_OK)

    result = _run_ladder(_ladder(), handler)

    assert result.outcome == "matched"
    assert result.title_match_strength == "loose"
    assert result.attempts_run == ["q_exist_1", "q_exist_2"]
    assert "coastal defence" not in seen, "rung 3 must not run after rung 2 matched"
    assert len(result.hits) == 1


def test_ladder_first_rung_match_is_exact_strength() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    result = _run_ladder(_ladder(), handler)
    assert result.title_match_strength == "exact"
    assert result.attempts_run == ["q_exist_1"]


def test_ladder_third_rung_match_is_keyword_strength() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params).get("q", "")
        if query == "coastal defence":
            return _json(NEWSAPI_OK)
        return _json({"articles": []})

    result = _run_ladder(_ladder(), handler)
    assert result.title_match_strength == "keyword"
    assert result.attempts_run == ["q_exist_1", "q_exist_2", "q_exist_3"]


def test_exhausted_ladder_is_distinguishable_from_an_empty_one() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    exhausted = _run_ladder(_ladder(), handler)
    empty = _run_ladder([], handler)

    assert exhausted.title_match_strength == "none"
    assert empty.title_match_strength == "none"
    # Same strength, opposite meaning — the outcome field is what separates them.
    assert exhausted.outcome == "exhausted"
    assert empty.outcome == "not_planned"
    assert exhausted.searched is True
    assert empty.searched is False
    assert exhausted.attempts_run == ["q_exist_1", "q_exist_2", "q_exist_3"]
    assert empty.attempts_run == []
    assert empty.reports == []


def test_empty_ladder_makes_no_requests_and_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an empty ladder must issue no requests")

    result = _run_ladder([], handler)
    assert isinstance(result, LadderResult)
    assert result.hits == []
    assert result.outcome == "not_planned"


def test_two_rung_ladder_runs_without_inventing_a_third() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    result = _run_ladder(_ladder(2), handler)
    assert result.attempts_run == ["q_exist_1", "q_exist_2"]
    assert result.outcome == "exhausted"


def test_ladder_ignores_non_existence_queries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    plan = _ladder(1) + [
        _query("q_claim_c1", kind="claim", template_id="claim_event", claim_id="c1"),
        _query("q_entity_0", kind="entity", template_id="entity_lookup"),
    ]
    assert [q.query_id for q in existence_queries(plan)] == ["q_exist_1"]
    result = _run_ladder(plan, handler)
    assert result.attempts_run == ["q_exist_1"]


def test_ladder_collects_reports_from_skipped_adapters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"articles": []})

    settings = _settings(newsapi_key="")
    result = _run_ladder(
        _ladder(1),
        handler,
        adapters=[NewsApiAdapter.from_settings(settings)],
        settings=settings,
    )
    assert [r.status for r in result.reports] == ["skipped_no_key"]
    # An unrun adapter is still visible, rather than silently absent.
    assert result.outcome == "exhausted"


def test_ladder_survives_an_adapter_that_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "down"})

    result = _run_ladder(_ladder(1), handler)
    assert result.outcome == "exhausted"
    assert result.reports[0].status == "error"
    assert result.reports[0].http_status == 500


def test_build_hit_returns_none_without_a_url() -> None:
    assert build_hit(adapter="x", query=_query(), url=None, title="t") is None
    assert build_hit(adapter="x", query=_query(), url="  ", title="t") is None


def test_hits_serialise_as_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(NEWSAPI_OK)

    hits, report = _run(NewsApiAdapter.from_settings(_settings()), handler)
    dumped = [hit.model_dump(mode="json") for hit in hits] + [report.model_dump(mode="json")]
    assert json.loads(json.dumps(dumped)) == dumped
