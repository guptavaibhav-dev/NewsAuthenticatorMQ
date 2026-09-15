"""Layer 3's core claim under test: volume is not corroboration.

The assertions that matter here are the ones separating `document_count` from
`independent_source_count`. If those ever collapse into one number, the tool
tells a journalist that one wire story republished twenty times is twenty
newsrooms agreeing, which is the single most damaging thing it could say.
"""

from __future__ import annotations

import asyncio
import re

import numpy as np
import pytest

from app.retrieval.adapters.base import ArticleContext, body_hash
from app.retrieval.independence import (
    PlanCoverage,
    build_coverage_report,
    build_payload,
    classify_existence,
    dedupe,
    ownership_map,
    parent_group,
    resolve_independence,
    shingle_jaccard,
    shingles,
)
from app.retrieval.ladder import LadderResult
from app.retrieval.ranking import (
    NEAR_DUPLICATE_THRESHOLD,
    RELEVANCE_FLOOR,
    rank,
    ranking_method_for,
)
from app.schemas.retrieval import AdapterReport, Capability, CoverageReport, SearchHit

WIRE_BODY = (
    "Ministers announced a coastal defence programme on Tuesday, saying work "
    "would begin in March and run for four years at a cost of 1.2 billion "
    "pounds. The department said the first sites had been selected."
)

OTHER_BODY = (
    "A parliamentary committee questioned the transport secretary about rail "
    "fares on Wednesday, hearing evidence from three operators about ticketing "
    "systems and the timetable review announced last autumn."
)


def _hit(
    domain: str,
    *,
    title: str = "Coastal defence plan announced",
    snippet: str = WIRE_BODY,
    wire: str | None = None,
    path: str = "/story",
    publisher_id: str | None = None,
    byline: str | None = None,
    published_at: str | None = "2026-09-12T08:30:00Z",
    body_hash_value: str | None = None,
    claim_id: str | None = None,
    url: str | None = None,
    adapter: str = "newsapi",
    canonical: str | None = None,
) -> SearchHit:
    resolved = url or f"https://{domain}{path}"
    return SearchHit(
        url=resolved,
        canonical_url=resolved if canonical is None else canonical,
        title=title,
        snippet=snippet,
        body_hash=body_hash_value,
        published_at=published_at,
        publisher_domain=domain,
        publisher_id=publisher_id or domain,
        byline=byline,
        wire_credit=wire,
        source_adapter=adapter,
        query_id="q_exist_1",
        claim_id=claim_id,
    )


def _context(**kwargs) -> ArticleContext:
    base = {
        "published_at": "2026-09-12T08:30:00Z",
        "article_language": None,
        "canonical_url": "https://theguardian.com/uk/coastal-defence",
        "publisher_domain": "theguardian.com",
        "headline": "Coastal defence plan announced",
    }
    base.update(kwargs)
    return ArticleContext(**base)


def _ladder(outcome: str = "exhausted", strength: str = "none") -> LadderResult:
    return LadderResult(
        hits=[],
        title_match_strength=strength,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        attempts_run=["q_exist_1"] if outcome != "not_planned" else [],
    )


class StubEmbeddings:
    """Deterministic stand-in for EmbeddingEngine, in the style of FakeLLM.

    Vectors come from a fixed word-position hash rather than Python's `hash`,
    so the same text yields the same vector in every process.
    """

    def __init__(self, engine_name: str = "hf:test-embed", fail: bool = False):
        self.engine_name = engine_name
        self.fail = fail
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding backend unavailable")
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        vec = np.zeros(64, dtype=np.float32)
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vec[sum(ord(char) for char in word) % 64] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec


# --- the headline result -----------------------------------------------------


