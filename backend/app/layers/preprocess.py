from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.engines.ner import NerEngine, parse_date_hint
from app.logutil import short_error
from app.schemas.envelope import (
    Claim,
    ClassificationPayload,
    DateWindow,
    Entity,
    InputPayload,
    RunEnvelope,
)

PREPROCESS_SYSTEM = """You are the Pre-processing and Classification layer of a journalist-centred news authentication framework.
You extract structure. You do not judge truth, authenticity, or whether the story is fake.
Return JSON only with keys:
content_type (article|claim|headline|social_post|mixed),
headline (string or null),
claims: array of {id, text, checkworthy (bool), kind (fact|opinion)},
entities: array of {text, type} where type is PERSON|ORG|GPE|DATE|EVENT,
date_window: {start (YYYY-MM-DD or null), end (YYYY-MM-DD or null), confidence (high|weak|none)}.
Split into atomic check-worthy factual claims. Ignore pure opinion unless it contains a checkable fact.
Use claim ids c1, c2, ...
If a date is uncertain, set confidence to weak and widen the window.
"""


async def run_preprocess(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    llm: LLMRouter,
    ner: NerEngine,
    emit,
) -> ClassificationPayload:
    text = envelope.input.raw_text
    await emit(
        layer="preprocess",
        parameter="input.text",
        process="claim extraction and classification",
        tool=settings.preprocess_model,
        status="running",
        detail="Extracting atomic claims, content type, and entities.",
    )

    llm_payload: dict = {}
    model_used = None
    attempts = [
        ("openai", settings.preprocess_model),
        ("anthropic", settings.query_planner_model),
        ("gemini", settings.evidence_llm_model),
    ]
    if any(llm.provider_ready(p) for p, _ in attempts):
        try:
            llm_payload, provider, model_used = await llm.chat_json_any(
                attempts=attempts,
                system=PREPROCESS_SYSTEM,
                user=_user_prompt(envelope.input),
            )
            if (provider, model_used) != attempts[0] or model_used != settings.preprocess_model:
                await emit(
                    layer="preprocess",
                    parameter="claims",
                    process="claim extraction failover",
                    tool=model_used,
                    status="skipped",
                    detail=(
                        f"{settings.preprocess_model} unavailable; "
                        f"extracted claims with {provider}/{model_used}."
                    ),
                )
        except Exception as exc:
            llm_payload = {}
            model_used = None
            await emit(
                layer="preprocess",
                parameter="claims",
                process="LLM claim extraction",
                tool=settings.preprocess_model,
                status="error",
                detail=short_error(exc),
            )
    else:
        await emit(
            layer="preprocess",
            parameter="claims",
            process="LLM claim extraction",
            tool=settings.preprocess_model,
            status="skipped",
            detail="No LLM provider is configured; using heuristic claims.",
        )

    await emit(
        layer="preprocess",
        parameter="entities",
        process="independent NER",
        tool="ner",
        status="running",
        detail="spaCy / Hugging Face / heuristic NER in parallel with the LLM.",
    )
    ner_entities = await ner.extract(text)

    claims = _claims_from_llm(llm_payload, text)
    llm_entities = _entities_from_llm(llm_payload)
    merged, disagreements = merge_entities(llm_entities, ner_entities)
    date_window = _date_window(llm_payload, text, merged)
    content_type = llm_payload.get("content_type") or _guess_type(envelope.input, text)
    headline = llm_payload.get("headline") or envelope.input.fetched_title

    classification = ClassificationPayload(
        content_type=content_type if content_type in {
            "article", "claim", "headline", "social_post", "mixed", "unknown"
        } else "unknown",
        headline=headline,
        claims=claims,
        entities=merged,
        date_window=date_window,
        disagreements=disagreements,
        preprocess_model=model_used or "heuristic",
        ner_engine=ner.engine_name,
    )
    envelope.engines_used["preprocess"] = classification.preprocess_model or "heuristic"
    envelope.engines_used["ner"] = ner.engine_name
    await emit(
        layer="preprocess",
        parameter="claims",
        process="claim extraction and classification",
        tool=classification.preprocess_model,
        status="ok",
        detail=f"{len(claims)} claim(s), {len(merged)} entities, {len(disagreements)} NER/LLM disagreement(s).",
    )
    return classification


