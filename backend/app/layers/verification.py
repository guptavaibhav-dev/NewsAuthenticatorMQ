from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.config import Settings
from app.engines.embeddings import EmbeddingEngine, token_jaccard
from app.engines.llm_router import LLMRouter
from app.logutil import short_error
from app.schemas.envelope import (
    EvidenceItem,
    ExistenceResult,
    RunEnvelope,
    SearchQueries,
    WikiHit,
)
from app.scoring.urls import canonical_url, normalize_title
from app.scoring.source_independence import publisher_family
from app.tools.factcheck import search_factchecks
from app.tools.gnews import search_second_aggregator
from app.tools.guardian import search_guardian
from app.tools.newsapi import search_newsapi
from app.tools.wikipedia import search_wikipedia

PLANNER_SYSTEM = """You are the query planner for the Verification Tool Layer.
You do not judge whether the news is true or false. You only produce search queries.
Return JSON with:
quoted_headline (string, the headline or main claim in quotes without the quote characters),
event_boolean (NewsAPI-style boolean query using AND/OR, entities and event nouns),
date_from (YYYY-MM-DD or null),
date_to (YYYY-MM-DD or null),
entity_queries (array of 1-5 entity strings for Wikipedia),
factcheck_query (short paraphrase of the main check-worthy claim).
Keep event_boolean under 180 characters.
"""


async def run_verification(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    llm: LLMRouter,
    embeddings: EmbeddingEngine,
    client,
    emit,
) -> None:
    queries = await plan_queries(envelope, settings=settings, llm=llm, emit=emit)
    envelope.queries = queries

    quoted = queries.quoted_headline or envelope.classification.headline or ""
    event_q = queries.event_boolean or quoted

    await emit(
        layer="verification",
        parameter="headline",
        process="quoted title search",
        tool="newsapi+guardian",
        status="running",
        detail=f'Looking for the same article via quoted title: "{quoted[:80]}"',
    )

    title_news, title_news_res = await search_newsapi(
        client,
        settings,
        query=f'"{quoted}"' if quoted else event_q,
        date_from=queries.date_from,
        date_to=queries.date_to,
        search_in="title",
        page_size=8,
        id_prefix="newsapi-title",
    )
    title_guard, title_guard_res = await search_guardian(
        client,
        settings,
        query=quoted or event_q,
        date_from=queries.date_from,
        date_to=queries.date_to,
        page_size=5,
        include_body=False,
        id_prefix="guardian-title",
    )

    await emit(
        layer="verification",
        parameter="claims+entities",
        process="event / type coverage search",
        tool="newsapi+guardian+aggregator",
        status="running",
        detail=f"Boolean event query: {event_q[:160]}",
    )

    event_news, event_news_res = await search_newsapi(
        client,
        settings,
        query=event_q,
        date_from=queries.date_from,
        date_to=queries.date_to,
        page_size=10,
        id_prefix="newsapi-event",
    )
    event_guard, event_guard_res = await search_guardian(
        client,
        settings,
        query=event_q,
        date_from=queries.date_from,
        date_to=queries.date_to,
        page_size=8,
        include_body=True,
        id_prefix="guardian-event",
    )
    event_agg, event_agg_res = await search_second_aggregator(
        client,
        settings,
        query=event_q,
        date_from=queries.date_from,
        date_to=queries.date_to,
    )

    fact_q = queries.factcheck_query or (envelope.classification.claims[0].text if envelope.classification.claims else quoted)
    await emit(
        layer="verification",
        parameter="claim",
        process="prior ClaimReview search",
        tool="google-factcheck",
        status="running",
        detail=f"Fact-check query: {fact_q[:160]}",
    )
    fact_items, fact_res = await search_factchecks(client, settings, query=fact_q)

    wiki_hits: list[WikiHit] = []
    wiki_results = []
    entity_queries = queries.entity_queries or [
        e.text for e in envelope.classification.entities if e.type in {"PERSON", "ORG", "GPE"}
    ][:5]
    for eq in entity_queries:
        await emit(
            layer="verification",
            parameter=f"entities.{eq}",
            process="Wikipedia / Wikidata grounding",
            tool="wikipedia",
            status="running",
            detail=f"Checking whether entity '{eq}' is grounded in public knowledge bases.",
        )
        hit, tres = await search_wikipedia(client, query=eq)
        wiki_hits.append(hit)
        wiki_results.append(tres)
        await emit(
            layer="verification",
            parameter=f"entities.{eq}",
            process="Wikipedia / Wikidata grounding",
            tool="wikipedia",
            status=tres.status,
            detail=hit.title or tres.detail or "no page",
        )

    merged = _dedupe(
        title_news + title_guard + event_news + event_guard + event_agg
    )
    ranked = await _rank(merged, envelope, embeddings, settings.max_evidence_items)
    existence = await classify_existence(envelope, ranked, embeddings)

    envelope.evidence_items = ranked
    envelope.wiki_hits = wiki_hits
    envelope.corroboration.existence = existence
    envelope.corroboration.fact_checks = fact_items
    envelope.tool_results.extend(
        [
            title_news_res,
            title_guard_res,
            event_news_res,
            event_guard_res,
            event_agg_res,
            fact_res,
            *wiki_results,
        ]
    )
    envelope.engines_used["verification_planner"] = queries.planner_model or "deterministic"
    envelope.engines_used["embeddings"] = embeddings.engine_name

    await emit(
        layer="verification",
        parameter="existence",
        process="same-article vs type-coverage classification",
        tool="embeddings",
        status="ok" if ranked else "empty",
        detail=f"{existence.existence_class}; {len(ranked)} unique evidence items kept.",
    )