def test_twenty_papers_one_reuters_story_is_one_source() -> None:
    papers = [
        "smh.com.au", "theage.com.au", "nzherald.co.nz", "straitstimes.com",
        "irishtimes.com", "thehindu.com", "japantimes.co.jp", "dawn.com",
        "gulfnews.com", "channelnewsasia.com", "brecorder.com", "thestar.com.my",
        "bangkokpost.com", "manilatimes.net", "jpost.com", "haaretz.com",
        "kathmandupost.com", "dhakatribune.com", "arabnews.com", "thenationalnews.com",
    ]
    hits = [
        _hit(domain, wire="Reuters", byline="Reuters", path=f"/{index}")
        for index, domain in enumerate(papers)
    ]

    documents = dedupe(hits)
    sources = resolve_independence(documents)

    # Twenty real pages survive dedupe: they are twenty documents.
    assert len(documents) == 20
    # But one newsroom wrote the story. This is the number that matters.
    assert len(sources) == 1
    assert sources[0].merge_reason == "same_wire"
    assert len(sources[0].member_urls) == 20

    payload = build_payload(
        hits=hits,
        ladder=_ladder(),
        context=_context(),
        coverage=CoverageReport(),
    )
    assert payload.document_count == 20
    assert payload.independent_source_count == 1


def test_wire_merge_evidence_names_the_wire_and_the_outlets() -> None:
    hits = [
        _hit("smh.com.au", wire="Reuters", path="/a"),
        _hit("theage.com.au", wire="Reuters", path="/b"),
        _hit("nzherald.co.nz", wire="Reuters", path="/c"),
    ]
    source = resolve_independence(dedupe(hits))[0]

    evidence = source.merge_evidence
    assert "Reuters" in evidence
    assert "smh.com.au" in evidence
    # A smaller number is not checkable unless the reader can see the grounds.
    assert "independent confirmations" in evidence


def test_two_mastheads_under_one_parent_are_one_source() -> None:
    hits = [
        _hit("smh.com.au", snippet=WIRE_BODY, path="/a"),
        _hit("theage.com.au", snippet=OTHER_BODY, title="Rail fares", path="/b"),
    ]
    sources = resolve_independence(dedupe(hits))

    # Different stories, same owner: still one newsroom for counting purposes.
    assert len(sources) == 1
    assert sources[0].merge_reason == "same_owner"
    assert "nine_entertainment" in sources[0].merge_evidence
    assert sorted(sources[0].publisher_ids) == ["smh.com.au", "theage.com.au"]


def test_three_unrelated_newsrooms_stay_three_sources() -> None:
    hits = [
        _hit("bbc.co.uk", snippet=WIRE_BODY, path="/a"),
        _hit("nytimes.com", snippet=OTHER_BODY, title="Rail fares", path="/b"),
        _hit("aljazeera.com", snippet="An unrelated report about shipping lanes.",
             title="Shipping", path="/c"),
    ]
    sources = resolve_independence(dedupe(hits))

    assert len(sources) == 3
    assert {source.merge_reason for source in sources} == {"none"}
    assert all("Stands alone" in source.merge_evidence for source in sources)


def test_unknown_domain_stays_independent_and_does_not_crash() -> None:
    hits = [
        _hit("bbc.co.uk", path="/a"),
        _hit("a-local-paper-nobody-mapped.example", snippet=OTHER_BODY,
             title="Local", path="/b"),
        _hit("another-unmapped-outlet.test", snippet="Something else entirely.",
             title="Other", path="/c"),
    ]
    assert parent_group("a-local-paper-nobody-mapped.example") is None

    sources = resolve_independence(dedupe(hits))
    # Absent from the map means unknown, never "independently owned" — but the
    # safe default is to leave it standing alone rather than guess a parent.
    assert len(sources) == 3


def test_same_wire_beats_same_owner_on_a_document_matching_both() -> None:
    # Both are Nine mastheads AND both carry the same Reuters credit.
    hits = [
        _hit("smh.com.au", wire="Reuters", path="/a"),
        _hit("theage.com.au", wire="Reuters", path="/b"),
    ]
    sources = resolve_independence(dedupe(hits))

    assert len(sources) == 1
    # The wire is the more specific and more consequential explanation.
    assert sources[0].merge_reason == "same_wire"
    assert "Reuters" in sources[0].merge_evidence


def test_reprint_groups_unrelated_publishers_without_a_wire_credit() -> None:
    hits = [
        _hit("first-outlet.test", path="/a"),
        _hit("second-outlet.test", path="/b"),
    ]
    sources = resolve_independence(dedupe(hits))

    assert len(sources) == 1
    assert sources[0].merge_reason == "reprint"
    assert "no wire credit" in sources[0].merge_evidence


