from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta

from app.config import Settings
from app.engines.llm_router import LLMRouter
from app.engines.ner import NerEngine, parse_date_hint
from app.layers.claim_agreement import agreement_rate, mark_single_pass, reconcile_passes
from app.layers.grounding import locate_quote, segment_source_for_span
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
claims: array of {id, text, source_quote, label, checkworthy (bool)},
entities: array of {text, type} where type is PERSON|ORG|GPE|DATE|EVENT,
date_window: {start (YYYY-MM-DD or null), end (YYYY-MM-DD or null), confidence (high|weak|none)}.

Claim rules:
- id: c1, c2, c3, ...
- text: the claim rewritten as a single standalone sentence.
- source_quote: the EXACT substring of the article that the claim came from.
  Copy it character for character out of CONTENT below. Do not paraphrase it,
  do not fix spelling or punctuation, do not change quotation marks, do not
  shorten it with "..." or any other ellipsis, and do not stitch separated
  passages into one quote. A shorter quote that is exact is always better than
  a longer quote that is edited.
- If you cannot supply a verbatim supporting quote for a claim, omit that claim
  entirely. Never invent or reconstruct a quote to satisfy the format.
- label: fact | opinion | unclear.

Split into atomic check-worthy factual claims. Ignore pure opinion unless it contains a checkable fact.
If a date is uncertain, set confidence to weak and widen the window.
"""

# Pass B. Same contract, independently worded, so the second pass is not just
# an echo of the first one's phrasing. It never sees pass A's output.
PREPROCESS_SYSTEM_B = """Your job is structural annotation of a news item for a newsroom verification tool.
Describe what the text says. Do not assess whether any of it is correct, trustworthy, or fabricated.

Emit a single JSON object and nothing else, with these keys:
content_type — one of article, claim, headline, social_post, mixed
headline — the headline string, or null
claims — a list of objects, each {id, text, source_quote, label, checkworthy}
entities — a list of objects, each {text, type}, type drawn from PERSON, ORG, GPE, DATE, EVENT
date_window — {start, end, confidence}; dates as YYYY-MM-DD or null; confidence one of high, weak, none

For every entry in claims:
  id — sequential, starting at c1
  text — one self-contained sentence stating the assertion
  label — fact if it is checkable, opinion if it is a judgement, unclear if you cannot tell
  checkworthy — true when the assertion is worth verifying
  source_quote — the run of characters in the supplied article that the assertion rests on.
    Transcribe it exactly as it appears. Matching the original matters more than reading well:
    keep the original punctuation and quotation marks, keep any typo, take a short span rather
    than trimming a long one with an ellipsis, and never splice two separate places together.
    Should no contiguous run of the article support an assertion, leave that assertion out of
    the list altogether. Do not reconstruct a quote from memory to fill the field.

