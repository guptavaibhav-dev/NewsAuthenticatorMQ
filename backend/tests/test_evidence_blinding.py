"""Engine B's user payload is the blinding boundary. The system prompt is not."""

from __future__ import annotations

from app.layers.evidence import blinded_analyst_payload
from app.schemas.envelope import Claim, ClassificationPayload, RunEnvelope
from app.schemas.retrieval import IndependentSource, RetrievalPayload, SearchHit

# Keys that would let Engine B see Engine A or Layer 3's judgements.
# Adding any of these to evidence_rows() or the claims blob must fail this test.
# wire_credit is here because it is Layer 3's syndication judgement; its
# absence from this list is what previously let that leak go unnoticed.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "nli_label",
        "nli_score",
        "nli_probs",
        "existence_class",
        "title_match_strength",
        "relevance_score",
        "merge_reason",
        "merge_evidence",
        "wire_credit",
        "overall_state",
        "corroboration",
        "corroboration_state",
        "independent_source_count",
        "source_groups",
    }
)

ALLOWED_CLAIM_KEYS = frozenset({"claim_id", "text"})
ALLOWED_EVIDENCE_KEYS = frozenset(
    {"source_id", "outlet", "date", "url", "title", "snippet"}
)


def _hit(**overrides) -> SearchHit:
    row = dict(
        url="https://smh.example/wire-story",
        canonical_url="https://smh.example/wire-story",
        title="Coastal defence plan announced",
        snippet="Ministers announced a coastal defence programme on Tuesday.",
        body_hash="sha256:abc",
        published_at="2026-09-12T08:30:00Z",
        publisher_domain="smh.example",
        publisher_id="smh.example",
        byline="A Reporter",
        wire_credit="Reuters",
        source_adapter="newsapi",
        query_id="q1",
        claim_id="c1",
        language="en",
        relevance_score=0.91,
    )
    row.update(overrides)
    return SearchHit(**row)


def _envelope() -> RunEnvelope:
    hit = _hit()
    return RunEnvelope(
        run_id="blinding",
        classification=ClassificationPayload(
            claims=[
                Claim(id="c1", text="Ministers announced a coastal defence programme.", checkworthy=True),
                Claim(id="c2", text="This is a colourful metaphor, not a checkworthy claim.", checkworthy=False),
            ]
        ),
        retrieval=RetrievalPayload(
            documents=[hit],
            independent_sources=[
                IndependentSource(
                    source_id="src-wire",
                    representative_url=hit.url,
                    member_urls=[hit.canonical_url],
                    publisher_ids=["smh.example"],
                    merge_reason="same_wire",
                    merge_evidence="Reuters credit on the page.",
                )
            ],
            existence_class="syndicated",
            title_match_strength="loose",
        ),
    )


def _keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_keys(item))
    return found


def test_engine_b_payload_contains_no_leaky_fields() -> None:
    payload = blinded_analyst_payload(_envelope())
    leaked = _keys(payload) & FORBIDDEN_PAYLOAD_KEYS
    assert leaked == set(), f"Engine B payload leaked {sorted(leaked)}"


def test_engine_b_evidence_rows_are_an_allowlist() -> None:
    payload = blinded_analyst_payload(_envelope())
    assert payload["evidence"], "fixture produced no evidence rows"
    for row in payload["evidence"]:
        extra = set(row) - ALLOWED_EVIDENCE_KEYS
        missing = ALLOWED_EVIDENCE_KEYS - set(row)
        assert extra == set(), f"leaky evidence field(s): {sorted(extra)}"
        assert missing == set(), f"evidence row missing {sorted(missing)}"


def test_engine_b_claims_are_id_and_text_only() -> None:
    payload = blinded_analyst_payload(_envelope())
    for row in payload["claims"]:
        assert set(row) == ALLOWED_CLAIM_KEYS


def test_engine_b_receives_every_claim_including_non_checkworthy() -> None:
    payload = blinded_analyst_payload(_envelope())
    assert [row["claim_id"] for row in payload["claims"]] == ["c1", "c2"]


def test_blinding_is_enforced_by_the_payload_not_the_system_prompt() -> None:
    # GEMINI_SYSTEM is not consulted. A prompt that says "you are blinded"
    # cannot catch a leaky field in evidence_rows(); walking the payload can.
    payload = blinded_analyst_payload(_envelope())
    dumped = str(payload)
    assert "wire_credit" not in _keys(payload)
    assert "nli_label" not in dumped
    assert "existence_class" not in dumped
    assert "merge_reason" not in dumped
    assert "relevance_score" not in dumped
    assert "title_match_strength" not in dumped
    assert "Reuters" not in dumped
