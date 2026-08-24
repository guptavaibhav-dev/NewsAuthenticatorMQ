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
from app.pipeline.orchestrator import execute_run
from app.pipeline.store import RunStore
from app.schemas.envelope import DecisionRequest, HumanDecision, RunEnvelope, RunRequest, utc_now

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
    state = store.create(envelope)
    log.info(
        "run %s queued url=%s text_chars=%s",
        run_id[:8],
        body.url or "-",
        len(body.text.strip()),
    )
    asyncio.create_task(
        execute_run(
            state,
            settings=settings,
            client=http_client,
            text=body.text,
            url=body.url,
        )
    )
    return {"run_id": run_id}


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
            if state.done.is_set() and seen >= len(state.envelope.trace):
                yield _sse({"type": "complete", "status": state.envelope.status})
                break
            try:
                await asyncio.wait_for(state.queue.get(), timeout=0.4)
            except TimeoutError:
                continue

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/decision")
async def set_decision(run_id: str, body: DecisionRequest) -> RunEnvelope:
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "Unknown run")
    if state.envelope.status != "complete":
        raise HTTPException(409, "Run is not complete")
    state.envelope.human_decision = HumanDecision(
        decision=body.decision,
        notes=body.notes,
        decided_at=utc_now(),
    )
    log.info("run %s editorial decision=%s", run_id[:8], body.decision)
    return state.envelope


def _sse(payload: dict) -> str:
    import json

    return f"data: {json.dumps(payload, default=str)}\n\n"
