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
from app.layers.verification import run_verification
from app.pipeline.store import RunState
from app.schemas.envelope import TraceEvent, utc_now
from app.tools.ingest import ingest_input
from app.tools.media import inspect_media


async def execute_run(
    state: RunState,
    *,
    settings: Settings,
    client,
    text: str,
    url: str,
) -> None:
    envelope = state.envelope
    envelope.status = "running"

    async def emit(**kwargs) -> TraceEvent:
        event = TraceEvent(**kwargs)
        envelope.trace.append(event)
        await state.queue.put(event)
        return event

    try:
        await emit(
            layer="input",
            parameter="text_or_url",
            process="content intake",
            tool="ingest",
            status="running",
            detail="Capturing pasted text and/or fetching article from URL.",
        )
        envelope.input = await ingest_input(client, text=text, url=url)
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

        media = await inspect_media(envelope.input)
        envelope.tool_results.append(media)

        llm = LLMRouter(settings, client)
        ner = NerEngine(settings, client)
        embeddings = EmbeddingEngine(settings, client)
        nli = NliEngine(settings, client)

        envelope.classification = await run_preprocess(
            envelope, settings=settings, llm=llm, ner=ner, emit=emit
        )
        await run_verification(
            envelope,
            settings=settings,
            llm=llm,
            embeddings=embeddings,
            client=client,
            emit=emit,
        )
        await run_evidence(
            envelope, settings=settings, nli=nli, llm=llm, emit=emit
        )
        envelope.uncertainty = await run_uncertainty(
            envelope, settings=settings, llm=llm, emit=emit
        )
        envelope.record = await run_documentation(
            envelope, settings=settings, llm=llm, emit=emit
        )

        envelope.status = "complete"
        envelope.completed_at = utc_now()
        await emit(
            layer="editorial",
            parameter="human_decision",
            process="await journalist decision",
            tool=None,
            status="ok",
            detail="Pipeline complete. Select an editorial outcome; the system will not auto-commit.",
        )
    except Exception as exc:
        envelope.status = "error"
        envelope.error = str(exc)
        envelope.completed_at = utc_now()
        await emit(
            layer="pipeline",
            parameter="run",
            process="orchestrator",
            tool=None,
            status="error",
            detail=str(exc)[:400],
        )
    finally:
        await state.queue.put(None)
        state.done.set()
