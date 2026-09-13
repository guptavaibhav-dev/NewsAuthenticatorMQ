from __future__ import annotations

import asyncio

from app.config import Settings
from app.layers.claim_agreement import (
    OVERLAP_THRESHOLD,
    agreement_rate,
    overlap_ratio,
    reconcile_passes,
)
from app.layers.preprocess import (
    PREPROCESS_SYSTEM,
    PREPROCESS_SYSTEM_B,
    ground_claims,
    run_preprocess,
)
from app.schemas.envelope import Claim, InputPayload, RunEnvelope, TextSegment

ARTICLE = (
    "Ministers announced a new coastal defence plan on Tuesday morning. "
    "The department said work would start in March and run for three years. "
    "Treasury has not confirmed the funding figure quoted by the department. "
    "Local councils were told about the plan a fortnight earlier."
)


def _payload(text: str = ARTICLE) -> InputPayload:
    return InputPayload(
        raw_text=text,
        segments=[TextSegment(source="fetched", start=0, end=len(text))],
    )


def _claim(cid: str, text: str, quote: str, label: str = "fact") -> Claim:
    return Claim(id=cid, text=text, source_quote=quote, kind=label)  # type: ignore[arg-type]


def _grounded(*claims: Claim) -> list[Claim]:
    return ground_claims(list(claims), _payload())


# --- span matching -----------------------------------------------------------


def _span(start: int, end: int, grounding: str = "exact") -> Claim:
    return Claim(
        id="c1",
        text="x",
        span_start=start,
        span_end=end,
        grounding=grounding,  # type: ignore[arg-type]
    )


def test_overlap_is_measured_against_the_shorter_span() -> None:
    # 10 chars inside a 20-char span: half of the shorter span, so it matches.
    assert overlap_ratio(_span(0, 20), _span(10, 20)) == 1.0
    assert overlap_ratio(_span(0, 20), _span(15, 35)) == 0.25
    assert overlap_ratio(_span(0, 20), _span(10, 30)) == OVERLAP_THRESHOLD


def test_adjacent_and_disjoint_spans_never_match() -> None:
    assert overlap_ratio(_span(0, 20), _span(20, 40)) == 0.0
    assert overlap_ratio(_span(0, 20), _span(50, 60)) == 0.0


def test_identical_text_in_different_places_does_not_match() -> None:
    # The safeguard against falling back to string similarity: same wording,
    # different part of the article, so the passes did not agree.
    a = _span(0, 30)
    b = _span(100, 130)
    merged = reconcile_passes([a], [b], model_a="model-a", model_b="model-b")
    assert [c.agreement for c in merged] == ["pass_a_only", "pass_b_only"]


def test_ungrounded_claims_are_single_pass_by_definition() -> None:
    a = Claim(id="c1", text="Same wording.", grounding="not_found")
    b = Claim(id="c1", text="Same wording.", grounding="not_found")
    merged = reconcile_passes([a], [b], model_a="model-a", model_b="model-b")
    assert len(merged) == 2
    assert {c.agreement for c in merged} == {"pass_a_only", "pass_b_only"}
    assert all("cannot be span-matched" in (c.agreement_note or "") for c in merged)


# --- reconciliation ----------------------------------------------------------


def test_both_passes_find_the_same_claim() -> None:
    quote = "work would start in March and run for three years"
    a = _grounded(_claim("c1", "Work starts in March.", quote))
    b = _grounded(_claim("c1", "The project begins in March.", "work would start in March"))
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")

    assert len(merged) == 1
    claim = merged[0]
    assert claim.agreement == "both"
    assert claim.variant_texts == ["Work starts in March.", "The project begins in March."]
    assert "model-a" in (claim.agreement_note or "")
    assert "model-b" in (claim.agreement_note or "")


def test_claim_found_by_one_pass_only_is_kept() -> None:
    shared = "work would start in March"
    a = _grounded(
        _claim("c1", "Work starts in March.", shared),
        _claim("c2", "Councils were told earlier.", "Local councils were told about the plan"),
    )
    b = _grounded(_claim("c1", "The project begins in March.", shared))
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")

    assert len(merged) == 2
    by_agreement = {c.agreement: c for c in merged}
    assert set(by_agreement) == {"both", "pass_a_only"}
    solo = by_agreement["pass_a_only"]
    assert solo.text == "Councils were told earlier."
    assert solo.variant_texts == ["Councils were told earlier."]
    assert "not evidence the claim is wrong" in (solo.agreement_note or "")