def test_different_wires_are_not_merged() -> None:
    hits = [
        _hit("first-outlet.test", wire="Reuters", path="/a"),
        _hit("second-outlet.test", wire="AFP", path="/b"),
    ]
    sources = resolve_independence(dedupe(hits))
    # Two agencies covering one event independently is real corroboration.
    assert len(sources) == 2


# --- dedupe ------------------------------------------------------------------


def test_dedupe_collapses_the_same_canonical_url() -> None:
    hits = [
        _hit("bbc.co.uk", path="/story", adapter="newsapi"),
        _hit("bbc.co.uk", path="/story", adapter="gdelt", byline="A Reporter"),
    ]
    documents = dedupe(hits)
    assert len(documents) == 1
    # The more complete record wins, so nothing is lost by collapsing.
    assert documents[0].byline == "A Reporter"


def test_dedupe_collapses_near_identical_text_from_one_publisher() -> None:
    hits = [
        _hit("bbc.co.uk", path="/story"),
        _hit("bbc.co.uk", path="/story/amp"),
    ]
    assert len(dedupe(hits)) == 1


def test_dedupe_does_not_collapse_across_publishers() -> None:
    # The single most important restriction in this module. If near-identical
    # text merged across mastheads, syndication would vanish before
    # resolve_independence ever got to name it.
    hits = [_hit(f"outlet{i}.test", wire="Reuters", path=f"/{i}") for i in range(20)]
    assert len(dedupe(hits)) == 20


def test_dedupe_uses_body_hash_when_both_sides_have_one() -> None:
    same = body_hash(WIRE_BODY)
    hits = [
        _hit("bbc.co.uk", path="/a", body_hash_value=same, title="One wording"),
        _hit("bbc.co.uk", path="/b", body_hash_value=same, title="Another wording"),
    ]
    assert len(dedupe(hits)) == 1


def test_dedupe_keeps_distinct_stories_from_one_publisher() -> None:
    hits = [
        _hit("bbc.co.uk", path="/a", snippet=WIRE_BODY),
        _hit("bbc.co.uk", path="/b", snippet=OTHER_BODY, title="Rail fares"),
    ]
    assert len(dedupe(hits)) == 2


def test_dedupe_is_idempotent() -> None:
    hits = [_hit(f"outlet{i}.test", wire="Reuters", path=f"/{i}") for i in range(5)]
    once = dedupe(hits)
    assert [h.url for h in dedupe(once)] == [h.url for h in once]


def test_shingles_handle_text_shorter_than_the_window() -> None:
    assert shingles("two words") == frozenset({("two", "words")})
    assert shingle_jaccard("two words", "two words") == 1.0
    assert shingles("") == frozenset()
    assert shingle_jaccard("", "anything") == 0.0


def test_empty_input_produces_no_documents_or_sources() -> None:
    assert dedupe([]) == []
    assert resolve_independence([]) == []


# --- ownership map -----------------------------------------------------------


def test_ownership_map_loads_and_is_a_flat_domain_mapping() -> None:
    table = ownership_map()
    assert len(table) >= 30
    assert table["reuters.com"] == "thomson_reuters"
    assert table["apnews.com"] == "associated_press"
    assert table["smh.com.au"] == table["theage.com.au"] == "nine_entertainment"
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in table.items())


def test_ownership_map_covers_the_named_seed_groups() -> None:
    groups = set(ownership_map().values())
    for expected in (
        "thomson_reuters", "associated_press", "afp", "news_corp",
        "nine_entertainment", "hearst", "gannett", "dmg_media",
        "guardian_media_group", "axel_springer", "bertelsmann", "times_group",
        "sinclair", "tribune_publishing",
    ):
        assert expected in groups
    assert len(groups) >= 30


def test_parent_group_resolves_from_a_hit_or_a_bare_domain() -> None:
    assert parent_group("theguardian.com") == "guardian_media_group"
    assert parent_group("https://www.theguardian.com/uk/story") == "guardian_media_group"
    assert parent_group(_hit("wsj.com")) == "news_corp"
    assert parent_group("") is None
    assert parent_group(None) is None


# --- ranking -----------------------------------------------------------------


class _Claim:
    def __init__(self, claim_id: str, text: str):
        self.id = claim_id
        self.text = text


def _rank(hits, claims, embeddings):
    async def _go():
        return await rank(hits, claims, embeddings)

    return asyncio.run(_go())


