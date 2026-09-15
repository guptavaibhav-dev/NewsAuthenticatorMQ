from __future__ import annotations

from app.config import Settings
from app.engines.embeddings import EmbeddingEngine
from app.engines.llm_router import LLMRouter
from app.engines.ner import NerEngine
from app.engines.nli import NliEngine
from app.layers.documentation import run_documentation
from app.layers.evidence import run_evidence
from app.layers.preprocess import run_preprocess
from app.layers.uncertainty import run_uncertainty
from app.logutil import get_logger, short_error
from app.retrieval.run import run_retrieval
from app.pipeline.store import RunState
from app.schemas.envelope import RunEnvelope, TraceEvent, utc_now
from app.tools.ingest import ingest_input

log = get_logger("run")

LAYER_IDS = {
    1: "input",
    2: "preprocess",
    3: "verification",
    4: "evidence",
    5: "uncertainty",
    6: "editorial",
    7: "documentation",
}

LAYER_TITLES = {
    1: "Input",
    2: "Pre-processing and Classification",
    # Display only. The layer id stays "verification" in LAYER_IDS, in every
    # trace event, and in the frontend's trace filter.
    3: "Retrieval and Independence",
    4: "Evidence Analysis",
    5: "Uncertainty and Risk Assessment",
    6: "Human Editorial Decision",
    7: "Output and Documentation",
}

LAST_LAYER = 7
EDITORIAL_LAYER = 6


def _emit_factory(state: RunState):
    envelope = state.envelope
    run_id = envelope.run_id[:8]

    async def emit(**kwargs) -> TraceEvent:
        event = TraceEvent(**kwargs)
        envelope.trace.append(event)
        await state.queue.put(event)
        line = (
            f"run {run_id}  [{event.layer}]  {event.process}  "
            f"{event.status}  {event.parameter}"
        )
        if event.tool:
            line += f"  tool={event.tool}"
        if event.detail:
            line += f"  {event.detail}"
        if event.status == "error":
            log.error(line)
        elif event.status in {"skipped", "empty"}:
            log.warning(line)
        else:
            log.info(line)
        return event

    return emit


def restore_snapshot(state: RunState, layer: int) -> None:
    snap = state.snapshots.get(layer)
    if not snap:
        raise ValueError(f"No snapshot for layer {layer}")
    restored = RunEnvelope.model_validate(snap)
    restored.run_id = state.envelope.run_id
    state.envelope = restored


def take_snapshot(state: RunState, layer: int) -> None:
    state.snapshots[layer] = state.envelope.model_dump(mode="json")


async def begin_editorial(state: RunState) -> None:
    envelope = state.envelope
    take_snapshot(state, EDITORIAL_LAYER)
    envelope.current_layer = EDITORIAL_LAYER
    envelope.phase = "awaiting_decision"
    envelope.status = "running"
    envelope.error = None
    emit = _emit_factory(state)
    await emit(
        layer="editorial",
        parameter="human_decision",
        process="await journalist decision",
        tool=None,
        status="running",
        detail="Select an editorial outcome. The system will not auto-commit.",
    )
    state.save()


async def execute_layer(
    state: RunState,
    layer: int,
    *,
    settings: Settings,
    client,
    restore: bool = False,
) -> None:
    if layer < 1 or layer > LAST_LAYER:
        raise ValueError(f"Unknown layer {layer}")
    if layer == EDITORIAL_LAYER:
        await begin_editorial(state)
        return

    if restore:
        restore_snapshot(state, layer)
    take_snapshot(state, layer)

    envelope = state.envelope
    envelope.status = "running"
    envelope.phase = "running_layer"
    envelope.current_layer = layer
    envelope.error = None
    envelope.completed_at = None
    state.save()
    run_id = envelope.run_id[:8]
    emit = _emit_factory(state)

    try:
        if layer == 1:
            await _run_input(state, client=client, emit=emit)
        elif layer == 2:
            await _run_preprocess(envelope, settings=settings, client=client, emit=emit)
        elif layer == 3:
            await _run_verification(envelope, settings=settings, client=client, emit=emit)
        elif layer == 4:
            await _run_evidence(envelope, settings=settings, client=client, emit=emit)
        elif layer == 5:
            envelope.uncertainty = await _run_uncertainty(
                envelope, settings=settings, client=client, emit=emit
            )
        elif layer == 7:
            envelope.record = await _run_documentation(
                envelope, settings=settings, client=client, emit=emit
            )
        else:
            raise ValueError(f"Unknown layer {layer}")

        envelope.completed_layer = layer
        envelope.error = None
        if layer == LAST_LAYER:
            envelope.phase = "complete"
            envelope.status = "complete"
            envelope.completed_at = utc_now()
            log.info(
                "run %s complete risk=%s recommendation=%s",
                run_id,
                envelope.uncertainty.publication_risk,
                envelope.uncertainty.recommended_decision,
            )
            state.done.set()
            await state.queue.put(None)
        else:
            envelope.phase = "awaiting_decision"
            envelope.status = "running"
    except Exception as exc:
        envelope.status = "error"
        envelope.phase = "error"
        envelope.error = str(exc)
        envelope.completed_at = utc_now()
        log.exception("run %s layer %s failed: %s", run_id, layer, short_error(exc))
        await emit(
            layer=LAYER_IDS.get(layer, "pipeline"),
            parameter="run",
            process="orchestrator",
            tool=None,
            status="error",
            detail=str(exc)[:400],
        )
    finally:
        state.save()


