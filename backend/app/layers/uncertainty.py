from __future__ import annotations

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.schemas.envelope import EditorialDecision, PublicationRisk, RunEnvelope, UncertaintyPayload

UNCERTAINTY_SYSTEM = """You are the Uncertainty and Risk Assessment layer.
You receive STRUCTURED scores only (no analyst prose, no authenticity target).
Do not invent evidence. Do not declare the story true or false.
Recommend one of: verified, misleading, manipulated, unsupported, unverifiable, needs_investigation
This is a recommendation for a journalist, not a verdict.
Return JSON:
{
  "unknowns": ["..."],
  "weak_evidence": ["..."],
  "source_independence_note": "...",
  "publication_risk": "low|moderate|high|unknown",
  "recommended_decision": "...",
  "rationale": "short"
}
Be conservative: missing corroboration => unverifiable or needs_investigation, never fake.
"""


async def run_uncertainty(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    llm: LLMRouter,
    emit,
) -> UncertaintyPayload:
    structured = _structured_view(envelope)
    await emit(
        layer="uncertainty",
        parameter="corroboration+tools",
        process="conservative risk assessment",
        tool=settings.uncertainty_model,
        status="running",
        detail="Model sees structured scores only, not Gemini prose.",
    )

    payload = rule_based_uncertainty(envelope)
    model_used = "rule-based"

    attempts = [
        ("openai", settings.uncertainty_model),
        ("anthropic", settings.documentation_model),
        ("gemini", settings.evidence_llm_model),
    ]
    if any(llm.provider_ready(p) for p, _ in attempts):
        user = (
            "STRUCTURED SIGNALS (do not assume missing tools imply fabrication):\n"
            + _json(structured)
        )
        try:
            data, _provider, model_used = await llm.chat_json_any(
                attempts=attempts,
                system=UNCERTAINTY_SYSTEM,
                user=user,
                temperature=0,
            )
            payload = _from_llm(data, payload)
        except Exception:
            model_used = "rule-based"

    payload.model = model_used
    envelope.engines_used["uncertainty"] = model_used
    await emit(
        layer="uncertainty",
        parameter="publication_risk",
        process="conservative risk assessment",
        tool=model_used,
        status="ok",
        detail=f"risk={payload.publication_risk}; recommendation={payload.recommended_decision} (not auto-committed).",
    )
    return payload


def rule_based_uncertainty(envelope: RunEnvelope) -> UncertaintyPayload:
    unknowns: list[str] = []
    weak: list[str] = []
    retrieval = envelope.retrieval

    if retrieval is not None:
        unreached = [
            f"{r.adapter} ({r.reason or r.status})"
            for r in retrieval.coverage.adapters
            if r.status in {"error", "skipped_no_key", "skipped_out_of_range"}
        ]
        if unreached:
            unknowns.append(
                "Some sources could not be searched: "
                + ", ".join(unreached)
                + ". This narrows what we could see; it says nothing about the article."
            )
        # not_found and out_of_range are different statements and are worded
        # differently. Flattening them is the defect the rewrite removes.
        if retrieval.existence_class == "out_of_range":
            unknowns.append(
                "We were unable to look for this article elsewhere "
                f"({retrieval.coverage.existence_search}). Not searched, not absent."
            )
        elif retrieval.existence_class == "not_found":
            unknowns.append(
                "The article was not found on any source we could search. "
                "An open question, not evidence against it."
            )
        if retrieval.coverage.capability_notes:
            unknowns.append(
                "Capability checks that did not run: "
                + "; ".join(retrieval.coverage.capability_notes)
            )
        missing_entities = [
            row.entity_text
            for row in retrieval.entity_grounding
            if not row.entity_is_well_known
        ]
    else:
        unknowns.append("Layer 3 has not run, so coverage is unknown.")
        missing_entities = []

    # Independent SOURCES, after wire and ownership collapsing — not outlets
    # and not pages. Twenty papers running one agency report is one source.
    # Skip when Layer 4 did not assess: zero sources then is a gap, not thin
    # corroboration.
    if (
        envelope.corroboration.overall_state != "not_assessed"
        and envelope.corroboration.independent_source_count < 2
    ):
        weak.append("Fewer than two independent sources corroborate the event.")
    if missing_entities:
        unknowns.append(
            "No Wikipedia/Wikidata hit for: "
            + ", ".join(missing_entities)
            + " (does not prove a hoax)."
        )
    if any(c.agreement == "contested" for c in envelope.corroboration.claims):
        weak.append("NLI and Gemini disagree on at least one claim.")
    if envelope.classification.disagreements:
        weak.append("LLM and NER entity sets disagree.")
    if envelope.input.fetch_status == "error":
        unknowns.append("URL fetch failed; analysis used provided text only.")

    corr = envelope.corroboration
    if corr.pairs_scored and not corr.nli_can_detect_contradiction:
        unknowns.append(
            "Contradiction detection was unavailable (lexical NLI fallback). "
            "A zero contradiction count is not a finding that none exists."
        )
    if corr.group_join_misses:
        unknowns.append(
            f"{corr.group_join_misses} document(s) did not join an IndependentSource "
            "group. Independent-source counts are an upper bound."
        )
    if corr.llm_dropped_id_count:
        unknowns.append(
            f"Engine B cited {corr.llm_dropped_id_count} source id(s) that were not "
            "in the evidence list; those were dropped and did not count as stance."
        )
    if corr.evidence_llm_temperature_pinned is False:
        unknowns.append(
            "Engine B sampling was not pinned (gemini-3* omits temperature). "
            "Fusion input may differ across runs."
        )

    state = envelope.corroboration.overall_state
    rec: EditorialDecision
    risk: PublicationRisk
    if state == "not_assessed":
        rec, risk = "needs_investigation", "unknown"
        reason = envelope.corroboration.unscored_reason
        existence = envelope.corroboration.existence_class
        if existence == "out_of_range":
            unknowns.append(
                "Layer 4 did not assess claims: sources could not cover this "
                "article. That is a gap in reach, not a finding."
            )
        elif existence == "not_found" and reason == "no_documents":
            unknowns.append(
                "Layer 4 did not assess claims: no coverage was found to score "
                "against. An open question, not evidence against the article."
            )
        else:
            unknowns.append(
                "Layer 4 did not assess claims against evidence "
                f"({reason or 'no pairs scored'}). That is not a finding "
                "against the article."
            )
    elif state in {"corroborated_coverage", "event_corroborated"}:
        rec, risk = "verified", "low"
    elif state == "contested_reporting" or state == "contested":
        rec, risk = "needs_investigation", "high"
    elif state == "single_source":
        rec, risk = "needs_investigation", "moderate"
    else:
        rec, risk = "unverifiable", "high"

    independence = _independence_note(envelope)
    if state == "not_assessed":
        rationale = (
            "Corroboration was not assessed: no claim × evidence pair was scored. "
            "That is an absence of assessment, not an absence of support."
        )
    else:
        rationale = (
            f"Corroboration state is {state}. Absence of hits is treated as uncertainty, "
            "not as proof the content is false."
        )
    return UncertaintyPayload(
        unknowns=unknowns,
        weak_evidence=weak,
        source_independence_note=independence,
        publication_risk=risk,
        recommended_decision=rec,
        rationale=rationale,
    )