def test_pass_b_only_claim_is_kept() -> None:
    a = _grounded(_claim("c1", "Work starts in March.", "work would start in March"))
    b = _grounded(
        _claim("c1", "The project begins in March.", "work would start in March"),
        _claim("c2", "Treasury has not confirmed it.", "Treasury has not confirmed"),
    )
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")
    assert sorted(c.agreement for c in merged) == ["both", "pass_b_only"]


def test_label_disagreement_becomes_unclear_with_no_winner() -> None:
    quote = "Treasury has not confirmed the funding figure"
    a = _grounded(_claim("c1", "Treasury has not confirmed it.", quote, label="fact"))
    b = _grounded(_claim("c1", "Treasury seems unconvinced.", quote, label="opinion"))
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")

    assert len(merged) == 1
    assert merged[0].kind == "unclear"
    assert "disagreed on label" in (merged[0].agreement_note or "")
    assert "fact" in merged[0].agreement_note and "opinion" in merged[0].agreement_note


def test_matching_pass_keeps_the_exactly_grounded_text() -> None:
    # Pass A re-typed the passage with sloppy spacing; pass B copied it verbatim,
    # so B's wording wins even though A is the tie-break default.
    a = _grounded(_claim("c1", "A wording.", "work  would start in  March and run"))
    b = _grounded(_claim("c1", "B wording.", "work would start in March and run for three years"))
    assert a[0].grounding == "normalised"
    assert b[0].grounding == "exact"
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")
    assert merged[0].text == "B wording."
    assert merged[0].variant_texts == ["A wording.", "B wording."]


def test_merged_claims_are_renumbered_in_document_order() -> None:
    a = _grounded(
        _claim("c1", "Councils were told.", "Local councils were told about the plan"),
        _claim("c2", "Ministers announced a plan.", "Ministers announced a new coastal defence plan"),
    )
    b = _grounded(_claim("c1", "A plan was announced.", "Ministers announced a new coastal"))
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")
    assert [c.id for c in merged] == ["c1", "c2"]
    assert merged[0].span_start < merged[1].span_start
    assert merged[0].agreement == "both"


def test_agreement_rate_matches_a_hand_computed_fixture() -> None:
    shared_one = "work would start in March"
    shared_two = "Treasury has not confirmed the funding figure"
    a = _grounded(
        _claim("c1", "Work starts in March.", shared_one),
        _claim("c2", "Treasury has not confirmed it.", shared_two),
        _claim("c3", "Councils were told earlier.", "Local councils were told about the plan"),
    )
    b = _grounded(
        _claim("c1", "The project begins in March.", shared_one),
        _claim("c2", "Treasury did not confirm.", shared_two),
        _claim("c3", "Ministers announced a plan.", "Ministers announced a new coastal defence plan"),
    )
    merged = reconcile_passes(a, b, model_a="model-a", model_b="model-b")

    # 2 agreed + 1 pass-A-only + 1 pass-B-only = 4 claims, 2 of them "both".
    assert len(merged) == 4
    assert sum(1 for c in merged if c.agreement == "both") == 2
    assert agreement_rate(merged) == 0.5


def test_agreement_rate_of_no_claims_is_zero() -> None:
    assert agreement_rate([]) == 0.0


# --- end to end through run_preprocess ---------------------------------------


class FakeLLM:
    """Returns a canned payload per system prompt, so the passes stay distinct."""

    def __init__(self, payload_a: dict, payload_b: dict, *, same_model: bool = False):
        self.payload_a = payload_a
        self.payload_b = payload_b
        self.same_model = same_model
        self.systems: list[str] = []

    def provider_ready(self, provider: str) -> bool:
        return provider in {"openai", "anthropic"}

    async def chat_json_any(self, *, attempts, system, user, temperature=0.1):
        assert temperature == 0.0, "claim extraction must be deterministic"
        self.systems.append(system)
        provider, model = attempts[0]
        if system == PREPROCESS_SYSTEM:
            return self.payload_a, provider, "model-a"
        return self.payload_b, provider, "model-a" if self.same_model else "model-b"


