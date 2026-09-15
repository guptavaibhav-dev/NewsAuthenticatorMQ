"""Layer 3 entry point: plan, retrieve, collapse, and report what we could see.

The order here is deliberate and load-bearing.

Queries are **frozen onto the envelope before a single HTTP request goes out**.
That is what makes a re-run replay the same search instead of quietly
conducting a different one: a journalist who re-runs the layer and gets a
different answer needs to know whether the world changed or our question did.

Adapters then run concurrently. Each one catches its own failures and returns a
report, so `asyncio.gather` is used without `return_exceptions` — if an adapter
ever did raise, that is a contract violation we want surfaced loudly rather than
swallowed into a silent coverage gap. A test asserts the contract directly.

Nothing in this layer decides whether the article is true. It establishes who
else published on the subject, how many of them are genuinely separate
newsrooms, and — just as importantly — which parts of the search we were unable
to perform.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

import httpx

from app.config import Settings
from app.retrieval.adapters import (
    GoogleFactCheckAdapter,
    WikipediaAdapter,
    news_adapters,
)
from app.retrieval.adapters.base import ArticleContext, SourceAdapter, body_hash
from app.retrieval.independence import PlanCoverage, build_coverage_report, build_payload
from app.retrieval.ladder import existence_queries, run_existence_ladder
from app.retrieval.planner import (
    PLANNER_TEMPLATE_VERSION,
    build_queries,
    rephrase_queries,
    select_claims,
)
from app.retrieval.ranking import rank
from app.schemas.envelope import RunEnvelope
from app.schemas.retrieval import (
    AdapterReport,
    AdapterStatus,
    EntityGrounding,
    FactCheckRecord,
    PlannedQuery,
    RetrievalPayload,
    SearchHit,
)

# The trace id stays "verification" even though the layer is now displayed as
# "Retrieval and Independence". The frontend filters trace events on this exact
# string; renaming it would empty the layer's process panel.
TRACE_LAYER = "verification"

# Worst-to-best, for collapsing one adapter's many per-query reports into the
# single report CoverageReport carries.
_STATUS_RANK: dict[AdapterStatus, int] = {
    "ok": 0,
    "empty": 1,
    "error": 2,
    "skipped_no_key": 3,
    "skipped_out_of_range": 4,
}


def article_context(envelope: RunEnvelope) -> ArticleContext:
    """Facts about the SUBMITTED article that adapters gate on.

    Both gate inputs are None today, and both deliberately so:

    `published_at` — nothing on InputPayload carries the article's publication
    date. `fetch_timestamp` is when *we* fetched it, and Layer 2's `date_window`
    describes when the reported events happened, not when the piece ran. Passing
    either would gate adapters on a date the article never claimed. None
    disables the age gate, every adapter is asked, and each one records
    "age check skipped" so the gap is visible rather than assumed away.

    `article_language` — no language detector exists anywhere in the codebase.
    """
    return ArticleContext(
        published_at=None,
        article_language=None,
        canonical_url=envelope.input.canonical_url or "",
        publisher_domain=envelope.input.publisher_domain or "",
        headline=envelope.classification.headline or envelope.input.fetched_title or None,
        body_hash=body_hash(envelope.input.raw_text),
    )


def _stored_plan(envelope: RunEnvelope) -> list[PlannedQuery] | None:
    """The frozen plan from an earlier pass, when one survived.

    A re-run that restores the layer-3 snapshot rewinds `envelope.retrieval` to
    None, so this normally returns None and the plan is rebuilt. That is safe
    because `build_queries` is deterministic over the same restored
    classification — the rebuilt plan is byte-identical. This path covers
    re-execution that did not rewind, where re-planning could otherwise drift
    if an operator has turned the LLM rephrase on.
    """
    existing = envelope.retrieval
    if existing is None or not existing.planned_queries:
        return None
    return [query.model_copy(deep=True) for query in existing.planned_queries]


async def run_retrieval(
    envelope: RunEnvelope,
    *,
    settings: Settings,
    llm: Any,
    embeddings: Any,
    client: httpx.AsyncClient,
    emit,
) -> None:
    classification = envelope.classification
    context = article_context(envelope)
    entities = list(classification.entities or ())

    # Selection is pure and cheap, so it runs even on a replay: its
    # `fields_missing` output is the only record of thin Layer 2 metadata, and
    # the coverage report would otherwise lose it.
    selected, skipped, fields_missing = select_claims(
        classification.claims,
        settings.retrieval_top_k_claims,
        entities=entities,
    )

    replayed = _stored_plan(envelope)
    if replayed is not None:
        queries = replayed
        planner_model = envelope.retrieval.planner_model if envelope.retrieval else None
        await emit(
            layer=TRACE_LAYER,
            parameter="queries",
            process="replay frozen query plan",
            tool="planner",
            status="ok",
            detail=(
                f"Re-running {len(queries)} stored queries verbatim so this run "
                "is comparable with the last one."
            ),
        )
    else:
        await emit(
            layer=TRACE_LAYER,
            parameter="claims",
            process="claim selection and query planning",
            tool="planner",
            status="running",
            detail=(
                f"{len(selected)} of {len(classification.claims)} claims selected "
                f"for search; unselected claims are unsearched, not unsupported."
            ),
        )
        queries = build_queries(classification, envelope.input, selected)
        queries, planner_model = await rephrase_queries(
            queries, settings=settings, llm=llm
        )

    # --- FREEZE. No HTTP request may precede this line. ---------------------
    # Writing the plan onto the envelope before dispatch is what lets a
    # journalist see what was asked even if every adapter then fails, and what
    # makes a re-run auditable rather than merely repeated.
    envelope.retrieval = RetrievalPayload(
        planned_queries=queries,
        planner_model=planner_model,
        planner_template_version=PLANNER_TEMPLATE_VERSION,
    )
    envelope.engines_used["verification_planner"] = planner_model or "deterministic"

    await emit(
        layer=TRACE_LAYER,
        parameter="queries",
        process="claim selection and query planning",
        tool=planner_model or "deterministic",
        status="ok" if queries else "empty",
        detail=(
            f"{len(queries)} queries frozen before dispatch "
            f"({len(existence_queries(queries))} existence, "
            f"{sum(1 for q in queries if q.kind == 'claim')} claim, "
            f"{sum(1 for q in queries if q.kind == 'factcheck')} fact-check, "
            f"{sum(1 for q in queries if q.kind == 'entity')} entity)."
        ),
    )

    adapters = news_adapters(settings)
    factcheck_adapter = GoogleFactCheckAdapter.from_settings(settings)
    wiki_adapter = WikipediaAdapter.from_settings(settings)

    await emit(
        layer=TRACE_LAYER,
        parameter="adapters",
        process="capability-gated retrieval",
        tool="+".join(adapter.name for adapter in adapters),
        status="running",
        detail=(
            "Running every adapter concurrently. An adapter that cannot reach "
            "this article reports a coverage gap, never an absence of coverage."
        ),
    )

    # Four independent workloads, all in flight at once. The old layer awaited
    # five searches in sequence and looked entities up one at a time inside a
    # for loop.
    ladder_result, claim_pack, factcheck_pack, entity_pack = await asyncio.gather(
        run_existence_ladder(
            client,
            queries,
            adapters,
            settings=settings,
            context=context,
        ),
        _search_many(
            client,
            [q for q in queries if q.kind == "claim"],
            adapters,
            settings=settings,
            context=context,
        ),
        _factcheck_many(
            client,
            [q for q in queries if q.kind == "factcheck"],
            factcheck_adapter,
            settings=settings,
            context=context,
        ),
        _search_many(
            client,
            [q for q in queries if q.kind == "entity"],
            [wiki_adapter],
            settings=settings,
            context=context,
        ),
    )

    claim_hits, claim_reports = claim_pack
    factchecks, factcheck_reports = factcheck_pack
    entity_hits, entity_reports = entity_pack

    all_hits = [*ladder_result.hits, *claim_hits, *entity_hits]
    reports = _collapse_reports(
        [*ladder_result.reports, *claim_reports, *factcheck_reports, *entity_reports]
    )

    await emit(
        layer=TRACE_LAYER,
        parameter="existence",
        process="existence ladder",
        tool="+".join(adapter.name for adapter in adapters),
        status="ok" if ladder_result.outcome == "matched" else "empty",
        detail=_ladder_detail(ladder_result),
    )

    ranked = await rank(_documents_only(all_hits, wiki_adapter.name), classification.claims, embeddings)
    envelope.engines_used["embeddings"] = embeddings.engine_name

    grounding = _entity_grounding(entity_hits, queries, entities)

    coverage = build_coverage_report(
        adapter_reports=reports,
        adapters=[*adapters, factcheck_adapter, wiki_adapter],
        context=context,
        ladder=ladder_result,
        plan=PlanCoverage(
            claims_total=len(classification.claims),
            claims_searched=_searched_claim_ids(queries),
            claims_skipped=[
                claim.id
                for claim in skipped
                if claim.id not in set(_searched_claim_ids(queries))
            ],
            fields_missing=fields_missing,
            existence_rungs_planned=len(existence_queries(queries)),
            keyword_rung_skipped=_keyword_rung_skipped(queries, context),
        ),
        scoring_fields_missing=_missing_scoring_fields(ranked.hits),
    )

    payload = build_payload(
        hits=ranked.hits,
        ladder=ladder_result,
        context=context,
        coverage=coverage,
        planned_queries=queries,
        planner_model=planner_model,
        planner_template_version=PLANNER_TEMPLATE_VERSION,
        ranking_method=ranked.ranking_method,
        ranking_engine_name=ranked.ranking_engine_name,
        factchecks=factchecks,
        entity_grounding=grounding,
    )
    envelope.retrieval = payload
    record_tool_results(envelope, payload)

    await emit(
        layer=TRACE_LAYER,
        parameter="independence",
        process="dedupe, ownership and wire collapsing",
        tool="independence",
        status="ok" if payload.documents else "empty",
        detail=(
            f"{payload.document_count} distinct pages collapse to "
            f"{payload.independent_source_count} independent source(s). "
            "Page count is inflated by syndication; only the source count "
            "speaks to corroboration."
        ),
    )

    await emit(
        layer=TRACE_LAYER,
        parameter="existence",
        process="same-article vs type-coverage classification",
        tool="embeddings",
        status="ok" if payload.documents else "empty",
        detail=(
            f"{payload.existence_class}; {payload.document_count} documents, "
            f"{payload.independent_source_count} independent sources."
        ),
    )


async def _search_many(
    client: httpx.AsyncClient,
    queries: list[PlannedQuery],
    adapters: list[SourceAdapter],
    *,
    settings: Settings,
    context: ArticleContext,
) -> tuple[list[SearchHit], list[AdapterReport]]:
    """Every query against every adapter, all at once.

    `return_exceptions` is deliberately left at its default. Adapters are
    contracted to catch their own failures and return `status=error`; if one
    ever raises, that bug should stop the layer loudly rather than disappear
    into what would look like a source with nothing to say.
    """
    if not queries or not adapters:
        return [], []
    outcomes = await asyncio.gather(
        *(
            adapter.search(client, query, settings=settings, context=context)
            for query in queries
            for adapter in adapters
        )
    )
    hits: list[SearchHit] = []
    reports: list[AdapterReport] = []
    for found, report in outcomes:
        hits.extend(found)
        reports.append(report)
    return hits, reports


async def _factcheck_many(
    client: httpx.AsyncClient,
    queries: list[PlannedQuery],
    adapter: GoogleFactCheckAdapter,
    *,
    settings: Settings,
    context: ArticleContext,
) -> tuple[list[FactCheckRecord], list[AdapterReport]]:
    if not queries:
        return [], []
    outcomes = await asyncio.gather(
        *(
            adapter.search_records(client, query, settings=settings, context=context)
            for query in queries
        )
    )
    records: list[FactCheckRecord] = []
    reports: list[AdapterReport] = []
    for found, report in outcomes:
        records.extend(found)
        reports.append(report)
    return records, reports


def _documents_only(hits: Iterable[SearchHit], wiki_name: str) -> list[SearchHit]:
    """Drop reference-work lookups from the document set.

    A Wikipedia page is not coverage of the story; counting one as a retrieved
    document would inflate `document_count` with something no newsroom
    published. Entity lookups are reported through `entity_grounding` instead.
    """
    return [hit for hit in hits if hit.source_adapter != wiki_name]


def _collapse_reports(reports: list[AdapterReport]) -> list[AdapterReport]:
    """One report per adapter, however many queries it ran.

    A skip survives only when every query was skipped: an adapter that was
    gated out for one query but ran for another did not have a coverage gap.
    """
    merged: dict[str, AdapterReport] = {}
    for report in reports:
        current = merged.get(report.adapter)
        if current is None:
            merged[report.adapter] = report.model_copy(deep=True)
            continue
        current.queries_run += report.queries_run
        current.hits_returned += report.hits_returned
        if _STATUS_RANK.get(report.status, 9) < _STATUS_RANK.get(current.status, 9):
            current.status = report.status
        current.http_status = current.http_status or report.http_status
        for name in report.checks_skipped:
            if name not in current.checks_skipped:
                current.checks_skipped.append(name)
        if report.reason and report.reason != current.reason:
            current.reason = report.reason if not current.reason else current.reason
    return list(merged.values())


def _ladder_detail(ladder) -> str:
    if ladder.outcome == "not_planned":
        return (
            "No headline was available, so no existence search was planned. "
            "We did not look; this is not a finding about the article."
        )
    if ladder.outcome == "matched":
        return (
            f"Found at title strength '{ladder.title_match_strength}' after "
            f"{len(ladder.attempts_run)} attempt(s)."
        )
    return (
        f"All {len(ladder.attempts_run)} attempt(s) ran and returned nothing. "
        "An open question, not evidence the story is false."
    )


def _searched_claim_ids(queries: Iterable[PlannedQuery]) -> list[str]:
    seen: list[str] = []
    for query in queries:
        if query.kind in {"claim", "factcheck"} and query.claim_id:
            if query.claim_id not in seen:
                seen.append(query.claim_id)
    return seen


def _keyword_rung_skipped(queries: Iterable[PlannedQuery], context: ArticleContext) -> bool:
    """True when a headline existed but yielded no distinctive keyword rung."""
    rungs = existence_queries(queries)
    if not rungs:
        return False
    return not any(query.template_id == "exist_keyword" for query in rungs)


def _missing_scoring_fields(hits: Iterable[SearchHit]) -> list[str]:
    """Fields later layers want that retrieval could not fill for every hit."""
    rows = list(hits)
    if not rows:
        return []
    missing: list[str] = []
    if not all(hit.published_at for hit in rows):
        missing.append("published_at")
    if not all(hit.body_hash for hit in rows):
        missing.append("body_hash")
    if not all(hit.snippet for hit in rows):
        missing.append("snippet")
    return missing


def _entity_grounding(
    hits: list[SearchHit],
    queries: Iterable[PlannedQuery],
    entities: list[Any],
) -> list[EntityGrounding]:
    """One record per entity we looked up, found or not.

    An entity with no reference-work entry is obscure, new, or spelled
    differently. It is never evidence of invention, and nothing downstream may
    score it as such.
    """
    types = {
        str(getattr(entity, "text", "")).strip().lower(): getattr(entity, "type", "")
        for entity in entities
    }
    by_query: dict[str, list[SearchHit]] = {}
    for hit in hits:
        by_query.setdefault(hit.query_id, []).append(hit)

    rows: list[EntityGrounding] = []
    for query in queries:
        if query.kind != "entity":
            continue
        found = by_query.get(query.query_id) or []
        rows.append(
            EntityGrounding(
                entity_text=query.query_text,
                entity_type=str(types.get(query.query_text.strip().lower(), "")),
                entity_is_well_known=bool(found),
                matched_title=found[0].title if found else None,
            )
        )
    return rows


def evidence_source_id(index: int) -> str:
    return f"s{index + 1}"


def record_tool_results(envelope: RunEnvelope, payload: RetrievalPayload) -> None:
    """Copy adapter reports onto envelope.tool_results.

    tool_results is a pipeline-wide field that Ask exposes from layer 1
    onward, so Layer 3 writes it but does not own it. Statuses are projected
    onto the coarser ToolStatus enum (ok/empty/error/skipped). That is a
    granularity loss on *tool* status, not the existence-class conflation:
    skipped_out_of_range and skipped_no_key both become skipped here, while
    envelope.retrieval.coverage.adapters keeps them distinct, and
    existence_class is never written to this list.
    """
    from app.schemas.envelope import ToolResult

    status_map = {
        "ok": "ok",
        "empty": "empty",
        "error": "error",
        "skipped_no_key": "skipped",
        "skipped_out_of_range": "skipped",
    }
    envelope.tool_results = [
        ToolResult(
            tool=report.adapter,
            status=status_map.get(report.status, "skipped"),
            detail=report.reason or "",
            hit_count=report.hits_returned,
        )
        for report in payload.coverage.adapters
    ]