def _user_prompt(payload: InputPayload) -> str:
    parts = []
    if payload.fetched_title:
        parts.append(f"TITLE: {payload.fetched_title}")
    if payload.url:
        parts.append(f"URL: {payload.url}")
    if payload.publisher_domain:
        parts.append(f"DOMAIN: {payload.publisher_domain}")
    parts.append("CONTENT:\n" + (payload.raw_text or "")[:8000])
    return "\n".join(parts)


def _claims_from_llm(payload: dict, text: str) -> list[Claim]:
    raw = payload.get("claims") if isinstance(payload, dict) else None
    claims: list[Claim] = []
    if isinstance(raw, list):
        for i, row in enumerate(raw, start=1):
            if not isinstance(row, dict):
                continue
            body = (row.get("text") or "").strip()
            if not body:
                continue
            kind = row.get("kind") if row.get("kind") in {"fact", "opinion"} else "unspecified"
            claims.append(
                Claim(
                    id=str(row.get("id") or f"c{i}"),
                    text=body,
                    checkworthy=bool(row.get("checkworthy", True)),
                    kind=kind,
                )
            )
    if claims:
        return claims[:8]
    return heuristic_claims(text)


def heuristic_claims(text: str) -> list[Claim]:
    sentences = [s.strip() for s in text.replace("?", ".").split(".") if len(s.strip()) > 40]
    if not sentences and text.strip():
        sentences = [text.strip()[:400]]
    return [
        Claim(id=f"c{i}", text=sent[:400], checkworthy=True, kind="unspecified")
        for i, sent in enumerate(sentences[:5], start=1)
    ]


def _entities_from_llm(payload: dict) -> list[Entity]:
    raw = payload.get("entities") if isinstance(payload, dict) else None
    out: list[Entity] = []
    if not isinstance(raw, list):
        return out
    allowed = {"PERSON", "ORG", "GPE", "DATE", "EVENT", "OTHER"}
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = (row.get("text") or "").strip()
        etype = str(row.get("type") or "OTHER").upper()
        if not name:
            continue
        if etype not in allowed:
            etype = "OTHER"
        out.append(Entity(text=name, type=etype, source="llm"))  # type: ignore[arg-type]
    return out


def merge_entities(llm_entities: list[Entity], ner_entities: list[Entity]) -> tuple[list[Entity], list[str]]:
    by_key: dict[str, Entity] = {}
    disagreements: list[str] = []
    llm_index = {(e.text.lower(), e.type) for e in llm_entities}
    ner_index = {(e.text.lower(), e.type) for e in ner_entities}
    llm_names = {e.text.lower() for e in llm_entities}
    ner_names = {e.text.lower() for e in ner_entities}

    for ent in llm_entities + ner_entities:
        key = ent.text.lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ent
            continue
        if existing.source != ent.source:
            existing.source = "both"

    for name, etype in llm_index:
        if name not in ner_names:
            disagreements.append(f"LLM-only entity: {name} ({etype})")
    for name, etype in ner_index:
        if name not in llm_names:
            disagreements.append(f"NER-only entity: {name} ({etype})")
    return list(by_key.values())[:30], disagreements[:20]


def _date_window(payload: dict, text: str, entities: list[Entity]) -> DateWindow:
    raw = payload.get("date_window") if isinstance(payload, dict) else None
    if isinstance(raw, dict) and (raw.get("start") or raw.get("end")):
        conf = raw.get("confidence") if raw.get("confidence") in {"high", "weak", "none"} else "weak"
        return DateWindow(start=raw.get("start"), end=raw.get("end"), confidence=conf)
    hint = parse_date_hint(text)
    if not hint:
        for ent in entities:
            if ent.type == "DATE":
                hint = parse_date_hint(ent.text)
                if hint:
                    break
    if not hint:
        return DateWindow()
    start = (hint - timedelta(days=2)).date().isoformat()
    end = (hint + timedelta(days=2)).date().isoformat()
    return DateWindow(start=start, end=end, confidence="weak")


def _guess_type(payload: InputPayload, text: str) -> str:
    if payload.url and len(text) > 400:
        return "article"
    if payload.url:
        return "headline"
    if len(text) < 180:
        return "claim"
    return "article"
