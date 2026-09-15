from __future__ import annotations

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.logutil import short_error
from app.schemas.envelope import DocumentationPayload, RunEnvelope

DOC_SYSTEM = """You are the Output and Documentation layer.
Write a verification RECORD for a journalist. Cite evidence by outlet and URL.
Do not issue a truth verdict. State that the journalist must decide.
Return JSON with keys:
claim_summary, source_assessment, evidence_summary, cross_source_notes,
uncertainty_statement, editorial_recommendation, citations (array of strings).
Keep each field to 1-3 short paragraphs.
"""


async def run_documentation(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    llm: LLMRouter,
    emit,
) -> DocumentationPayload:
    templated = template_record(envelope)
    await emit(
        layer="documentation",
        parameter="verification_record",
        process="citation-backed documentation",
        tool=settings.documentation_model,
        status="running",
        detail="Producing an audit record, not an authenticity judgement.",
    )
    model_used = "template"
    attempts = [
        ("anthropic", settings.documentation_model),
        ("gemini", settings.evidence_llm_model),
        ("openai", settings.uncertainty_model),
    ]
    if any(llm.provider_ready(p) for p, _ in attempts):
        try:
            data, provider, model_used = await llm.chat_json_any(
                attempts=attempts,
                system=DOC_SYSTEM,
                user=_doc_user(envelope),
            )
            templated = DocumentationPayload(
                claim_summary=str(data.get("claim_summary") or templated.claim_summary),
                source_assessment=str(data.get("source_assessment") or templated.source_assessment),
                evidence_summary=str(data.get("evidence_summary") or templated.evidence_summary),
                cross_source_notes=str(data.get("cross_source_notes") or templated.cross_source_notes),
                uncertainty_statement=str(
                    data.get("uncertainty_statement") or templated.uncertainty_statement
                ),
                editorial_recommendation=str(
                    data.get("editorial_recommendation") or templated.editorial_recommendation
                ),
                citations=[str(c) for c in (data.get("citations") or templated.citations)],
                model=model_used,
            )
            if (provider, model_used) != attempts[0]:
                await emit(
                    layer="documentation",
                    parameter="verification_record",
                    process="citation-backed documentation",
                    tool=model_used,
                    status="skipped",
                    detail=(
                        f"{settings.documentation_model} unavailable; "
                        f"record written with {provider}/{model_used}."
                    ),
                )
        except Exception as exc:
            templated.model = f"template ({short_error(exc)})"[:200]
            model_used = "template"
            await emit(
                layer="documentation",
                parameter="verification_record",
                process="citation-backed documentation",
                tool=settings.documentation_model,
                status="error",
                detail=short_error(exc),
            )
    templated.model = model_used
    envelope.engines_used["documentation"] = model_used
    await emit(
        layer="documentation",
        parameter="verification_record",
        process="citation-backed documentation",
        tool=model_used,
        status="ok",
        detail="Record ready. Human editorial decision is still required.",
    )
    return templated


def template_record(envelope: RunEnvelope) -> DocumentationPayload:
    claims = envelope.classification.claims
    claim_summary = (
        "Check-worthy claims: "
        + "; ".join(f"{c.id}. {c.text}" for c in claims)
        if claims
        else "No atomic claims were extracted."
    )
    retrieval = envelope.retrieval
    source_assessment = _source_assessment(envelope)
    evidence_summary = _evidence_summary(envelope)
    cross = []
    if retrieval is not None:
        for source in retrieval.independent_sources:
            if source.merge_reason != "none":
                cross.append(f"Source grouping: {source.merge_evidence}")
        for note in retrieval.coverage.capability_notes:
            cross.append(f"Coverage limit: {note}")
    for row in envelope.corroboration.claims:
        cross.append(
            f"{row.claim_id}: NLI support={row.nli_support} contradict={row.nli_contradict}; "
            f"Gemini support={row.llm_support} contradict={row.llm_contradict}; "
            f"agreement={row.agreement}; state={row.state}."
        )
    if retrieval is not None:
        for record in retrieval.factchecks[:5]:
            # Attributed to the reviewer by name. It is their rating of their
            # reading of a claim, not a NewsAuth finding about this article.
            cross.append(
                f"Prior fact-check by {record.reviewer_name or 'an unnamed reviewer'}, "
                f"which rated “{record.rating_text}” the claim "
                f"“{record.reviewed_claim_text}” ({record.review_url})."
            )
    else:
        for fc in envelope.corroboration.fact_checks[:5]:
            cross.append(
                f"Prior fact-check: {fc.publisher} rated “{fc.textual_rating}” ({fc.url})."
            )
    rec = envelope.uncertainty.recommended_decision or "needs_investigation"
    if retrieval is not None:
        # One citation per independent source, not per page: citing twenty
        # syndicated copies of one wire report would pad the record with
        # twenty references to a single piece of journalism.
        citations = [source.representative_url for source in retrieval.independent_sources]
        citations += [record.review_url for record in retrieval.factchecks if record.review_url]
    else:
        citations = [item.url for item in envelope.evidence_items if item.url]
        citations += [fc.url for fc in envelope.corroboration.fact_checks if fc.url]
    return DocumentationPayload(
        claim_summary=claim_summary,
        source_assessment=source_assessment,
        evidence_summary=evidence_summary,
        cross_source_notes=" ".join(cross) or "No cross-source comparison available.",
        uncertainty_statement=(
            envelope.uncertainty.rationale
            + " Unknowns: "
            + "; ".join(envelope.uncertainty.unknowns or ["none recorded"])
        ),
        editorial_recommendation=(
            f"System recommendation (not a verdict): {rec}. "
            "The journalist must select the editorial decision in the dashboard."
        ),
        citations=citations,
        model="template",
    )


