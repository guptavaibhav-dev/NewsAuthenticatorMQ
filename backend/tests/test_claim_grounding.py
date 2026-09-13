from __future__ import annotations

import pytest

from app.layers.grounding import locate_quote, normalise, segment_source_for_span
from app.layers.preprocess import _claims_from_llm, heuristic_claims
from app.schemas.envelope import Claim, InputPayload, TextSegment

ARTICLE = (
    "Ministers announced a new coastal defence plan on Tuesday morning. "
    "The minister called it a \"coastal defence plan-urgent\" and said work "
    "would start in March. Treasury has not confirmed the three-year funding "
    "figure quoted by the department."
)


def _payload(text: str = ARTICLE, segments: list[TextSegment] | None = None) -> InputPayload:
    if segments is None:
        segments = [TextSegment(source="fetched", start=0, end=len(text))]
    return InputPayload(raw_text=text, segments=segments)


def _llm(claims: list[dict]) -> dict:
    return {"claims": claims}


def assert_span_matches_quote(claim: Claim, raw_text: str) -> None:
    """raw_text[span_start:span_end] must be the passage we located."""
    if claim.grounding == "not_found":
        assert claim.span_start is None and claim.span_end is None
        return
    assert claim.span_start is not None and claim.span_end is not None
    assert 0 <= claim.span_start < claim.span_end <= len(raw_text)
    located = raw_text[claim.span_start : claim.span_end]
    assert located
    if claim.grounding == "exact":
        assert located == (claim.source_quote or "").strip()
    else:
        assert normalise(located).strip() == normalise(claim.source_quote or "").strip()


def test_verbatim_quote_is_exact_with_correct_offsets() -> None:
    quote = "work would start in March"
    payload = _payload()
    claims = _claims_from_llm(
        _llm([{"id": "c1", "text": "Work starts in March.", "source_quote": quote, "label": "fact"}]),
        payload,
    )
    claim = claims[0]
    assert claim.grounding == "exact"
    assert claim.span_start == ARTICLE.index(quote)
    assert claim.span_end == ARTICLE.index(quote) + len(quote)
    assert ARTICLE[claim.span_start : claim.span_end] == quote
    assert_span_matches_quote(claim, ARTICLE)


def test_curly_quotes_against_ascii_article_are_normalised() -> None:
    # The model re-typed the passage with smart quotes and an em dash.
    quote = "a \u201ccoastal defence plan\u2014urgent\u201d"
    payload = _payload()
    claims = _claims_from_llm(
        _llm([{"id": "c1", "text": "The minister used that phrase.", "source_quote": quote, "label": "fact"}]),
        payload,
    )
    claim = claims[0]
    assert claim.grounding == "normalised"
    located = ARTICLE[claim.span_start : claim.span_end]
    assert located == 'a "coastal defence plan-urgent"'
    assert_span_matches_quote(claim, ARTICLE)


def test_collapsed_whitespace_is_normalised_not_exact() -> None:
    text = "Ministers  announced\na new  plan on Tuesday morning and said nothing else."
    payload = _payload(text)
    quote = "Ministers announced a new plan on Tuesday morning"
    claims = _claims_from_llm(
        _llm([{"id": "c1", "text": "A plan was announced.", "source_quote": quote, "label": "fact"}]),
        payload,
    )
    claim = claims[0]
    assert claim.grounding == "normalised"
    assert text[claim.span_start : claim.span_end] == "Ministers  announced\na new  plan on Tuesday morning"
    assert_span_matches_quote(claim, text)


def test_absent_quote_is_not_found_and_still_present() -> None:
    payload = _payload()
    claims = _claims_from_llm(
        _llm(
            [
                {"id": "c1", "text": "Work starts in March.", "source_quote": "work would start in March", "label": "fact"},
                {"id": "c2", "text": "The bridge collapsed.", "source_quote": "the bridge collapsed overnight", "label": "fact"},
            ]
        ),
        payload,
    )
    assert [c.id for c in claims] == ["c1", "c2"]
    fabricated = claims[1]
    assert fabricated.grounding == "not_found"
    assert fabricated.span_start is None
    assert fabricated.span_end is None
    assert fabricated.source_quote == "the bridge collapsed overnight"
    assert_span_matches_quote(fabricated, ARTICLE)


