from __future__ import annotations

from app.config import Settings
from app.engines.llm_router import LLMRouter
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
    if llm.anthropic_ready():
        try:
            data = await llm.chat_json(
                provider="anthropic",
                model=settings.documentation_model,
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
                model=settings.documentation_model,
            )
            model_used = settings.documentation_model
        except Exception as exc:
            templated.model = f"template (documentation LLM error: {exc})"[:200]
            await emit(
                layer="documentation",
                parameter="verification_record",
                process="citation-backed documentation",
                tool=settings.documentation_model,
                status="error",
                detail=str(exc)[:240],
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
    sources = [
        f"{item.outlet} ({item.source_band}, {item.url})"
        for item in envelope.evidence_items[:8]
    ]
    source_assessment = (
        "Retrieved outlets: " + "; ".join(sources)
        if sources
        else "No portal hits. This is recorded as missing corroboration, not as falsity."
    )
    evidence_summary = (
        f"Existence class: {envelope.corroboration.existence.existence_class}. "
        f"Overall corroboration: {envelope.corroboration.overall_state}. "
        f"Independent publisher families: {envelope.corroboration.independent_source_count}."
    )
    cross = []
    for row in envelope.corroboration.claims:
        cross.append(
            f"{row.claim_id}: NLI support={row.nli_support} contradict={row.nli_contradict}; "
            f"Gemini support={row.llm_support} contradict={row.llm_contradict}; "
            f"agreement={row.agreement}; state={row.state}."
        )
    for fc in envelope.corroboration.fact_checks[:5]:
        cross.append(
            f"Prior fact-check: {fc.publisher} rated “{fc.textual_rating}” ({fc.url})."
        )
    rec = envelope.uncertainty.recommended_decision or "needs_investigation"
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


def _doc_user(envelope: RunEnvelope) -> str:
    import json

    slim = {
        "input": envelope.input.model_dump(),
        "classification": envelope.classification.model_dump(),
        "queries": envelope.queries.model_dump(),
        "evidence": [e.model_dump() for e in envelope.evidence_items],
        "corroboration": envelope.corroboration.model_dump(),
        "uncertainty": envelope.uncertainty.model_dump(),
        "wiki": [w.model_dump() for w in envelope.wiki_hits],
        "engines": envelope.engines_used,
    }
    return json.dumps(slim, ensure_ascii=False)[:20000]
