from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import APP_USER_AGENT, get_settings
from app.pipeline.orchestrator import execute_run
from app.pipeline.store import RunStore
from app.schemas.envelope import DecisionRequest, HumanDecision, RunEnvelope, RunRequest, utc_now

store = RunStore()
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global http_client
    settings = get_settings()
    http_client = httpx.AsyncClient(
        timeout=settings.http_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": APP_USER_AGENT},
    )
    yield
    await http_client.aclose()
    http_client = None


app = FastAPI(title="NewsAuth", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "ok": True,
        "providers": {
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "gemini": bool(settings.gemini_key),
            "newsapi": bool(settings.newsapi_key),
            "guardian": bool(settings.guardian_api_key),
            "gnews": bool(settings.gnews_api_key or settings.newsdata_api_key),
            "factcheck": bool(settings.factcheck_key),
            "huggingface": bool(settings.hf_token),
        },
        "models": {
            "preprocess": settings.preprocess_model,
            "query_planner": settings.query_planner_model,
            "evidence_llm": settings.evidence_llm_model,
            "uncertainty": settings.uncertainty_model,
            "documentation": settings.documentation_model,
            "nli": settings.nli_model,
        },
    }


@app.post("/api/runs")
async def create_run(body: RunRequest) -> dict:
    if not body.text.strip() and not body.url.strip():
        raise HTTPException(400, "Provide article text, a URL, or both.")
    settings = get_settings()
    assert http_client is not None
    run_id = str(uuid.uuid4())
    envelope = RunEnvelope(run_id=run_id, status="queued")
    state = store.create(envelope)
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
    return state.envelope


def _sse(payload: dict) -> str:
    import json

    return f"data: {json.dumps(payload, default=str)}\n\n"
