from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.envelope import RunEnvelope, TraceEvent

_RUNS_DIR = Path(__file__).resolve().parents[2] / ".runs"


@dataclass
class RunState:
    envelope: RunEnvelope
    original_text: str = ""
    original_url: str = ""
    queue: asyncio.Queue[TraceEvent | None] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    busy: bool = False
    snapshots: dict[int, dict] = field(default_factory=dict)

    def save(self) -> None:
        save_run(self)


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        _RUNS_DIR.mkdir(parents=True, exist_ok=True)

    def create(self, envelope: RunEnvelope, *, text: str = "", url: str = "") -> RunState:
        state = RunState(envelope=envelope, original_text=text, original_url=url)
        self._runs[envelope.run_id] = state
        state.save()
        return state

    def get(self, run_id: str) -> RunState | None:
        found = self._runs.get(run_id)
        if found:
            return found
        loaded = load_run(run_id)
        if loaded:
            self._runs[run_id] = loaded
        return loaded


def save_run(state: RunState) -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "original_text": state.original_text,
        "original_url": state.original_url,
        "snapshots": {str(key): value for key, value in state.snapshots.items()},
        "envelope": state.envelope.model_dump(mode="json"),
    }
    path = _RUNS_DIR / f"{state.envelope.run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_run(run_id: str) -> RunState | None:
    path = _RUNS_DIR / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    envelope = RunEnvelope.model_validate(payload.get("envelope") or {})
    interrupted = envelope.phase == "running_layer"
    if interrupted:
        envelope.phase = "error"
        envelope.status = "error"
        envelope.error = (
            "The API restarted while this layer was running. "
            "Use Generate response again for the current layer."
        )
    snapshots = {
        int(key): value for key, value in (payload.get("snapshots") or {}).items()
    }
    state = RunState(
        envelope=envelope,
        original_text=payload.get("original_text") or "",
        original_url=payload.get("original_url") or "",
        snapshots=snapshots,
    )
    if envelope.phase in {"complete", "error"}:
        state.done.set()
    if interrupted:
        state.save()
    return state