def test_ranking_is_deterministic_for_identical_input() -> None:
    hits = [
        _hit("bbc.co.uk", path="/a", snippet=WIRE_BODY),
        _hit("nytimes.com", path="/b", snippet=OTHER_BODY, title="Rail fares"),
        _hit("aljazeera.com", path="/c", snippet="Shipping lanes report.",
             title="Shipping"),
    ]
    claims = [_Claim("c1", "Work on coastal defences begins in March.")]

    first = _rank(hits, claims, StubEmbeddings())
    second = _rank(hits, claims, StubEmbeddings())

    assert [h.url for h in first.hits] == [h.url for h in second.hits]
    assert [h.relevance_score for h in first.hits] == [
        h.relevance_score for h in second.hits
    ]
    assert first.hits[0].relevance_score >= first.hits[-1].relevance_score


def test_ranking_scores_a_hit_against_the_claim_it_was_retrieved_for() -> None:
    hits = [_hit("bbc.co.uk", path="/a", snippet=WIRE_BODY, claim_id="c2")]
    claims = [
        _Claim("c1", "An unrelated statement about shipping lanes."),
        _Claim("c2", "Coastal defence work begins in March."),
    ]
    result = _rank(hits, claims, StubEmbeddings())
    assert result.hits[0].relevance_score is not None


def test_ranking_method_reflects_the_engine_actually_used() -> None:
    hits = [_hit("bbc.co.uk")]
    claims = [_Claim("c1", "Coastal defence work begins in March.")]

    hosted = _rank(hits, claims, StubEmbeddings("hf:sentence-transformers/all-mpnet-base-v2"))
    assert hosted.ranking_method == "embedding"
    assert hosted.ranking_engine_name == "hf:sentence-transformers/all-mpnet-base-v2"

    # The degraded path must be visible, not silent: its scores are on an
    # entirely different scale from the hosted engine's.
    degraded = _rank(hits, claims, StubEmbeddings("char-ngram-cosine"))
    assert degraded.ranking_method == "char-ngram"
    assert degraded.ranking_engine_name == "char-ngram-cosine"
    assert hosted.ranking_method != degraded.ranking_method


@pytest.mark.parametrize(
    "engine_name, expected",
    [
        ("hf:any/model", "embedding"),
        ("char-ngram-cosine", "char-ngram"),
        ("char-trigram-cosine", "char-ngram"),
        ("", ""),
        ("something-new", "something-new"),
    ],
)
def test_ranking_method_labels_the_scale(engine_name, expected) -> None:
    assert ranking_method_for(engine_name) == expected


def test_ranking_without_claims_leaves_scores_and_method_unset() -> None:
    result = _rank([_hit("bbc.co.uk")], [], StubEmbeddings())
    assert result.ranking_method == ""
    assert result.ranking_engine_name == ""
    # Unranked, not irrelevant.
    assert result.hits[0].relevance_score is None


def test_ranking_failure_keeps_the_documents() -> None:
    hits = [_hit("bbc.co.uk"), _hit("nytimes.com", path="/b")]
    claims = [_Claim("c1", "Coastal defence work begins in March.")]
    result = _rank(hits, claims, StubEmbeddings(fail=True))

    assert len(result.hits) == 2
    assert result.ranking_method == ""


def test_thresholds_are_documented_as_char_trigram_tuned() -> None:
    # Guards the constants against a silent edit; the comment above them
    # records that neither transfers to semantic embeddings.
    assert RELEVANCE_FLOOR == 0.22
    assert NEAR_DUPLICATE_THRESHOLD == 0.88


# --- coverage report ---------------------------------------------------------


class _StubAdapter:
    def __init__(self, name, *, max_age_days=None, languages=None, requires_key=True):
        self.name = name
        self.capabilities = Capability(
            max_age_days=max_age_days,
            languages=languages,
            regions=None,
            searches_full_text=False,
            requires_key=requires_key,
        )


def _report(adapter, status, **kwargs) -> AdapterReport:
    return AdapterReport(adapter=adapter, status=status, **kwargs)