async def plan_queries(envelope, *, settings: Settings, llm: LLMRouter, emit) -> SearchQueries:
    fallback = deterministic_queries(envelope)
    attempts = [
        ("anthropic", settings.query_planner_model),
        ("gemini", settings.evidence_llm_model),
        ("openai", settings.uncertainty_model),
    ]
    if not any(llm.provider_ready(p) for p, _ in attempts):
        await emit(
            layer="verification",
            parameter="queries",
            process="query planner",
            tool=settings.query_planner_model,
            status="skipped",
            detail="No LLM provider is configured; using deterministic queries.",
        )
        fallback.planner_mode = "deterministic"
        return fallback

    user = _planner_user(envelope, fallback)
    try:
        data, provider, model = await llm.chat_json_any(
            attempts=attempts,
            system=PLANNER_SYSTEM,
            user=user,
        )
        queries = SearchQueries(
            quoted_headline=data.get("quoted_headline") or fallback.quoted_headline,
            event_boolean=data.get("event_boolean") or fallback.event_boolean,
            date_from=data.get("date_from") or fallback.date_from,
            date_to=data.get("date_to") or fallback.date_to,
            entity_queries=data.get("entity_queries") or fallback.entity_queries,
            factcheck_query=data.get("factcheck_query") or fallback.factcheck_query,
            planner_model=model,
            planner_mode="llm",
        )
        await emit(
            layer="verification",
            parameter="queries",
            process="query planner",
            tool=model,
            status="ok",
            detail=f"Search queries produced by {provider}/{model}; planner did not score truth.",
        )
        return queries
    except Exception as exc:
        await emit(
            layer="verification",
            parameter="queries",
            process="query planner",
            tool=settings.query_planner_model,
            status="skipped",
            detail=f"{short_error(exc)}; falling back to deterministic queries.",
        )
        fallback.planner_mode = "deterministic"
        return fallback


_QUERY_STOP = {
    "the", "a", "an", "this", "that", "these", "those", "and", "but", "for",
    "president", "minister", "sacked", "tells", "said", "should", "asked",
    "about", "what", "knew", "from", "with", "after", "last", "month", "week",
}

_EVENT_HINTS = (
    "corruption", "ukraine", "zelensky", "zelenskyy", "fedorov", "federov",
    "minister", "investigation", "defence", "defense", "drone",
)


def _short_search_name(text: str) -> str | None:
    parts = [p for p in text.replace(",", " ").split() if p]
    if not parts:
        return None
    token = parts[-1].strip(".,;:\"'")
    if len(token) < 4 or token.lower() in _QUERY_STOP:
        return None
    return token


def deterministic_queries(envelope: RunEnvelope) -> SearchQueries:
    headline = (envelope.classification.headline or envelope.input.fetched_title or "").strip()
    if len(headline) > 90:
        cut = headline[:90]
        headline = cut.rsplit(" ", 1)[0] if " " in cut else cut
    claim = envelope.classification.claims[0].text if envelope.classification.claims else headline
    people = [
        e.text
        for e in envelope.classification.entities
        if e.type in {"PERSON", "ORG"} and len(e.text) > 2
    ]
    places = [
        e.text
        for e in envelope.classification.entities
        if e.type == "GPE" and len(e.text) > 3 and e.text.lower() not in _QUERY_STOP
    ]
    names = []
    for raw in people or _proper_nouns(claim + " " + headline):
        short = _short_search_name(raw)
        if short and short not in names:
            names.append(short)
    places_short = []
    for raw in places:
        short = _short_search_name(raw)
        if short and short not in places_short and short not in names:
            places_short.append(short)
    haystack = f"{headline} {claim}".lower()
    hints = [h.title() if h != "ukraine" else "Ukraine" for h in _EVENT_HINTS if h in haystack]
    parts: list[str] = []
    if names:
        parts.append("(" + " OR ".join(names[:3]) + ")")
    if places_short:
        parts.append(places_short[0])
    elif "Ukraine" in hints:
        parts.append("Ukraine")
    if hints:
        extra = next((h for h in hints if h.lower() not in {n.lower() for n in names} and h != "Ukraine"), None)
        if extra:
            parts.append(extra)
    event_boolean = " AND ".join(parts) if parts else (headline or claim)[:80]
    window = envelope.classification.date_window
    start, end = window.start, window.end
    if not start:
        recent = datetime.utcnow()
        start = (recent - timedelta(days=30)).date().isoformat()
        end = recent.date().isoformat()
    entities = (people + places_short)[:5] or names[:5]
    quoted = headline.strip('"')
    if len(quoted) > 90:
        quoted = quoted[:90].rsplit(" ", 1)[0]
    return SearchQueries(
        quoted_headline=quoted,
        event_boolean=event_boolean[:160],
        date_from=start,
        date_to=end,
        entity_queries=entities,
        factcheck_query=(claim[:120] if claim else quoted),
        planner_model="deterministic",
        planner_mode="deterministic",
    )


