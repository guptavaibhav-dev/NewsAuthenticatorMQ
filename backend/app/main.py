from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import APP_USER_AGENT, get_settings
from app.health import build_health
from app.logutil import get_logger, redact_url, setup_logging
from app.pipeline.ask import answer_question
from app.pipeline.orchestrator import (
    EDITORIAL_LAYER,
    LAST_LAYER,
    _emit_factory,
    begin_editorial,
    execute_layer,
)
from app.pipeline.store import RunState, RunStore
from app.schemas.envelope import (
    AskRequest,
    DecisionRequest,
    HumanDecision,
    RunEnvelope,
    RunRequest,
    StepRequest,
    utc_now,
)

store = RunStore()
http_client: httpx.AsyncClient | None = None
log = get_logger("api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global http_client
    settings = get_settings()
    setup_logging(settings.log_level)
    log.info("NewsAuth API starting (log_level=%s)", settings.log_level)

    async def on_request(request: httpx.Request) -> None:
        get_logger("http").debug("%s %s", request.method, redact_url(str(request.url)))

    async def on_response(response: httpx.Response) -> None:
        url = redact_url(str(response.request.url))
        if response.status_code >= 400:
            get_logger("http").warning(
                "%s %s -> %s", response.request.method, url, response.status_code
            )
        else:
            get_logger("http").debug(
                "%s %s -> %s", response.request.method, url, response.status_code
            )

    http_client = httpx.AsyncClient(
        timeout=settings.http_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": APP_USER_AGENT},
        event_hooks={"request": [on_request], "response": [on_response]},
    )
    log.info("HTTP client ready")
    yield
    await http_client.aclose()
    http_client = None
    log.info("NewsAuth API stopped")


app = FastAPI(title="NewsAuth", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "NewsAuth API",
        "dashboard": "http://localhost:5173",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health(probe: bool = False):
    get_settings.cache_clear()
    settings = get_settings()
    log.info("GET /api/health probe=%s", probe)
    result = await build_health(settings, http_client, probe=probe)
    summary = result.get("summary") or {}
    log.info(
        "health done keys=%s/%s working layers_ready=%s/%s",
        summary.get("keys_working"),
        summary.get("keys_total"),
        summary.get("layers_ready"),
        summary.get("layers_total"),
    )
    return result


@app.post("/api/runs")
async def create_run(body: RunRequest) -> dict:
    if not body.text.strip() and not body.url.strip():
        log.warning("POST /api/runs rejected: empty text and url")
        raise HTTPException(400, "Provide article text, a URL, or both.")
    settings = get_settings()
    assert http_client is not None
    run_id = str(uuid.uuid4())
    envelope = RunEnvelope(run_id=run_id, status="queued")
    state = store.create(envelope, text=body.text, url=body.url)
    log.info(
        "run %s queued url=%s text_chars=%s",
        run_id[:8],
        body.url or "-",
        len(body.text.strip()),
    )
    await _run_exclusive(state, layer=1, restore=False, settings=settings)
    return _step_payload(state, layer=1)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> RunEnvelope:
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")
    return state.envelope


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str):
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")

    async def gen():
        seen = 0
        while True:
            trace = state.envelope.trace
            while seen < len(trace):
                yield _sse(trace[seen].model_dump())
                seen += 1
            finished = state.envelope.phase == "complete" and not state.busy
            if finished and seen >= len(state.envelope.trace):
                yield _sse({"type": "complete", "status": state.envelope.status})
                break
            try:
                await asyncio.wait_for(state.queue.get(), timeout=0.4)
            except TimeoutError:
                continue

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/step")
async def step_run(run_id: str, body: StepRequest) -> dict:
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")
    settings = get_settings()
    envelope = state.envelope

    if body.action == "rerun":
        layer = envelope.current_layer
        if layer is None:
            raise HTTPException(409, "No layer to re-run")
        if layer == EDITORIAL_LAYER:
            raise HTTPException(409, "Editorial decision cannot be generated by the system")
        if envelope.phase not in {"awaiting_decision", "error", "complete"}:
            raise HTTPException(409, "Cannot re-run while a layer is executing")
        await _run_exclusive(state, layer=layer, restore=True, settings=settings)
        return _step_payload(state, layer=layer)

    if envelope.phase == "running_layer" or state.busy:
        raise HTTPException(409, "A layer is already running")
    if envelope.phase == "error":
        raise HTTPException(409, "Repair the failed layer before proceeding")
    if envelope.phase == "complete":
        raise HTTPException(409, "Run is already complete")

    current = envelope.current_layer or 0
    if envelope.phase == "idle" and current == 0:
        next_layer = 1
    elif envelope.phase == "awaiting_decision":
        if current == EDITORIAL_LAYER:
            raise HTTPException(409, "Submit an editorial decision to continue")
        if current >= LAST_LAYER:
            raise HTTPException(409, "Run is already complete")
        next_layer = current + 1
    else:
        raise HTTPException(409, "Run is not waiting for a decision")

    if next_layer == EDITORIAL_LAYER:
        await _exclusive_start(state)
        try:
            await begin_editorial(state)
        finally:
            state.busy = False
            state.save()
        return _step_payload(state, layer=EDITORIAL_LAYER)

    await _run_exclusive(state, layer=next_layer, restore=False, settings=settings)
    return _step_payload(state, layer=next_layer)


@app.post("/api/runs/{run_id}/ask")
async def ask_run(run_id: str, body: AskRequest) -> dict:
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Question is empty")
    if state.busy or state.envelope.phase == "running_layer":
        raise HTTPException(409, "A layer is running")
    layer = body.layer
    current = state.envelope.current_layer
    if current is None:
        raise HTTPException(409, "No active layer")
    if layer != current:
        raise HTTPException(409, "Questions must target the current layer")
    if layer < 1 or layer > LAST_LAYER:
        raise HTTPException(400, "Unknown layer")
    settings = get_settings()
    assert http_client is not None
    try:
        answer = await answer_question(
            state.envelope,
            layer=layer,
            question=question,
            settings=settings,
            client=http_client,
        )
    except Exception as exc:
        log.exception("run %s ask failed: %s", run_id[:8], exc)
        raise HTTPException(502, "Could not answer the question") from exc
    return {"layer": layer, "answer": answer}


@app.post("/api/runs/{run_id}/decision")
async def set_decision(run_id: str, body: DecisionRequest) -> dict:
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")
    envelope = state.envelope
    if envelope.current_layer != EDITORIAL_LAYER or envelope.phase != "awaiting_decision":
        raise HTTPException(409, "Run is not awaiting an editorial decision")
    settings = get_settings()
    await _exclusive_start(state)
    try:
        envelope.human_decision = HumanDecision(
            decision=body.decision,
            notes=body.notes,
            decided_at=utc_now(),
        )
        envelope.completed_layer = EDITORIAL_LAYER
        log.info("run %s editorial decision=%s", run_id[:8], body.decision)
        emit = _emit_factory(state)
        await emit(
            layer="editorial",
            parameter="human_decision",
            process="journalist decision recorded",
            tool=None,
            status="ok",
            detail=f"Recorded {body.decision}; not an authenticity verdict.",
        )
        await execute_layer(
            state, LAST_LAYER, settings=settings, client=http_client, restore=False
        )
    finally:
        state.busy = False
        state.save()
    return _step_payload(state, layer=state.envelope.current_layer or LAST_LAYER)


def _step_payload(state: RunState, layer: int) -> dict:
    envelope = state.envelope
    next_layer = None
    if envelope.phase == "awaiting_decision" and envelope.current_layer:
        if envelope.current_layer == EDITORIAL_LAYER:
            next_layer = LAST_LAYER
        elif envelope.current_layer < LAST_LAYER:
            next_layer = envelope.current_layer + 1
    return {
        "run_id": envelope.run_id,
        "layer": layer,
        "next_layer": next_layer,
        "envelope": envelope,
    }


async def _exclusive_start(state: RunState) -> None:
    async with state.lock:
        if state.busy:
            raise HTTPException(409, "A layer is already running")
        state.busy = True


async def _run_exclusive(
    state: RunState,
    *,
    layer: int,
    restore: bool,
    settings,
) -> None:
    await _exclusive_start(state)
    try:
        assert http_client is not None
        await execute_layer(
            state,
            layer,
            settings=settings,
            client=http_client,
            restore=restore,
        )
    finally:
        state.busy = False
        state.save()


def _sse(payload: dict) -> str:
    import json

    return f"data: {json.dumps(payload, default=str)}\n\n"