def test_coverage_distinguishes_not_planned_from_exhausted() -> None:
    adapters = [_StubAdapter("newsapi", max_age_days=30, languages=["en"])]
    reports = [_report("newsapi", "empty", queries_run=1)]

    exhausted = build_coverage_report(
        adapter_reports=reports,
        adapters=adapters,
        context=_context(),
        ladder=_ladder("exhausted"),
        plan=PlanCoverage(existence_rungs_planned=3),
    )
    never_looked = build_coverage_report(
        adapter_reports=reports,
        adapters=adapters,
        context=_context(headline=None),
        ladder=_ladder("not_planned"),
        plan=PlanCoverage(existence_rungs_planned=0),
    )

    assert exhausted.existence_search == "exhausted"
    assert never_looked.existence_search == "not_planned"
    # Both report nothing found; only this field says whether we looked, and a
    # reader gets it without counting planned_queries.
    assert exhausted.existence_rungs_planned == 3
    assert never_looked.existence_rungs_planned == 0


def test_coverage_surfaces_gate_notes_from_the_adapters() -> None:
    reports = [
        _report(
            "newsapi",
            "ok",
            queries_run=1,
            hits_returned=2,
            checks_skipped=["age"],
            reason="age check skipped: the submitted article has no usable date",
        ),
        _report(
            "guardian",
            "empty",
            queries_run=1,
            checks_skipped=["language"],
            reason="language check skipped: the article's language is unknown",
        ),
        _report("gnews", "skipped_no_key", reason="no API key configured for gnews"),
    ]
    coverage = build_coverage_report(
        adapter_reports=reports,
        adapters=[_StubAdapter("newsapi", max_age_days=30, languages=["en"])],
        context=_context(),
        ladder=_ladder("exhausted"),
        plan=PlanCoverage(),
    )

    joined = " ".join(coverage.capability_notes)
    assert "newsapi: age check skipped" in joined
    assert "guardian: language check skipped" in joined
    # A skipped adapter has no gate note to report; it is a different signal
    # and stays in the adapter reports where it belongs.
    assert not any(note.startswith("gnews:") for note in coverage.capability_notes)
    assert len(coverage.adapters) == 3


def test_coverage_records_the_all_stopword_headline_case() -> None:
    coverage = build_coverage_report(
        adapter_reports=[_report("newsapi", "empty", queries_run=1)],
        adapters=[_StubAdapter("newsapi", max_age_days=30)],
        context=_context(),
        ladder=_ladder("exhausted"),
        plan=PlanCoverage(existence_rungs_planned=2, keyword_rung_skipped=True),
    )
    assert coverage.existence_rungs_planned == 2
    assert coverage.existence_keyword_rung_skipped is True
    assert coverage.existence_search == "exhausted"


def test_three_narrowing_signals_are_independently_readable() -> None:
    coverage = build_coverage_report(
        adapter_reports=[
            _report("newsapi", "empty", queries_run=1, checks_skipped=["age"],
                    reason="age check skipped: no usable publication date"),
        ],
        adapters=[_StubAdapter("newsapi", max_age_days=30, languages=["en"])],
        context=_context(),
        ladder=_ladder("not_planned"),
        plan=PlanCoverage(existence_rungs_planned=2, keyword_rung_skipped=True),
    )
    # Gate notes, ladder outcome, and the thin-headline case are three separate
    # facts and must not be inferable only from each other.
    assert coverage.capability_notes
    assert coverage.existence_search == "not_planned"
    assert coverage.existence_keyword_rung_skipped is True


def test_language_checks_are_not_applied_when_the_language_is_unknown() -> None:
    adapters = [_StubAdapter("guardian", languages=["en"])]
    unknown = build_coverage_report(
        adapter_reports=[_report("guardian", "ok", queries_run=1, hits_returned=1)],
        adapters=adapters,
        context=_context(article_language=None),
        ladder=_ladder(),
        plan=PlanCoverage(),
    )
    known = build_coverage_report(
        adapter_reports=[_report("guardian", "ok", queries_run=1, hits_returned=1)],
        adapters=adapters,
        context=_context(article_language="en"),
        ladder=_ladder(),
        plan=PlanCoverage(),
    )

    assert unknown.article_language is None
    assert unknown.language_checks_applied is False
    assert known.language_checks_applied is True