def _source_assessment(envelope: RunEnvelope) -> str:
    """Who published on this, counted as newsrooms rather than as pages."""
    retrieval = envelope.retrieval
    if retrieval is None:
        sources = [
            f"{item.outlet} ({item.source_band}, {item.url})"
            for item in envelope.evidence_items[:8]
        ]
        return (
            "Retrieved outlets: " + "; ".join(sources)
            if sources
            else "No portal hits. This is recorded as missing corroboration, not as falsity."
        )
    if not retrieval.independent_sources:
        if retrieval.existence_class == "out_of_range":
            return (
                "No source could be searched for this article, so there is "
                "nothing to assess. This is a gap in our reach, not a finding."
            )
        return (
            "No coverage was found on the sources we could search. This is "
            "recorded as missing corroboration, not as falsity."
        )
    rows = []
    for source in retrieval.independent_sources[:8]:
        who = ", ".join(source.publisher_ids) or "unattributed"
        detail = f"{who} — {source.representative_url}"
        if source.merge_reason != "none":
            detail += f" ({len(source.member_urls)} pages merged as {source.merge_reason})"
        rows.append(detail)
    return (
        f"{retrieval.independent_source_count} independent source(s) behind "
        f"{retrieval.document_count} retrieved page(s): " + "; ".join(rows)
    )


def _evidence_summary(envelope: RunEnvelope) -> str:
    retrieval = envelope.retrieval
    if retrieval is None:
        return (
            f"Existence class: {envelope.corroboration.existence.existence_class}. "
            f"Overall corroboration: {envelope.corroboration.overall_state}. "
            f"Independent publisher families: {envelope.corroboration.independent_source_count}."
        )
    if retrieval.existence_class == "out_of_range":
        existence = (
            "Existence: we were unable to search for this article elsewhere "
            f"({retrieval.coverage.existence_search}). Never looked, so nothing "
            "follows from it."
        )
    elif retrieval.existence_class == "not_found":
        existence = (
            "Existence: searched and not found on any reachable source. An open "
            "question, not evidence the story is false."
        )
    else:
        existence = (
            f"Existence: {retrieval.existence_class} "
            f"(title match strength {retrieval.title_match_strength})."
        )
    return (
        f"{existence} Overall corroboration: {envelope.corroboration.overall_state}. "
        f"{retrieval.independent_source_count} independent source(s) — the figure "
        f"that bears on corroboration — behind {retrieval.document_count} retrieved "
        f"page(s), which syndication inflates. Ranked by "
        f"{retrieval.ranking_method or 'no ranking engine'}."
    )


def _doc_user(envelope: RunEnvelope) -> str:
    import json

    retrieval = envelope.retrieval
    slim = {
        "input": envelope.input.model_dump(),
        "classification": envelope.classification.model_dump(),
        "corroboration": envelope.corroboration.model_dump(),
        "uncertainty": envelope.uncertainty.model_dump(),
        "human_decision": envelope.human_decision.model_dump(),
        "engines": envelope.engines_used,
    }
    if retrieval is not None:
        slim["retrieval"] = retrieval.model_dump()
    else:
        slim["queries"] = envelope.queries.model_dump()
        slim["evidence"] = [e.model_dump() for e in envelope.evidence_items]
        slim["wiki"] = [w.model_dump() for w in envelope.wiki_hits]
    return json.dumps(slim, ensure_ascii=False)[:20000]