def _independence_note(envelope: RunEnvelope) -> str:
    """State pages and sources together, so neither can be read as the other."""
    retrieval = envelope.retrieval
    if retrieval is None:
        return "Layer 3 has not run, so independence is unknown."
    collapsed = [
        source
        for source in retrieval.independent_sources
        if source.merge_reason != "none"
    ]
    note = (
        f"{retrieval.document_count} page(s) retrieved, resolving to "
        f"{retrieval.independent_source_count} independent source(s). The page "
        "count is inflated by syndication and is not corroboration; only the "
        "source count is."
    )
    if collapsed:
        note += " Collapsed: " + " ".join(source.merge_evidence for source in collapsed)
    return note


def _from_llm(data: dict, fallback: UncertaintyPayload) -> UncertaintyPayload:
    risk = data.get("publication_risk")
    rec = data.get("recommended_decision")
    allowed_decisions = {
        "verified",
        "misleading",
        "manipulated",
        "unsupported",
        "unverifiable",
        "needs_investigation",
    }
    allowed_risk = {"low", "moderate", "high", "unknown"}
    return UncertaintyPayload(
        unknowns=list(data.get("unknowns") or fallback.unknowns),
        weak_evidence=list(data.get("weak_evidence") or fallback.weak_evidence),
        source_independence_note=str(
            data.get("source_independence_note") or fallback.source_independence_note
        ),
        publication_risk=risk if risk in allowed_risk else fallback.publication_risk,
        recommended_decision=rec if rec in allowed_decisions else fallback.recommended_decision,
        rationale=str(data.get("rationale") or fallback.rationale),
    )


def _structured_view(envelope: RunEnvelope) -> dict:
    retrieval = envelope.retrieval
    view = {
        "overall_state": envelope.corroboration.overall_state,
        "pairs_scored": envelope.corroboration.pairs_scored,
        "unscored_reason": envelope.corroboration.unscored_reason,
        "existence_class": envelope.corroboration.existence_class
        or (retrieval.existence_class if retrieval else None),
        "independent_source_count": envelope.corroboration.independent_source_count,
        "claims": [c.model_dump() for c in envelope.corroboration.claims],
        "tool_results": [t.model_dump() for t in envelope.tool_results],
        "fact_check_count": len(retrieval.factchecks) if retrieval else 0,
        "wiki_missing": [
            row.entity_text
            for row in (retrieval.entity_grounding if retrieval else [])
            if not row.entity_is_well_known
        ],
        "nli_engine": envelope.corroboration.nli_engine or envelope.engines_used.get("nli"),
        "nli_can_detect_contradiction": envelope.corroboration.nli_can_detect_contradiction,
        "group_join_misses": envelope.corroboration.group_join_misses,
        "llm_dropped_id_count": envelope.corroboration.llm_dropped_id_count,
        "evidence_llm": envelope.engines_used.get("evidence_llm"),
        "evidence_llm_model": envelope.corroboration.evidence_llm_model,
        "evidence_llm_temperature": envelope.corroboration.evidence_llm_temperature,
        "evidence_llm_temperature_pinned": envelope.corroboration.evidence_llm_temperature_pinned,
        "disagreements": envelope.classification.disagreements,
    }
    if retrieval is None:
        return view

    view.update(
        {
            "existence_class": retrieval.existence_class,
            "title_match_strength": retrieval.title_match_strength,
            # Both counts are supplied, labelled, so the model cannot mistake
            # page volume for corroboration. The system prompt already forbids
            # a verdict; this stops it inferring one from a big number.
            "document_count_pages_not_corroboration": retrieval.document_count,
            "independent_source_count": retrieval.independent_source_count,
            "merge_reasons": [
                source.merge_reason for source in retrieval.independent_sources
            ],
            "adapters": [r.model_dump() for r in retrieval.coverage.adapters],
            "coverage": retrieval.coverage.model_dump(),
            "wiki_missing": [
                row.entity_text
                for row in retrieval.entity_grounding
                if not row.entity_is_well_known
            ],
            "ranking_method": retrieval.ranking_method,
        }
    )
    return view


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