def _proper_nouns(text: str) -> list[str]:
    found = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b", text or "")
    return [item for item in found if item.lower() not in _QUERY_STOP][:6]


def _planner_user(envelope: RunEnvelope, fallback: SearchQueries) -> str:
    claims = "\n".join(f"- {c.id}: {c.text}" for c in envelope.classification.claims)
    ents = ", ".join(f"{e.text} ({e.type})" for e in envelope.classification.entities)
    return (
        f"HEADLINE: {envelope.classification.headline}\n"
        f"CONTENT TYPE: {envelope.classification.content_type}\n"
        f"DATE WINDOW: {envelope.classification.date_window.model_dump()}\n"
        f"ENTITIES: {ents}\nCLAIMS:\n{claims}\n"
        f"DETERMINISTIC FALLBACK (edit if needed): {fallback.model_dump_json()}"
    )


def _dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    out: list[EvidenceItem] = []
    for item in items:
        key = canonical_url(item.url) if item.url else item.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def _rank(
    items: list[EvidenceItem],
    envelope: RunEnvelope,
    embeddings: EmbeddingEngine,
    limit: int,
) -> list[EvidenceItem]:
    if not items:
        return []
    claim_text = " ".join(c.text for c in envelope.classification.claims[:3]) or envelope.input.raw_text[:500]
    scored: list[EvidenceItem] = []
    for item in items:
        target = f"{item.title} {item.snippet}"
        try:
            sim = await embeddings.similarity(claim_text, target)
        except Exception:
            sim = token_jaccard(claim_text, target)
        item.similarity = sim
        scored.append(item)
    scored.sort(key=lambda x: x.similarity or 0, reverse=True)
    relevant = [
        item
        for item in scored
        if (item.similarity or 0) >= 0.22
        or token_jaccard(claim_text, f"{item.title} {item.snippet}") >= 0.08
    ]
    if not relevant:
        relevant = []
    families_seen: set[str] = set()
    preferred: list[EvidenceItem] = []
    rest: list[EvidenceItem] = []
    for item in relevant:
        fam = item.publisher_family or publisher_family(item.url)
        if fam not in families_seen:
            families_seen.add(fam)
            preferred.append(item)
        else:
            rest.append(item)
    return (preferred + rest)[:limit]


async def classify_existence(
    envelope: RunEnvelope,
    items: list[EvidenceItem],
    embeddings: EmbeddingEngine,
) -> ExistenceResult:
    input_url = envelope.input.canonical_url
    input_title = envelope.classification.headline or envelope.input.fetched_title or ""
    input_domain = envelope.input.publisher_domain
    snippet = (envelope.input.raw_text or "")[:400]
    probe = f"{input_title} {snippet}".strip()

    if input_url:
        for item in items:
            if canonical_url(item.url) == canonical_url(input_url):
                return ExistenceResult(
                    existence_class="exact_url_match",
                    matched_url=item.url,
                    matched_title=item.title,
                    similarity=1.0,
                    notes="Canonical URL matched a retrieved article.",
                )

    best: ExistenceResult | None = None
    for item in items:
        title_score = token_jaccard(input_title, item.title) if input_title else 0.0
        try:
            near = await embeddings.similarity(probe, f"{item.title} {item.snippet[:400]}")
        except Exception:
            near = title_score
        same_family = (
            input_domain
            and publisher_family(input_domain) == (item.publisher_family or publisher_family(item.url))
        )
        if input_title and normalize_title(input_title) == normalize_title(item.title):
            return ExistenceResult(
                existence_class="title_match",
                matched_url=item.url,
                matched_title=item.title,
                similarity=max(near, title_score),
                notes="Normalised titles match.",
            )
        if near >= 0.88:
            klass = "near_duplicate" if same_family else "syndicated_or_reprint"
            candidate = ExistenceResult(
                existence_class=klass,
                matched_url=item.url,
                matched_title=item.title,
                similarity=near,
                notes="Embedding cosine ≥ 0.88 against title+lead.",
            )
            if best is None or (candidate.similarity or 0) > (best.similarity or 0):
                best = candidate
    return best or ExistenceResult(
        existence_class="not_found",
        notes="No same-article match. This is not evidence of fabrication.",
    )
