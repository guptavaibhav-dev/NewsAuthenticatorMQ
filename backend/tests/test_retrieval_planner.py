from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.retrieval.planner import (
    PLANNER_SYSTEM,
    PLANNER_TEMPLATE_VERSION,
    accept_rewrite,
    build_queries,
    score_claim,
    select_claims,
    stopwords,
)
from app.schemas.envelope import Claim, ClassificationPayload, DateWindow, Entity, InputPayload

ARTICLE = (
    "Ministers announced a new coastal defence plan on Tuesday morning. "
    "The department said work would start in March and run for three years. "
    "Treasury has not confirmed the funding figure quoted by the department."
)

ENTITIES = [
    Entity(text="Treasury", type="ORG", source="both"),
    Entity(text="March", type="DATE", source="ner"),
    Entity(text="Rachel Vance", type="PERSON", source="llm"),
    Entity(text="Cornwall", type="GPE", source="both"),
]


def _claim(
    cid: str,
    text: str,
    *,
    kind: str = "fact",
    grounding: str = "exact",
    agreement: str = "both",
    checkworthy: bool = True,
    span: tuple[int, int] | None = (0, 10),
) -> Claim:
    return Claim(
        id=cid,
        text=text,
        kind=kind,  # type: ignore[arg-type]
        grounding=grounding,  # type: ignore[arg-type]
        agreement=agreement,  # type: ignore[arg-type]
        checkworthy=checkworthy,
        source_quote=text,
        span_start=None if span is None else span[0],
        span_end=None if span is None else span[1],
    )


def _classification(
    claims: list[Claim],
    *,
    headline: str | None = "Ministers announce coastal defence plan for Cornwall",
    confidence: str = "weak",
    start: str | None = "2026-09-01",
    end: str | None = "2026-09-13",
    entities: list[Entity] | None = None,
) -> ClassificationPayload:
    return ClassificationPayload(
        headline=headline,
        claims=claims,
        entities=ENTITIES if entities is None else entities,
        date_window=DateWindow(start=start, end=end, confidence=confidence),  # type: ignore[arg-type]
    )


def _input() -> InputPayload:
    return InputPayload(raw_text=ARTICLE)


# --- scoring -----------------------------------------------------------------


def test_template_version_is_pinned() -> None:
    assert PLANNER_TEMPLATE_VERSION == "l3-v1"


def test_stopwords_are_bundled_and_lowercase() -> None:
    words = stopwords()
    assert "the" in words and "would" in words
    assert "treasury" not in words
    assert all(word == word.lower() for word in words)


def test_opinion_claims_rank_below_factual_ones() -> None:
    fact = _claim("c1", "Treasury confirmed 3 million pounds in March.", kind="fact")
    opinion = _claim("c2", "Treasury confirmed 3 million pounds in March.", kind="opinion")
    fact_score, _ = score_claim(fact, ENTITIES)
    opinion_score, _ = score_claim(opinion, ENTITIES)
    assert opinion_score < fact_score
    assert fact_score - opinion_score == 4.0


def test_entity_and_number_terms_are_additive() -> None:
    bare = _claim("c1", "Something happened somewhere.", kind="unspecified")
    entity_only = _claim("c2", "Treasury reacted.", kind="unspecified")
    both = _claim("c3", "Treasury paid 3 million.", kind="unspecified")
    baseline = 3.0  # grounding exact + agreement both + checkworthy
    assert score_claim(bare, ENTITIES)[0] == baseline
    assert score_claim(entity_only, ENTITIES)[0] == baseline + 2.0
    assert score_claim(both, ENTITIES)[0] == baseline + 4.0


def test_kind_is_read_not_label() -> None:
    # .label does not exist on Claim; a planner reading it would silently score 0.
    claim = _claim("c1", "Plain sentence.", kind="fact")
    assert not hasattr(claim, "label")
    score, missing = score_claim(claim, ENTITIES)
    assert "kind" not in missing
    assert score > 0


def test_loose_dates_count_as_numeric() -> None:
    for text in ("Work starts in March.", "It happened on Tuesday.", "2026-09-13 was the day."):
        claim = _claim("c1", text, kind="unspecified")
        assert score_claim(claim, [])[0] >= 4.0, text


def test_ungrounded_claim_scores_without_raising() -> None:
    claim = _claim(
        "c1",
        "The bridge collapsed overnight.",
        grounding="not_found",
        span=None,
    )
    assert claim.span_start is None and claim.span_end is None
    score, missing = score_claim(claim, ENTITIES)
    assert isinstance(score, float)
    assert missing == []
    selected, skipped, _ = select_claims([claim], 3, entities=ENTITIES)
    assert len(selected) + len(skipped) == 1


