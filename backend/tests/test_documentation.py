"""Direct tests for Layer 7 source assessment.

`_source_assessment` used to crash on `IndependentSource.publisher_id`, a field
that does not exist. Coverage through a full pipeline run hid that until the
first real retrieval payload arrived. These tests call the function itself.
"""

from __future__ import annotations

from app.layers.documentation import _source_assessment
from app.schemas.envelope import RunEnvelope
from app.schemas.retrieval import IndependentSource, RetrievalPayload


def _envelope_with(*sources: IndependentSource, existence: str = "title_match") -> RunEnvelope:
    envelope = RunEnvelope(run_id="source-assessment")
    envelope.retrieval = RetrievalPayload(
        independent_sources=list(sources),
        existence_class=existence,  # type: ignore[arg-type]
    )
    return envelope


def test_source_assessment_uses_publisher_ids_and_counts_newsrooms() -> None:
    envelope = _envelope_with(
        IndependentSource(
            source_id="src1",
            representative_url="https://www.smh.com.au/story",
            member_urls=[
                "https://www.smh.com.au/story",
                "https://www.theage.com.au/story",
            ],
            publisher_ids=["nine_au"],
            merge_reason="same_owner",
            merge_evidence="smh.com.au and theage.com.au share an owner",
        )
    )

    text = _source_assessment(envelope)

    assert "nine_au" in text
    assert "2 pages merged as same_owner" in text
    assert "1 independent source(s) behind 0 retrieved page(s)" in text


def test_source_assessment_out_of_range_is_a_gap_not_a_finding() -> None:
    envelope = _envelope_with(existence="out_of_range")
    text = _source_assessment(envelope)
    assert "gap in our reach" in text
    assert "falsity" not in text


def test_source_assessment_when_layer_three_has_not_run() -> None:
    envelope = RunEnvelope(run_id="no-l3")
    assert envelope.retrieval is None
    assert _source_assessment(envelope) == (
        "Layer 3 has not run, so there is no source assessment yet."
    )
