from __future__ import annotations

import json

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.pipeline.orchestrator import LAYER_TITLES
from app.schemas.envelope import RunEnvelope

ASK_SYSTEM = """You are a read-only assistant sitting beside a journalist who is inspecting one layer of a news-authentication pipeline.

You may explain, quote, and reference the supplied layer output and the accumulated run envelope. You must not:
- mutate the run, change a claim, alter a score, or write an editorial decision
- invent evidence, sources, or layer results that are not in the provided context
- speculate about layers that have not run yet
- issue an authenticity verdict (true/false, fake/real, authentic/inauthentic)

This system is decision support only. Outputs are signals, not a true/false verdict. Final editorial judgement stays with the journalist.
If the question asks you to decide authenticity, refuse and point to the signals already recorded.
Answer in concise prose. Use the claim ids (c1, c2, …) and source ids when you refer to them.
"""


def context_for_layer(envelope: RunEnvelope, layer: int) -> dict:
    data: dict = {
        "run_id": envelope.run_id,
        "current_layer": layer,
        "layer_name": LAYER_TITLES.get(layer, str(layer)),
        "completed_layer": envelope.completed_layer,
        "engines_used": envelope.engines_used,
    }
    if layer >= 1:
        data["input"] = envelope.input.model_dump()
        data["tool_results"] = [t.model_dump() for t in envelope.tool_results]
    if layer >= 2:
        data["classification"] = envelope.classification.model_dump()
    if layer >= 3:
        data["queries"] = envelope.queries.model_dump()
        data["evidence_items"] = [e.model_dump() for e in envelope.evidence_items]
        data["wiki_hits"] = [w.model_dump() for w in envelope.wiki_hits]
        data["existence"] = envelope.corroboration.existence.model_dump()
        data["fact_checks"] = [f.model_dump() for f in envelope.corroboration.fact_checks]
    if layer >= 4:
        data["analysis"] = [a.model_dump() for a in envelope.analysis]
        data["corroboration"] = envelope.corroboration.model_dump()
    if layer >= 5:
        data["uncertainty"] = envelope.uncertainty.model_dump()
    if layer >= 6:
        data["human_decision"] = envelope.human_decision.model_dump()
        data["system_recommendation"] = envelope.uncertainty.recommended_decision
    if layer >= 7:
        data["record"] = envelope.record.model_dump()
    return data


async def answer_question(
    envelope: RunEnvelope,
    *,
    layer: int,
    question: str,
    settings: Settings,
    client,
) -> str:
    llm = LLMRouter(settings, client)
    context = context_for_layer(envelope, layer)
    user = (
        f"CURRENT LAYER: {layer} ({LAYER_TITLES.get(layer, '')})\n"
        f"JOURNALIST QUESTION:\n{question.strip()}\n\n"
        "CONTEXT (only layers that have already run; do not assume later layers):\n"
        + json.dumps(context, ensure_ascii=False, default=str)[:20000]
    )
    attempts = [
        ("openai", settings.uncertainty_model),
        ("anthropic", settings.documentation_model),
        ("gemini", settings.evidence_llm_model),
    ]
    text, _provider, _model = await llm.chat_any(
        attempts=attempts,
        system=ASK_SYSTEM,
        user=user,
        temperature=0.2,
    )
    return text.strip()