def test_missing_optional_attribute_populates_fields_missing() -> None:
    partial = SimpleNamespace(id="c1", text="Treasury paid 3 million in March.")
    score, missing = score_claim(partial, ENTITIES)
    assert sorted(missing) == ["agreement", "checkworthy", "grounding", "kind"]
    assert score == 4.0  # entity + number only
    selected, skipped, fields_missing = select_claims([partial], 1, entities=ENTITIES)
    assert selected == [partial] and skipped == []
    assert fields_missing == ["agreement", "checkworthy", "grounding", "kind"]


def test_score_claim_never_raises_on_junk() -> None:
    for junk in (SimpleNamespace(), SimpleNamespace(text=None), SimpleNamespace(text=42)):
        score, missing = score_claim(junk, ENTITIES)
        assert isinstance(score, float)
        assert "text" in missing


# --- selection ---------------------------------------------------------------


def test_selected_and_skipped_partition_the_input() -> None:
    claims = [
        _claim("c1", "Treasury paid 3 million in March."),
        _claim("c2", "It is a disgrace.", kind="opinion", grounding="not_found", span=None),
        _claim("c3", "Cornwall councils were told a fortnight earlier."),
        _claim("c4", "Rachel Vance signed the order on Tuesday.", agreement="pass_a_only"),
        _claim("c5", "Nothing much.", kind="unspecified", checkworthy=False),
    ]
    selected, skipped, _ = select_claims(claims, 3, entities=ENTITIES)

    assert len(selected) == 3
    ids = [c.id for c in selected] + [c.id for c in skipped]
    assert sorted(ids) == ["c1", "c2", "c3", "c4", "c5"]
    assert len(ids) == len(set(ids))
    assert len(selected) + len(skipped) == len(claims)


def test_negative_scores_are_never_selected_even_with_budget_left() -> None:
    opinion = _claim(
        "c1",
        "Frankly a shambles.",
        kind="opinion",
        grounding="not_found",
        agreement="pass_b_only",
        checkworthy=False,
        span=None,
    )
    assert score_claim(opinion, ENTITIES)[0] < 0
    selected, skipped, _ = select_claims([opinion], 10, entities=ENTITIES)
    assert selected == []
    assert skipped == [opinion]


def test_k_larger_than_claim_count_does_not_crash() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    selected, skipped, _ = select_claims(claims, 99, entities=ENTITIES)
    assert selected == claims
    assert skipped == []


def test_empty_and_zero_budget_are_safe() -> None:
    assert select_claims([], 5) == ([], [], [])
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    selected, skipped, _ = select_claims(claims, 0, entities=ENTITIES)
    assert selected == [] and skipped == claims


def test_ties_break_on_claim_id_naturally() -> None:
    # Identical scores, so only the id ordering decides. c2 must precede c10.
    claims = [
        _claim("c10", "Treasury paid 3 million in March."),
        _claim("c2", "Treasury paid 3 million in March."),
    ]
    selected, _skipped, _ = select_claims(claims, 2, entities=ENTITIES)
    assert [c.id for c in selected] == ["c2", "c10"]


# --- query building ----------------------------------------------------------


def test_existence_ladder_has_three_rungs() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(_classification(claims), _input(), claims)
    ladder = [q for q in queries if q.kind == "existence"]

    assert [q.query_id for q in ladder] == ["q_exist_1", "q_exist_2", "q_exist_3"]
    assert [q.template_id for q in ladder] == ["exist_exact", "exist_loose", "exist_keyword"]
    assert [q.attempt for q in ladder] == [1, 2, 3]
    assert ladder[0].query_text.startswith('"') and ladder[0].query_text.endswith('"')
    assert ladder[1].query_text == "Ministers announce coastal defence plan for Cornwall"
    assert "for" not in ladder[2].query_text.split()
    assert len(ladder[2].query_text.split()) <= 6


def test_headline_none_produces_zero_existence_queries() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(_classification(claims, headline=None), _input(), claims)
    assert [q for q in queries if q.kind == "existence"] == []
    # The body text must not be mined for a substitute headline.
    assert all(ARTICLE[:40] not in q.query_text for q in queries)
    assert queries, "claim and entity queries should still be built"


def test_blank_headline_is_treated_as_absent() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(_classification(claims, headline="   "), _input(), claims)
    assert [q for q in queries if q.kind == "existence"] == []