def test_missing_quote_is_not_found_never_guessed() -> None:
    payload = _payload()
    claims = _claims_from_llm(
        _llm([{"id": "c1", "text": "Something happened.", "label": "unclear"}]),
        payload,
    )
    assert claims[0].grounding == "not_found"
    assert claims[0].source_quote is None
    assert claims[0].kind == "unclear"


def test_near_miss_is_a_failure_not_a_fuzzy_match() -> None:
    payload = _payload()
    # One wrong word: must not match.
    start, end, grounding = locate_quote(ARTICLE, "work would start in April")
    assert (start, end, grounding) == (None, None, "not_found")
    # Ellipsis stitching must not match either.
    start, end, grounding = locate_quote(ARTICLE, "Ministers announced ... in March")
    assert grounding == "not_found"
    assert payload.raw_text == ARTICLE


def test_label_maps_to_kind_and_unknown_labels_fall_back() -> None:
    payload = _payload()
    claims = _claims_from_llm(
        _llm(
            [
                {"id": "c1", "text": "A.", "source_quote": "work would start in March", "label": "opinion"},
                {"id": "c2", "text": "B.", "source_quote": "work would start in March", "label": "wild-guess"},
            ]
        ),
        payload,
    )
    assert claims[0].kind == "opinion"
    assert claims[1].kind == "unspecified"


def test_claim_source_tracks_layer_1_segments() -> None:
    pasted = "Journalist note: confirm the figure."
    fetched = "Treasury has not confirmed the three-year funding figure."
    raw = f"{pasted}\n\n{fetched}"
    split = len(pasted) + 2
    payload = _payload(
        raw,
        [
            TextSegment(source="pasted", start=0, end=split),
            TextSegment(source="fetched", start=split, end=len(raw)),
        ],
    )
    claims = _claims_from_llm(
        _llm(
            [
                {"id": "c1", "text": "A note.", "source_quote": "confirm the figure", "label": "unclear"},
                {"id": "c2", "text": "Not confirmed.", "source_quote": "Treasury has not confirmed", "label": "fact"},
                {"id": "c3", "text": "Both.", "source_quote": "the figure.\n\nTreasury", "label": "unclear"},
            ]
        ),
        payload,
    )
    assert claims[0].claim_source == "pasted"
    assert claims[1].claim_source == "fetched"
    assert claims[2].claim_source == "spans_both"
    for claim in claims:
        assert_span_matches_quote(claim, raw)


def test_claim_source_is_none_without_segments() -> None:
    payload = InputPayload(raw_text=ARTICLE)
    claims = _claims_from_llm(
        _llm([{"id": "c1", "text": "A.", "source_quote": "work would start in March", "label": "fact"}]),
        payload,
    )
    assert claims[0].grounding == "exact"
    assert claims[0].claim_source is None
    assert segment_source_for_span([], 0, 5) is None


def test_ungrounded_claims_are_never_dropped() -> None:
    payload = _payload()
    rows = [
        {"id": f"c{i}", "text": f"Claim {i}.", "source_quote": f"invented passage {i}", "label": "fact"}
        for i in range(1, 4)
    ]
    claims = _claims_from_llm(_llm(rows), payload)
    assert len(claims) == 3
    assert all(c.grounding == "not_found" for c in claims)


def test_heuristic_fallback_claims_are_grounded_exactly() -> None:
    claims = heuristic_claims(ARTICLE)
    assert claims
    for claim in claims:
        assert claim.grounding == "exact"
        assert ARTICLE[claim.span_start : claim.span_end] == claim.source_quote
        assert_span_matches_quote(claim, ARTICLE)


@pytest.mark.parametrize(
    "quote",
    [
        "Ministers announced a new coastal defence plan on Tuesday morning.",
        "coastal defence plan-urgent",
        "Treasury has not confirmed the three-year funding figure",
    ],
)
def test_grounded_spans_round_trip(quote: str) -> None:
    start, end, grounding = locate_quote(ARTICLE, quote)
    assert grounding == "exact"
    assert ARTICLE[start:end] == quote