def test_languages_covered_says_any_for_an_unrestricted_adapter() -> None:
    coverage = build_coverage_report(
        adapter_reports=[
            _report("guardian", "ok", queries_run=1, hits_returned=1),
            _report("gdelt", "empty", queries_run=1),
        ],
        adapters=[
            _StubAdapter("guardian", languages=["en"]),
            _StubAdapter("gdelt", languages=None, requires_key=False),
        ],
        context=_context(),
        ladder=_ladder(),
        plan=PlanCoverage(),
    )
    assert coverage.languages_covered == ["any", "en"]


def test_skipped_adapters_do_not_contribute_coverage() -> None:
    coverage = build_coverage_report(
        adapter_reports=[
            _report("guardian", "skipped_no_key", reason="no API key"),
            _report("newsapi", "ok", queries_run=1, hits_returned=1),
        ],
        adapters=[
            _StubAdapter("guardian", languages=["en"]),
            _StubAdapter("newsapi", max_age_days=30, languages=["en", "fr"]),
        ],
        context=_context(),
        ladder=_ladder(),
        plan=PlanCoverage(),
    )
    # Guardian never ran, so its unlimited archive must not be claimed as reach.
    assert coverage.languages_covered == ["en", "fr"]
    assert coverage.earliest_reachable_date is not None


def test_earliest_reachable_date_is_none_when_any_running_adapter_is_unbounded() -> None:
    coverage = build_coverage_report(
        adapter_reports=[
            _report("guardian", "ok", queries_run=1, hits_returned=1),
            _report("newsapi", "empty", queries_run=1),
        ],
        adapters=[
            _StubAdapter("guardian", max_age_days=None),
            _StubAdapter("newsapi", max_age_days=30),
        ],
        context=_context(),
        ladder=_ladder(),
        plan=PlanCoverage(),
    )
    assert coverage.earliest_reachable_date is None


def test_coverage_carries_searched_and_skipped_claim_ids() -> None:
    coverage = build_coverage_report(
        adapter_reports=[],
        adapters=[],
        context=_context(),
        ladder=_ladder(),
        plan=PlanCoverage(
            claims_total=5,
            claims_searched=["c1", "c2"],
            claims_skipped=["c3", "c4", "c5"],
            fields_missing=["checkworthy"],
        ),
        scoring_fields_missing=["body_hash"],
    )
    assert coverage.claims_total == 5
    assert coverage.claims_searched == ["c1", "c2"]
    assert coverage.claims_skipped == ["c3", "c4", "c5"]
    assert coverage.scoring_fields_missing == ["body_hash", "checkworthy"]


# --- existence classification and counts -------------------------------------


def test_exact_url_match_against_the_submitted_article() -> None:
    context = _context(canonical_url="https://bbc.co.uk/story")
    documents = dedupe([_hit("bbc.co.uk", path="/story")])
    assert classify_existence(
        documents=documents,
        sources=resolve_independence(documents),
        ladder=_ladder("matched", "exact"),
        context=context,
    ) == "exact_url"


def test_a_syndicated_article_is_classed_as_syndicated_not_corroborated() -> None:
    hits = [
        _hit("smh.com.au", wire="Reuters", path="/a"),
        _hit("theage.com.au", wire="Reuters", path="/b"),
        _hit("nzherald.co.nz", wire="Reuters", path="/c"),
    ]
    documents = dedupe(hits)
    sources = resolve_independence(documents)
    assert classify_existence(
        documents=documents,
        sources=sources,
        ladder=_ladder("matched", "exact"),
        context=_context(),
    ) == "syndicated"


def test_title_match_uses_the_submitted_headline() -> None:
    documents = dedupe([_hit("bbc.co.uk", title="Coastal Defence Plan Announced!")])
    assert classify_existence(
        documents=documents,
        sources=resolve_independence(documents),
        ladder=_ladder("matched", "loose"),
        context=_context(),
    ) == "title_match"


def test_nothing_found_after_a_full_search_is_not_found() -> None:
    assert classify_existence(
        documents=[],
        sources=[],
        ladder=_ladder("exhausted"),
        context=_context(),
        adapter_reports=[_report("newsapi", "empty", queries_run=1)],
    ) == "not_found"


