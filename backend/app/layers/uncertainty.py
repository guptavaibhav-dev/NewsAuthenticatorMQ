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
    skipped = [t.tool for t in envelope.tool_results if t.status in {"skipped", "error"}]
    if skipped:
        unknowns.append("Some verification tools did not return results: " + ", ".join(skipped))
    if envelope.corroboration.existence.existence_class == "not_found":
        unknowns.append("Same-article existence was not confirmed on queried portals.")
    if envelope.corroboration.independent_source_count < 2:
        weak.append("Fewer than two independent publisher families corroborate the event.")
    missing_wiki = [h.query for h in envelope.wiki_hits if not h.found]
    if missing_wiki:
        unknowns.append(
            "No Wikipedia/Wikidata hit for: "
            + ", ".join(missing_wiki)
            + " (does not prove a hoax)."
        )
    if any(c.agreement == "contested" for c in envelope.corroboration.claims):
        weak.append("NLI and Gemini disagree on at least one claim.")
    if envelope.classification.disagreements:
        weak.append("LLM and NER entity sets disagree.")
    if envelope.input.fetch_status == "error":
        unknowns.append("URL fetch failed; analysis used provided text only.")

    state = envelope.corroboration.overall_state
    rec: EditorialDecision
    risk: PublicationRisk
    if state in {"corroborated_coverage", "event_corroborated"}:
        rec, risk = "verified", "low"
    elif state == "contested_reporting" or state == "contested":
        rec, risk = "needs_investigation", "high"
    elif state == "single_source":
        rec, risk = "needs_investigation", "moderate"
    else:
        rec, risk = "unverifiable", "high"

    independence = (
        f"{envelope.corroboration.independent_source_count} independent publisher "
        "families among retrieved items. Unknown band is unrated, not unreliable."
    )
    return UncertaintyPayload(
        unknowns=unknowns,
        weak_evidence=weak,
        source_independence_note=independence,
        publication_risk=risk,
        recommended_decision=rec,
        rationale=(
            f"Corroboration state is {state}. Absence of hits is treated as uncertainty, "
            "not as proof the content is false."
        ),
    )


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
    return {
        "existence_class": envelope.corroboration.existence.existence_class,
        "overall_state": envelope.corroboration.overall_state,
        "independent_source_count": envelope.corroboration.independent_source_count,
        "claims": [c.model_dump() for c in envelope.corroboration.claims],
        "tool_results": [t.model_dump() for t in envelope.tool_results],
        "fact_check_count": len(envelope.corroboration.fact_checks),
        "wiki_missing": [h.query for h in envelope.wiki_hits if not h.found],
        "nli_engine": envelope.engines_used.get("nli"),
        "evidence_llm": envelope.engines_used.get("evidence_llm"),
        "disagreements": envelope.classification.disagreements,
    }


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