class FakeNer:
    engine_name = "stub"

    async def extract(self, text: str):
        return []


async def _noop_emit(**kwargs) -> None:
    return None


def _settings(**kwargs) -> Settings:
    base = {
        "openai_api_key": "test",
        "anthropic_api_key": "test",
        "gemini_api_key": "",
        "google_api_key": "",
    }
    base.update(kwargs)
    return Settings(**base)


def _run(llm: FakeLLM, settings: Settings):
    envelope = RunEnvelope(run_id="test-run", input=_payload())
    return asyncio.run(
        run_preprocess(envelope, settings=settings, llm=llm, ner=FakeNer(), emit=_noop_emit)
    )


def _rows(*pairs: tuple[str, str]) -> dict:
    return {
        "claims": [
            {"id": f"c{i}", "text": text, "source_quote": quote, "label": "fact"}
            for i, (text, quote) in enumerate(pairs, start=1)
        ]
    }


def test_two_passes_run_concurrently_with_different_prompts() -> None:
    llm = FakeLLM(
        _rows(("Work starts in March.", "work would start in March")),
        _rows(("The project begins in March.", "work would start in March and run")),
    )
    classification = _run(llm, _settings())

    assert sorted(llm.systems) == sorted([PREPROCESS_SYSTEM, PREPROCESS_SYSTEM_B])
    assert PREPROCESS_SYSTEM != PREPROCESS_SYSTEM_B
    assert classification.pass_a_model == "model-a"
    assert classification.pass_b_model == "model-b"
    assert classification.passes_independent is True
    assert classification.total_claims == 1
    assert classification.claim_agreement_rate == 1.0
    assert classification.claims[0].agreement == "both"


def test_same_model_twice_is_not_independent() -> None:
    llm = FakeLLM(
        _rows(("Work starts in March.", "work would start in March")),
        _rows(("The project begins in March.", "work would start in March and run")),
        same_model=True,
    )
    classification = _run(llm, _settings())
    assert classification.pass_a_model == classification.pass_b_model == "model-a"
    assert classification.passes_independent is False


def test_single_pass_keeps_the_output_shape_and_is_not_independent() -> None:
    rows = _rows(
        ("Work starts in March.", "work would start in March"),
        ("Treasury has not confirmed it.", "Treasury has not confirmed"),
    )
    llm = FakeLLM(rows, rows)
    classification = _run(llm, _settings(claim_passes=1))

    assert llm.systems == [PREPROCESS_SYSTEM]
    assert classification.pass_a_model == "model-a"
    assert classification.pass_b_model is None
    assert classification.passes_independent is False
    assert classification.total_claims == 2
    assert classification.claim_agreement_rate == 1.0
    for claim in classification.claims:
        assert claim.agreement == "both"
        assert claim.variant_texts == [claim.text]
        assert "not cross-checked" in (claim.agreement_note or "")


def test_end_to_end_agreement_rate_matches_the_fixture() -> None:
    llm = FakeLLM(
        _rows(
            ("Work starts in March.", "work would start in March"),
            ("Councils were told earlier.", "Local councils were told about the plan"),
        ),
        _rows(
            ("The project begins in March.", "work would start in March and run"),
            ("Ministers announced a plan.", "Ministers announced a new coastal defence plan"),
        ),
    )
    classification = _run(llm, _settings())

    # 1 agreed, 1 pass-A-only, 1 pass-B-only.
    assert classification.total_claims == 3
    assert classification.claim_agreement_rate == round(1 / 3, 4)
    assert sorted(c.agreement for c in classification.claims) == [
        "both",
        "pass_a_only",
        "pass_b_only",
    ]


def test_failed_second_pass_degrades_to_one_pass() -> None:
    class HalfBrokenLLM(FakeLLM):
        async def chat_json_any(self, *, attempts, system, user, temperature=0.1):
            if system == PREPROCESS_SYSTEM_B:
                raise RuntimeError("provider down")
            return await super().chat_json_any(
                attempts=attempts, system=system, user=user, temperature=temperature
            )

    llm = HalfBrokenLLM(_rows(("Work starts in March.", "work would start in March")), {})
    classification = _run(llm, _settings())
    assert classification.pass_b_model is None
    assert classification.passes_independent is False
    assert classification.total_claims == 1
    assert classification.claims[0].agreement == "both"