def test_never_looked_is_out_of_range_not_not_found() -> None:
    no_headline = classify_existence(
        documents=[],
        sources=[],
        ladder=_ladder("not_planned"),
        context=_context(headline=None),
        adapter_reports=[_report("newsapi", "empty", queries_run=1)],
    )
    all_skipped = classify_existence(
        documents=[],
        sources=[],
        ladder=_ladder("exhausted"),
        context=_context(),
        adapter_reports=[
            _report("newsapi", "skipped_out_of_range", reason="too old"),
            _report("guardian", "skipped_no_key", reason="no key"),
        ],
    )
    # Both mean "we could not look", which is a different statement from
    # "we looked and found nothing".
    assert no_headline == "out_of_range"
    assert all_skipped == "out_of_range"


def test_empty_hit_list_yields_a_valid_payload() -> None:
    payload = build_payload(
        hits=[],
        ladder=_ladder("exhausted"),
        context=_context(),
        coverage=CoverageReport(
            adapters=[_report("newsapi", "empty", queries_run=1)],
            existence_search="exhausted",
        ),
    )

    assert payload.documents == []
    assert payload.independent_sources == []
    assert payload.document_count == 0
    assert payload.independent_source_count == 0
    assert payload.existence_class == "not_found"
    assert payload.title_match_strength == "none"
    # Still round-trips, so an empty run is a real result rather than a hole.
    from app.schemas.retrieval import RetrievalPayload

    assert RetrievalPayload.model_validate(payload.model_dump(mode="json")) == payload


@pytest.mark.parametrize(
    "hits",
    [
        [],
        [_hit("bbc.co.uk")],
        [_hit(f"outlet{i}.test", wire="Reuters", path=f"/{i}") for i in range(20)],
        [_hit("smh.com.au", path="/a"), _hit("theage.com.au", path="/b",
                                             snippet=OTHER_BODY, title="Rail")],
    ],
)
def test_counts_always_equal_the_lengths_of_their_lists(hits) -> None:
    payload = build_payload(
        hits=hits,
        ladder=_ladder(),
        context=_context(),
        coverage=CoverageReport(),
    )
    # A count that drifts from its list is the one way this layer could quietly
    # misreport corroboration, so both are derived rather than passed in.
    assert payload.document_count == len(payload.documents)
    assert payload.independent_source_count == len(payload.independent_sources)
    assert payload.independent_source_count <= payload.document_count


def test_counts_cannot_be_overridden_by_a_caller() -> None:
    from app.schemas.retrieval import RetrievalPayload

    payload = RetrievalPayload(
        documents=[_hit("bbc.co.uk"), _hit("nytimes.com", path="/b")],
        document_count=99,
        independent_source_count=99,
    )
    assert payload.document_count == 2
    assert payload.independent_source_count == 0


def test_payload_carries_ranking_provenance() -> None:
    payload = build_payload(
        hits=[_hit("bbc.co.uk")],
        ladder=_ladder(),
        context=_context(),
        coverage=CoverageReport(),
        ranking_method="char-ngram",
        ranking_engine_name="char-ngram-cosine",
    )
    assert payload.ranking_method == "char-ngram"
    assert payload.ranking_engine_name == "char-ngram-cosine"


def test_empty_canonical_url_still_groups_and_joins_layer4() -> None:
    """Layer 3 and Layer 4 must share grouping_url or the join silently page-counts."""
    from app.layers.evidence import join_independent_sources
    from app.schemas.envelope import RunEnvelope
    from app.schemas.retrieval import RetrievalPayload
    from app.scoring.urls import grouping_url

    hits = [
        _hit(
            "smh.com.au",
            path="/a?utm_source=share",
            canonical="",
            snippet=WIRE_BODY,
        ),
        _hit(
            "theage.com.au",
            path="/b?utm_source=share",
            canonical="",
            snippet=WIRE_BODY,
            wire="Reuters",
        ),
    ]
    documents = dedupe(hits)
    sources = resolve_independence(documents)
    assert sources
    grouped = {url for source in sources for url in source.member_urls}
    for hit in documents:
        assert grouping_url(hit) in grouped

    envelope = RunEnvelope(run_id="join-empty-canonical")
    envelope.retrieval = RetrievalPayload(
        documents=documents,
        independent_sources=sources,
        independent_source_count=len(sources),
        document_count=len(documents),
    )
    groups, misses = join_independent_sources(envelope)
    assert misses == 0
    assert len(groups) == len(documents)