def test_claim_and_factcheck_queries_are_built_per_selected_claim() -> None:
    claims = [
        _claim("c1", "Treasury confirmed 3 million pounds for Cornwall in March."),
        _claim("c3", "Rachel Vance signed the order."),
    ]
    queries = build_queries(_classification(claims), _input(), claims)

    by_id = {q.query_id: q for q in queries}
    assert by_id["q_claim_c1"].template_id == "claim_event"
    assert by_id["q_claim_c1"].kind == "claim"
    assert by_id["q_claim_c1"].claim_id == "c1"
    assert "Treasury" in by_id["q_claim_c1"].query_text
    assert "3" in by_id["q_claim_c1"].query_text

    assert by_id["q_fc_c3"].template_id == "factcheck"
    assert by_id["q_fc_c3"].kind == "factcheck"
    assert by_id["q_fc_c3"].query_text == "Rachel Vance signed the order."


def test_factcheck_query_is_truncated_to_200_chars() -> None:
    long_claim = _claim("c1", "Treasury " + "x" * 400)
    queries = build_queries(_classification([long_claim]), _input(), [long_claim])
    factcheck = next(q for q in queries if q.template_id == "factcheck")
    assert len(factcheck.query_text) <= 200


def test_entity_queries_cover_person_org_gpe_only() -> None:
    queries = build_queries(_classification([]), _input(), [])
    entity_queries = [q for q in queries if q.kind == "entity"]

    assert [q.query_id for q in entity_queries] == ["q_entity_0", "q_entity_1", "q_entity_2"]
    assert [q.query_text for q in entity_queries] == ["Treasury", "Rachel Vance", "Cornwall"]
    assert all(q.template_id == "entity_lookup" for q in entity_queries)
    # DATE entities are not looked up.
    assert "March" not in [q.query_text for q in entity_queries]


def test_duplicate_entities_are_looked_up_once() -> None:
    entities = [
        Entity(text="Treasury", type="ORG", source="llm"),
        Entity(text="treasury", type="ORG", source="ner"),
    ]
    queries = build_queries(_classification([], entities=entities), _input(), [])
    assert len([q for q in queries if q.kind == "entity"]) == 1


def test_all_query_ids_are_unique() -> None:
    claims = [
        _claim("c1", "Treasury paid 3 million in March."),
        _claim("c2", "Cornwall councils were told on Tuesday."),
        _claim("c3", "Rachel Vance signed the order."),
    ]
    queries = build_queries(_classification(claims), _input(), claims)
    ids = [q.query_id for q in queries]
    assert len(ids) == len(set(ids))
    assert len(ids) > 5


def test_duplicate_claim_ids_still_yield_unique_query_ids() -> None:
    claims = [_claim("c1", "Treasury paid 3 million."), _claim("c1", "Cornwall was told.")]
    queries = build_queries(_classification(claims), _input(), claims)
    ids = [q.query_id for q in queries]
    assert len(ids) == len(set(ids))


# --- date windows ------------------------------------------------------------


def test_weak_confidence_leaves_both_bounds_none() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(
        _classification(claims, confidence="weak", start="2026-09-01", end="2026-09-13"),
        _input(),
        claims,
    )
    assert queries
    assert all(q.date_from is None for q in queries)
    assert all(q.date_to is None for q in queries)


def test_none_confidence_leaves_both_bounds_none() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(
        _classification(claims, confidence="none", start="2026-09-01", end="2026-09-13"),
        _input(),
        claims,
    )
    assert all(q.date_from is None and q.date_to is None for q in queries)


def test_high_confidence_with_start_none_leaves_date_from_none() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(
        _classification(claims, confidence="high", start=None, end="2026-09-13"),
        _input(),
        claims,
    )
    dated = [q for q in queries if q.kind in {"existence", "claim"}]
    assert dated
    assert all(q.date_from is None for q in dated)
    assert all(q.date_to == "2026-09-13" for q in dated)


def test_high_confidence_with_both_bounds_applies_them() -> None:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    queries = build_queries(
        _classification(claims, confidence="high", start="2026-09-01", end="2026-09-13"),
        _input(),
        claims,
    )
    existence = next(q for q in queries if q.kind == "existence")
    assert (existence.date_from, existence.date_to) == ("2026-09-01", "2026-09-13")
    # Fact-check and entity lookups are not time-bounded.
    factcheck = next(q for q in queries if q.kind == "factcheck")
    assert factcheck.date_from is None and factcheck.date_to is None


# --- determinism -------------------------------------------------------------


def test_identical_input_produces_identical_query_lists() -> None:
    claims = [
        _claim("c1", "Treasury paid 3 million in March."),
        _claim("c2", "Cornwall councils were told on Tuesday."),
        _claim("c3", "Rachel Vance signed the order."),
    ]
    classification = _classification(claims, confidence="high")

    first = build_queries(classification, _input(), claims)
    second = build_queries(classification, _input(), claims)

    assert [q.model_dump() for q in first] == [q.model_dump() for q in second]
    assert first is not second