Break compound statements into separate, individually checkable entries. Skip commentary unless
it contains something checkable. Widen date_window and mark confidence weak when the timing is vague.
"""

_SENTENCE = re.compile(r"[^.?!]+(?:[.?!]+|$)")


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

    extraction = await _extract_claims(
        envelope.input, settings=settings, llm=llm, emit=emit
    )
    llm_payload = extraction.payload_a
    model_used = extraction.pass_a_model if extraction.pass_a_model != "heuristic" else None

    await emit(
        layer="preprocess",
        parameter="entities",
        process="independent NER",
        tool="ner",
        status="running",
        detail="spaCy / Hugging Face / heuristic NER in parallel with the LLM.",
    )
    ner_entities = await ner.extract(text)

    claims = extraction.claims
    ungrounded = [c for c in claims if c.grounding == "not_found"]
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
        ungrounded_claim_count=len(ungrounded),
        total_claims=len(claims),
        claim_agreement_rate=agreement_rate(claims),
        pass_a_model=extraction.pass_a_model,
        pass_b_model=extraction.pass_b_model,
        passes_independent=extraction.passes_independent,
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
    if classification.pass_b_model:
        single = [c for c in claims if c.agreement != "both"]
        await emit(
            layer="preprocess",
            parameter="claims",
            process="claim cross-check",
            tool=f"{classification.pass_a_model} + {classification.pass_b_model}",
            status="ok",
            detail=(
                f"{int(classification.claim_agreement_rate * 100)}% of claims were found by both "
                f"passes; {len(single)} found by one pass only (kept, lower confidence). "
                "Agreement measures extractor overlap, not whether a claim is true."
            ),
        )
    if ungrounded:
        await emit(
            layer="preprocess",
            parameter="claims",
            process="quote grounding",
            tool=classification.preprocess_model,
            status="empty",
            detail=(
                f"{len(ungrounded)} claim(s) quote text that is not in the article "
                f"({', '.join(c.id for c in ungrounded)}); kept and flagged unverified. "
                "This reflects extraction quality, not the truth of the article."
            ),
        )
    return classification


@dataclass
class ClaimExtraction:
    """Result of one or two claim-extraction passes."""

    claims: list[Claim]
    payload_a: dict
    pass_a_model: str
    pass_b_model: str | None
    passes_independent: bool


def _attempt_chains(settings: Settings, llm: LLMRouter) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Build the (provider, model) chains for pass A and pass B.

    Pass B prefers a provider pass A will not reach for, so the two passes are
    genuinely different models when more than one is configured. If only one
    provider is available both passes use it; `passes_independent` is then
    computed from the resolved model names, not from this intent.
    """
    preferred = [
        ("openai", settings.preprocess_model),
        ("anthropic", settings.query_planner_model),
        ("gemini", settings.evidence_llm_model),
    ]
    ready = [pair for pair in preferred if llm.provider_ready(pair[0])]
    if len(ready) >= 2:
        # Pass B starts at the second provider and falls back to the first only
        # if every other option fails.
        return ready, ready[1:] + ready[:1]
    return ready, ready


async def _run_pass(
    llm: LLMRouter,
    *,
    attempts: list[tuple[str, str]],
    system: str,
    user: str,
) -> tuple[dict, str]:
    payload, _provider, model = await llm.chat_json_any(
        attempts=attempts,
        system=system,
        user=user,
        temperature=0.0,
    )
    return payload, model


async def _extract_claims(
    payload: InputPayload,
    *,
    settings: Settings,
    llm: LLMRouter,
    emit,
) -> ClaimExtraction:
    """Extract claims once or twice and reconcile by span overlap."""
    attempts_a, attempts_b = _attempt_chains(settings, llm)
    user = _user_prompt(payload)

    if not attempts_a:
        await emit(
            layer="preprocess",
            parameter="claims",
            process="LLM claim extraction",
            tool=settings.preprocess_model,
            status="skipped",
            detail="No LLM provider is configured; using heuristic claims.",
        )
        claims = ground_claims(heuristic_claims(payload.raw_text), payload)
        mark_single_pass(claims, model="heuristic", reason="deterministic sentence fallback")
        return ClaimExtraction(claims, {}, "heuristic", None, False)

    two_passes = settings.claim_passes == 2
    tasks = [_run_pass(llm, attempts=attempts_a, system=PREPROCESS_SYSTEM, user=user)]
    if two_passes:
        tasks.append(_run_pass(llm, attempts=attempts_b, system=PREPROCESS_SYSTEM_B, user=user))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    result_a = results[0]
    result_b = results[1] if len(results) > 1 else None

    if isinstance(result_a, BaseException):
        await emit(
            layer="preprocess",
            parameter="claims",
            process="LLM claim extraction (pass A)",
            tool=settings.preprocess_model,
            status="error",
            detail=short_error(result_a),
        )
        payload_a, model_a = {}, None
    else:
        payload_a, model_a = result_a

    if isinstance(result_b, BaseException):
        await emit(
            layer="preprocess",
            parameter="claims",
            process="LLM claim extraction (pass B)",
            tool="cross-check",
            status="error",
            detail=(
                f"Second pass failed ({short_error(result_b)}); claims are from one pass "
                "only and are not cross-checked."
            ),
        )
        payload_b, model_b = {}, None
    elif result_b is None:
        payload_b, model_b = {}, None
    else:
        payload_b, model_b = result_b

    if model_a is None and model_b is not None:
        # Pass A died but the cross-check pass survived; promote it.
        payload_a, model_a = payload_b, model_b
        payload_b, model_b = {}, None

    if model_a is None:
        claims = ground_claims(heuristic_claims(payload.raw_text), payload)
        mark_single_pass(claims, model="heuristic", reason="deterministic sentence fallback")
        return ClaimExtraction(claims, {}, "heuristic", None, False)

    if model_a != settings.preprocess_model:
        await emit(
            layer="preprocess",
            parameter="claims",
            process="claim extraction failover",
            tool=model_a,
            status="skipped",
            detail=f"{settings.preprocess_model} unavailable; extracted claims with {model_a}.",
        )

    claims_a = _claims_from_llm(payload_a, payload)
    claims_b = _claims_from_llm(payload_b, payload) if model_b else []

    if not claims_a and not claims_b:
        claims = ground_claims(heuristic_claims(payload.raw_text), payload)
        mark_single_pass(claims, model="heuristic", reason="deterministic sentence fallback")
        return ClaimExtraction(claims, payload_a, "heuristic", None, False)

    if model_b is None:
        reason = (
            "single-pass extraction (CLAIM_PASSES=1)"
            if not two_passes
            else "only one extraction pass returned"
        )
        mark_single_pass(claims_a, model=model_a, reason=reason)
        return ClaimExtraction(claims_a, payload_a, model_a, None, False)

    reconciled = reconcile_passes(claims_a, claims_b, model_a=model_a, model_b=model_b)
    independent = model_a != model_b
    if not independent:
        await emit(
            layer="preprocess",
            parameter="claims",
            process="claim cross-check",
            tool=model_a,
            status="skipped",
            detail=(
                f"Both passes ran on {model_a} with differently worded prompts. "
                "Agreement is not an independent cross-check; configure a second "
                "provider for that."
            ),
        )
    return ClaimExtraction(reconciled, payload_a, model_a, model_b, independent)


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