async def _run_input(state: RunState, *, client, emit) -> None:
    envelope = state.envelope
    text = state.original_text
    url = state.original_url
    await emit(
        layer="input",
        parameter="text_or_url",
        process="content intake",
        tool="ingest",
        status="running",
        detail="Capturing pasted text and/or fetching article from URL.",
    )
    envelope.input = await ingest_input(client, text=text, url=url)
    if envelope.input.fetch_status == "error":
        log.warning(
            "run %s ingest failed: %s",
            envelope.run_id[:8],
            envelope.input.fetch_error or "unknown fetch error",
        )
    if not envelope.input.raw_text.strip():
        raise ValueError("No article text available. Paste content or provide a reachable URL.")
    await emit(
        layer="input",
        parameter="text_or_url",
        process="content intake",
        tool="ingest",
        status=envelope.input.fetch_status if url else "ok",
        detail=(
            f"title={envelope.input.fetched_title or 'n/a'}; "
            f"domain={envelope.input.publisher_domain or 'n/a'}"
        ),
    )
    envelope.engines_used["input"] = "ingest"


async def _run_preprocess(envelope: RunEnvelope, *, settings: Settings, client, emit) -> None:
    llm = LLMRouter(settings, client)
    ner = NerEngine(settings, client)
    envelope.classification = await run_preprocess(
        envelope, settings=settings, llm=llm, ner=ner, emit=emit
    )
    log.info(
        "run %s preprocess done claims=%s ungrounded=%s agreement=%s entities=%s "
        "passes=%s/%s independent=%s ner=%s",
        envelope.run_id[:8],
        len(envelope.classification.claims),
        envelope.classification.ungrounded_claim_count,
        envelope.classification.claim_agreement_rate,
        len(envelope.classification.entities),
        envelope.classification.pass_a_model,
        envelope.classification.pass_b_model,
        envelope.classification.passes_independent,
        envelope.classification.ner_engine,
    )
    if envelope.classification.ungrounded_claim_count:
        log.warning(
            "run %s %s claim(s) quote text absent from the article; kept and flagged.",
            envelope.run_id[:8],
            envelope.classification.ungrounded_claim_count,
        )


async def _run_verification(envelope: RunEnvelope, *, settings: Settings, client, emit) -> None:
    llm = LLMRouter(settings, client)
    embeddings = EmbeddingEngine(settings, client)
    await run_retrieval(
        envelope,
        settings=settings,
        llm=llm,
        embeddings=embeddings,
        client=client,
        emit=emit,
    )
    retrieval = envelope.retrieval
    for report in retrieval.coverage.adapters if retrieval else []:
        if report.status == "error":
            log.error(
                "run %s adapter %s error: %s", envelope.run_id[:8], report.adapter, report.reason
            )
        elif report.status.startswith("skipped"):
            log.warning(
                "run %s adapter %s %s: %s",
                envelope.run_id[:8],
                report.adapter,
                report.status,
                report.reason,
            )
    if retrieval is None:
        return
    # documents and independent_sources are logged side by side on purpose:
    # the first is a page count inflated by syndication, the second is the only
    # one that speaks to corroboration.
    log.info(
        "run %s retrieval done documents=%s independent_sources=%s existence=%s "
        "ladder=%s ranking=%s",
        envelope.run_id[:8],
        retrieval.document_count,
        retrieval.independent_source_count,
        retrieval.existence_class,
        retrieval.coverage.existence_search,
        retrieval.ranking_method or "unranked",
    )


async def _run_evidence(envelope: RunEnvelope, *, settings: Settings, client, emit) -> None:
    llm = LLMRouter(settings, client)
    nli = NliEngine(settings, client)
    await run_evidence(envelope, settings=settings, nli=nli, llm=llm, emit=emit)
    log.info(
        "run %s evidence done corroboration=%s nli=%s gemini=%s",
        envelope.run_id[:8],
        envelope.corroboration.overall_state,
        envelope.engines_used.get("nli"),
        envelope.engines_used.get("evidence_llm"),
    )


async def _run_uncertainty(envelope: RunEnvelope, *, settings: Settings, client, emit):
    llm = LLMRouter(settings, client)
    return await run_uncertainty(envelope, settings=settings, llm=llm, emit=emit)


async def _run_documentation(envelope: RunEnvelope, *, settings: Settings, client, emit):
    llm = LLMRouter(settings, client)
    return await run_documentation(envelope, settings=settings, llm=llm, emit=emit)
