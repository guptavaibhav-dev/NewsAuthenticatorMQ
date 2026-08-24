from __future__ import annotations

from app.schemas.envelope import (
    ClaimCorroboration,
    CorroborationPayload,
    CorroborationState,
    EngineAgreement,
    ExistenceResult,
    GeminiClaimAnalysis,
    PairAnalysis,
)
from app.scoring.source_independence import publisher_family


def fuse_claim(
    *,
    claim_id: str,
    pairs: list[PairAnalysis],
    gemini: GeminiClaimAnalysis | None,
    evidence_by_id: dict[str, str],
    threshold: float,
    existence: ExistenceResult,
) -> ClaimCorroboration:
    valid_ids = set(evidence_by_id)

    nli_support_ids = {
        p.source_id
        for p in pairs
        if p.nli_label == "entailment" and p.nli_score >= threshold
    }
    nli_contradict_ids = {
        p.source_id
        for p in pairs
        if p.nli_label == "contradiction" and p.nli_score >= threshold
    }

    llm_support_ids: set[str] = set()
    llm_contradict_ids: set[str] = set()
    if gemini:
        llm_support_ids = {sid for sid in gemini.supported_by if sid in valid_ids}
        llm_contradict_ids = {sid for sid in gemini.contradicted_by if sid in valid_ids}

    nli_dir = _direction(len(nli_support_ids), len(nli_contradict_ids))
    llm_dir = _direction(len(llm_support_ids), len(llm_contradict_ids)) if gemini else "none"

    if gemini is None:
        agreement: EngineAgreement = "nli_only" if nli_dir != "none" else "none"
    elif nli_dir == "none" and llm_dir != "none":
        agreement = "llm_only"
    elif nli_dir != "none" and llm_dir == "none":
        agreement = "nli_only"
    elif nli_dir == llm_dir and nli_dir != "none":
        agreement = "convergent"
    elif nli_dir != "none" and llm_dir != "none" and nli_dir != llm_dir:
        agreement = "contested"
    else:
        agreement = "none"

    support_families = {
        publisher_family(evidence_by_id[sid])
        for sid in (nli_support_ids | llm_support_ids)
        if sid in evidence_by_id
    }
    contradict_families = {
        publisher_family(evidence_by_id[sid])
        for sid in (nli_contradict_ids | llm_contradict_ids)
        if sid in evidence_by_id
    }

    state = _existence_overlay(
        existence=existence,
        agreement=agreement,
        support_n=len(support_families),
        contradict_n=len(contradict_families),
        retrieved=bool(evidence_by_id),
    )

    return ClaimCorroboration(
        claim_id=claim_id,
        nli_support=len(
            {publisher_family(evidence_by_id[s]) for s in nli_support_ids if s in evidence_by_id}
        ),
        nli_contradict=len(
            {
                publisher_family(evidence_by_id[s])
                for s in nli_contradict_ids
                if s in evidence_by_id
            }
        ),
        llm_support=len(
            {publisher_family(evidence_by_id[s]) for s in llm_support_ids if s in evidence_by_id}
        ),
        llm_contradict=len(
            {
                publisher_family(evidence_by_id[s])
                for s in llm_contradict_ids
                if s in evidence_by_id
            }
        ),
        independent_support_outlets=len(support_families),
        independent_contradict_outlets=len(contradict_families),
        agreement=agreement,
        state=state,
    )


def overall_state(claims: list[ClaimCorroboration], retrieved: bool) -> CorroborationState:
    if not retrieved:
        return "no_corroboration_found"
    if any(c.agreement == "contested" or c.state == "contested_reporting" for c in claims):
        return "contested_reporting" if any(
            c.state == "contested_reporting" for c in claims
        ) else "contested"
    if any(c.state == "corroborated_coverage" for c in claims):
        return "corroborated_coverage"
    if any(c.state == "event_corroborated" for c in claims):
        return "event_corroborated"
    if any(c.state == "single_source" for c in claims):
        return "single_source"
    return "no_corroboration_found"


def _direction(support: int, contradict: int) -> str:
    if support == 0 and contradict == 0:
        return "none"
    if contradict > support:
        return "contradict"
    if support > contradict:
        return "support"
    return "mixed"


def _existence_overlay(
    *,
    existence,
    agreement: EngineAgreement,
    support_n: int,
    contradict_n: int,
    retrieved: bool,
) -> CorroborationState:
    if not retrieved:
        return "no_corroboration_found"
    if contradict_n >= 1 and support_n >= 1:
        return "contested_reporting"
    if contradict_n >= 2:
        return "contested_reporting"
    same_article = existence.existence_class in {
        "exact_url_match",
        "title_match",
        "near_duplicate",
        "syndicated_or_reprint",
    }
    if same_article and agreement == "convergent" and support_n >= 1:
        return "corroborated_coverage"
    if support_n >= 2:
        return "event_corroborated"
    if support_n == 1 or existence.existence_class == "syndicated_or_reprint":
        return "single_source"
    if agreement == "contested":
        return "contested"
    return "no_corroboration_found"


def build_payload(
    *,
    existence: ExistenceResult,
    claims: list[ClaimCorroboration],
    fact_checks,
    independent_source_count: int,
    retrieved: bool,
) -> CorroborationPayload:
    return CorroborationPayload(
        existence=existence,
        overall_state=overall_state(claims, retrieved),
        independent_source_count=independent_source_count,
        claims=claims,
        fact_checks=fact_checks,
    )
