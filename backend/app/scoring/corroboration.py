from __future__ import annotations

from app.schemas.envelope import (
    ClaimCorroboration,
    CorroborationPayload,
    CorroborationState,
    EngineAgreement,
    GeminiClaimAnalysis,
    PairAnalysis,
    UnscoredReason,
)
from app.schemas.retrieval import ExistenceClass

# Unvalidated defaults inherited from pre-rewrite scoring. Candidates for
# experimental determination, alongside Settings.nli_threshold (0.6), which
# has no cited justification anywhere in this repo.
CONTESTED_MIN_CONTRADICT_WITH_SUPPORT = 1
CONTESTED_HEAVY_CONTRADICT = 2
EVENT_MIN_INDEPENDENT_SUPPORT = 2
SINGLE_SOURCE_SUPPORT = 1
DIRECTION_TIE = "mixed"


def llm_row_participated(gemini: GeminiClaimAnalysis | None) -> bool:
    """True only when Engine B cited at least one real source_id as stance.

    An empty row after hallucinated ids are dropped is a non-response, not an
    LLM opinion of 'no stance'.
    """
    if gemini is None:
        return False
    return bool(gemini.supported_by or gemini.contradicted_by or gemini.unrelated)


def _distinct_sources(
    source_ids: set[str],
    evidence_by_id: dict[str, str],
    source_groups: dict[str, str] | None,
) -> set[str]:
    """Collapse evidence ids to the newsrooms genuinely behind them.

    `source_groups` comes from Layer 3's independence resolution, which has
    already merged wire syndication, shared ownership and reprints. Using it
    here is the point of the rewrite: counting mastheads or pages instead
    treats one wire story republished by twenty papers as twenty outlets
    corroborating a claim, when it is one newsroom's reporting seen twenty
    times.

    An id that Layer 3 did not group is counted as its own source, not collapsed
    by the old publisher-family map. That map over-counted wires and is gone.
    """
    groups: set[str] = set()
    for sid in source_ids:
        if sid not in evidence_by_id:
            continue
        if source_groups and sid in source_groups:
            groups.add(source_groups[sid])
        else:
            groups.add(sid)
    return groups


def fuse_claim(
    *,
    claim_id: str,
    pairs: list[PairAnalysis],
    gemini: GeminiClaimAnalysis | None,
    evidence_by_id: dict[str, str],
    threshold: float,
    existence_class: ExistenceClass,
    source_groups: dict[str, str] | None = None,
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
    participating = llm_row_participated(gemini)
    if participating and gemini is not None:
        llm_support_ids = {sid for sid in gemini.supported_by if sid in valid_ids}
        llm_contradict_ids = {sid for sid in gemini.contradicted_by if sid in valid_ids}

    nli_dir = _direction(len(nli_support_ids), len(nli_contradict_ids))
    llm_dir = _direction(len(llm_support_ids), len(llm_contradict_ids)) if participating else "none"

    if not participating:
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

    # Independent SOURCES, not pages and not mastheads. A claim backed by
    # twenty syndicated copies of one wire report is backed by one source.
    support_families = _distinct_sources(
        nli_support_ids | llm_support_ids, evidence_by_id, source_groups
    )
    contradict_families = _distinct_sources(
        nli_contradict_ids | llm_contradict_ids, evidence_by_id, source_groups
    )

    state = _existence_overlay(
        existence_class=existence_class,
        agreement=agreement,
        support_n=len(support_families),
        contradict_n=len(contradict_families),
        pairs_scored=bool(pairs),
    )

    return ClaimCorroboration(
        claim_id=claim_id,
        nli_support=len(_distinct_sources(nli_support_ids, evidence_by_id, source_groups)),
        nli_contradict=len(
            _distinct_sources(nli_contradict_ids, evidence_by_id, source_groups)
        ),
        llm_support=len(_distinct_sources(llm_support_ids, evidence_by_id, source_groups)),
        llm_contradict=len(
            _distinct_sources(llm_contradict_ids, evidence_by_id, source_groups)
        ),
        independent_support_outlets=len(support_families),
        independent_contradict_outlets=len(contradict_families),
        agreement=agreement,
        state=state,
        existence_class=existence_class,
    )


def overall_state(claims: list[ClaimCorroboration], *, pairs_scored: bool) -> CorroborationState:
    if not pairs_scored:
        return "not_assessed"
    if not claims or all(c.state == "not_assessed" for c in claims):
        return "not_assessed"
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
    return DIRECTION_TIE


def _existence_overlay(
    *,
    existence_class: ExistenceClass,
    agreement: EngineAgreement,
    support_n: int,
    contradict_n: int,
    pairs_scored: bool,
) -> CorroborationState:
    # Scored-or-not is decided before existence is consulted. Existence class
    # is recorded on the claim; it must not be flattened into a state that
    # pretends we evaluated stance we never ran.
    if not pairs_scored:
        return "not_assessed"
    if (
        contradict_n >= CONTESTED_MIN_CONTRADICT_WITH_SUPPORT
        and support_n >= CONTESTED_MIN_CONTRADICT_WITH_SUPPORT
    ):
        return "contested_reporting"
    if contradict_n >= CONTESTED_HEAVY_CONTRADICT:
        return "contested_reporting"
    same_article = existence_class in {
        "exact_url",
        "title_match",
        "near_duplicate",
        "syndicated",
    }
    if same_article and agreement == "convergent" and support_n >= SINGLE_SOURCE_SUPPORT:
        return "corroborated_coverage"
    if support_n >= EVENT_MIN_INDEPENDENT_SUPPORT:
        return "event_corroborated"
    if support_n == SINGLE_SOURCE_SUPPORT:
        return "single_source"
    # Syndication without stance support is not single_source: distribution
    # is not an engine having assessed the claim.
    if agreement == "contested":
        return "contested"
    return "no_corroboration_found"


def reason_unscored(
    *,
    claims: list,
    documents: list,
    pairs: list,
) -> UnscoredReason | None:
    if pairs:
        return None
    if not claims:
        return "no_claims"
    if not documents:
        return "no_documents"
    return "documents_filtered"


def build_payload(
    *,
    claims: list[ClaimCorroboration],
    independent_source_count: int,
    pairs_scored: bool,
    unscored_reason: UnscoredReason | None,
    existence_class: ExistenceClass | None,
    nli_engine: str = "",
    nli_can_detect_contradiction: bool = False,
    group_join_misses: int = 0,
    llm_dropped_id_count: int = 0,
    evidence_llm_model: str | None = None,
    evidence_llm_temperature: float | None = None,
    evidence_llm_temperature_pinned: bool | None = None,
) -> CorroborationPayload:
    return CorroborationPayload(
        overall_state=overall_state(claims, pairs_scored=pairs_scored),
        independent_source_count=independent_source_count,
        claims=claims,
        pairs_scored=pairs_scored,
        unscored_reason=unscored_reason,
        existence_class=existence_class,
        nli_engine=nli_engine,
        nli_can_detect_contradiction=nli_can_detect_contradiction,
        group_join_misses=group_join_misses,
        llm_dropped_id_count=llm_dropped_id_count,
        evidence_llm_model=evidence_llm_model,
        evidence_llm_temperature=evidence_llm_temperature,
        evidence_llm_temperature_pinned=evidence_llm_temperature_pinned,
    )
