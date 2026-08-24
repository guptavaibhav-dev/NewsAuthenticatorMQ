from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.schemas.envelope import RunEnvelope, TraceEvent


@dataclass
class RunState:
    envelope: RunEnvelope
    queue: asyncio.Queue[TraceEvent | None] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def create(self, envelope: RunEnvelope) -> RunState:
        state = RunState(envelope=envelope)
        self._runs[envelope.run_id] = state
        return state

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)