def test_selection_is_deterministic_across_calls() -> None:
    claims = [
        _claim("c1", "Treasury paid 3 million in March."),
        _claim("c2", "Cornwall was told on Tuesday."),
        _claim("c3", "Rachel Vance signed the order."),
        _claim("c4", "A view was expressed.", kind="opinion"),
    ]
    first = select_claims(claims, 2, entities=ENTITIES)
    second = select_claims(claims, 2, entities=ENTITIES)
    assert [c.id for c in first[0]] == [c.id for c in second[0]]
    assert [c.id for c in first[1]] == [c.id for c in second[1]]
    assert first[2] == second[2]


# --- LLM rephrase gate -------------------------------------------------------


def _plan() -> list:
    claims = [_claim("c1", "Treasury paid 3 million in March.")]
    return build_queries(_classification(claims), _input(), claims)


def test_planner_llm_is_off_by_default() -> None:
    assert Settings().planner_use_llm is False


def test_system_prompt_marks_claim_text_as_untrusted_data() -> None:
    assert "<CLAIM></CLAIM>" in PLANNER_SYSTEM
    assert "UNTRUSTED DATA" in PLANNER_SYSTEM
    assert "never instructions" in PLANNER_SYSTEM.lower()


def test_rewrite_accepted_when_only_query_text_changes() -> None:
    plan = _plan()
    returned = [
        {
            "query_id": q.query_id,
            "template_id": q.template_id,
            "claim_id": q.claim_id,
            "query_text": f"{q.query_text} extra",
        }
        for q in plan
    ]
    accepted = accept_rewrite(plan, returned)
    assert accepted is not None
    assert [q.query_text for q in accepted] == [f"{q.query_text} extra" for q in plan]
    # Everything else is untouched.
    assert [(q.query_id, q.template_id, q.claim_id, q.attempt) for q in accepted] == [
        (q.query_id, q.template_id, q.claim_id, q.attempt) for q in plan
    ]


def test_rewrite_rejected_when_a_query_is_dropped() -> None:
    plan = _plan()
    returned = [
        {"query_id": q.query_id, "template_id": q.template_id, "claim_id": q.claim_id, "query_text": "x"}
        for q in plan
    ][:-1]
    assert accept_rewrite(plan, returned) is None


def test_rewrite_rejected_when_queries_are_reordered() -> None:
    plan = _plan()
    returned = list(
        reversed(
            [
                {
                    "query_id": q.query_id,
                    "template_id": q.template_id,
                    "claim_id": q.claim_id,
                    "query_text": "x",
                }
                for q in plan
            ]
        )
    )
    assert accept_rewrite(plan, returned) is None


def test_rewrite_rejected_when_template_or_claim_id_changes() -> None:
    plan = _plan()
    base = [
        {"query_id": q.query_id, "template_id": q.template_id, "claim_id": q.claim_id, "query_text": "x"}
        for q in plan
    ]

    tampered = [dict(row) for row in base]
    tampered[0]["template_id"] = "exist_invented"
    assert accept_rewrite(plan, tampered) is None

    tampered = [dict(row) for row in base]
    tampered[0]["claim_id"] = "c99"
    assert accept_rewrite(plan, tampered) is None

    tampered = [dict(row) for row in base]
    tampered[0]["query_id"] = "q_exist_9"
    assert accept_rewrite(plan, tampered) is None


def test_rewrite_rejected_when_a_query_is_added() -> None:
    plan = _plan()
    returned = [
        {"query_id": q.query_id, "template_id": q.template_id, "claim_id": q.claim_id, "query_text": "x"}
        for q in plan
    ]
    returned.append(
        {"query_id": "q_extra", "template_id": "exist_exact", "claim_id": None, "query_text": "x"}
    )
    assert accept_rewrite(plan, returned) is None


@pytest.mark.parametrize("bad_text", ["", "   ", None, 42, ["list"]])
def test_rewrite_rejected_on_unusable_query_text(bad_text: object) -> None:
    plan = _plan()
    returned = [
        {"query_id": q.query_id, "template_id": q.template_id, "claim_id": q.claim_id, "query_text": "fine"}
        for q in plan
    ]
    returned[0]["query_text"] = bad_text
    assert accept_rewrite(plan, returned) is None


@pytest.mark.parametrize("junk", [None, {}, "queries", [1, 2, 3], [None]])
def test_rewrite_rejected_on_malformed_payload(junk: object) -> None:
    assert accept_rewrite(_plan(), junk) is None


def test_original_plan_is_never_mutated_by_a_rewrite() -> None:
    plan = _plan()
    before = [q.model_dump() for q in plan]
    returned = [
        {"query_id": q.query_id, "template_id": q.template_id, "claim_id": q.claim_id, "query_text": "rewritten"}
        for q in plan
    ]
    accept_rewrite(plan, returned)
    assert [q.model_dump() for q in plan] == before