def _claims_from_llm(payload: dict, input_payload: InputPayload) -> list[Claim]:
    """Grounded claims from one pass's JSON. Empty is a valid answer here —
    the heuristic fallback belongs to the caller, which knows whether the
    other pass also came back empty."""
    raw = payload.get("claims") if isinstance(payload, dict) else None
    claims: list[Claim] = []
    if isinstance(raw, list):
        for i, row in enumerate(raw, start=1):
            if not isinstance(row, dict):
                continue
            body = (row.get("text") or "").strip()
            if not body:
                continue
            # The contract asks for `label`; older responses used `kind`.
            label = row.get("label") or row.get("kind")
            kind = label if label in {"fact", "opinion", "unclear"} else "unspecified"
            quote = (row.get("source_quote") or "").strip() or None
            claims.append(
                Claim(
                    id=str(row.get("id") or f"c{i}"),
                    text=body,
                    checkworthy=bool(row.get("checkworthy", True)),
                    kind=kind,
                    source_quote=quote,
                )
            )
    return ground_claims(claims[:8], input_payload)


def ground_claims(claims: list[Claim], input_payload: InputPayload) -> list[Claim]:
    """Locate every claim's quote in raw_text and record where it landed.

    A claim whose quote is not in the article is kept and marked not_found —
    never silently dropped, because a fabricated quote is exactly what the
    journalist needs to see.
    """
    text = input_payload.raw_text
    for claim in claims:
        start, end, grounding = locate_quote(text, claim.source_quote)
        claim.span_start = start
        claim.span_end = end
        claim.grounding = grounding
        claim.claim_source = segment_source_for_span(input_payload.segments, start, end)
    return claims


def heuristic_claims(text: str) -> list[Claim]:
    """Deterministic fallback: long sentences lifted verbatim from the text.

    Offsets come from the original string, so these claims quote the article
    exactly rather than being reconstructed.
    """
    claims: list[Claim] = []
    for match in _SENTENCE.finditer(text or ""):
        raw = match.group(0)
        stripped = raw.strip()
        if len(stripped) <= 40:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        claims.append(
            Claim(
                id=f"c{len(claims) + 1}",
                text=stripped[:400],
                checkworthy=True,
                kind="unspecified",
                source_quote=stripped,
                span_start=start,
                span_end=start + len(stripped),
                grounding="exact",
            )
        )
        if len(claims) == 5:
            break
    if claims:
        return claims
    stripped = (text or "").strip()
    if not stripped:
        return []
    start = text.index(stripped[:1]) if stripped else 0
    quote = stripped[:400]
    return [
        Claim(
            id="c1",
            text=quote,
            checkworthy=True,
            kind="unspecified",
            source_quote=quote,
            span_start=start,
            span_end=start + len(quote),
            grounding="exact",
        )
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
