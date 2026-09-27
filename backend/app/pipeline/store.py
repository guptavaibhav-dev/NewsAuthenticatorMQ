from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.envelope import (
    RunEnvelope,
    RunSession,
    RunSummary,
    StoredChatMessage,
    TraceEvent,
    utc_now,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _BACKEND_DIR / ".newsauth.db"
_RUNS_DIR = _BACKEND_DIR / ".runs"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  original_text TEXT NOT NULL DEFAULT '',
  original_url TEXT NOT NULL DEFAULT '',
  headline TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  completed_layer INTEGER NOT NULL DEFAULT 0,
  envelope_json TEXT NOT NULL,
  snapshots_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  layer INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS messages_run_seq ON messages(run_id, seq);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA)
    return conn


def _headline(state: RunState) -> str:
    headline = (state.envelope.classification.headline or "").strip()
    if headline:
        return headline[:200]
    url = state.original_url.strip()
    if url:
        return url[:200]
    text = " ".join(state.original_text.split())
    if text:
        return text[:80] + ("…" if len(text) > 80 else "")
    return state.envelope.run_id


def _apply_interrupt(envelope: RunEnvelope) -> bool:
    if envelope.phase != "running_layer":
        return False
    envelope.phase = "error"
    envelope.status = "error"
    envelope.error = (
        "The API restarted while this layer was running. "
        "Use Generate response again for the current layer."
    )
    return True


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
    db_path: Path = field(default_factory=lambda: _DEFAULT_DB)

    def save(self) -> None:
        save_run(self)


class RunStore:
    def __init__(
        self,
        db_path: Path | None = None,
        runs_dir: Path | None = None,
        *,
        import_json: bool = True,
    ) -> None:
        self._runs: dict[str, RunState] = {}
        self._db_path = Path(db_path) if db_path is not None else _DEFAULT_DB
        self._runs_dir = Path(runs_dir) if runs_dir is not None else _RUNS_DIR
        with _connect(self._db_path):
            pass
        if import_json:
            self._import_json_once()

    def create(self, envelope: RunEnvelope, *, text: str = "", url: str = "") -> RunState:
        state = RunState(
            envelope=envelope,
            original_text=text,
            original_url=url,
            db_path=self._db_path,
        )
        self._runs[envelope.run_id] = state
        state.save()
        return state

    def get(self, run_id: str) -> RunState | None:
        found = self._runs.get(run_id)
        if found:
            return found
        loaded = load_run(run_id, db_path=self._db_path)
        if loaded:
            loaded.db_path = self._db_path
            self._runs[run_id] = loaded
        return loaded

    def list_runs(self) -> list[RunSummary]:
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT run_id, headline, original_url, phase, completed_layer,
                       created_at, updated_at
                FROM runs
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [
            RunSummary(
                run_id=row["run_id"],
                title=row["headline"] or row["run_id"],
                url=row["original_url"] or "",
                phase=row["phase"] or "",
                completed_layer=int(row["completed_layer"] or 0),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def list_messages(self, run_id: str) -> list[StoredChatMessage]:
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, kind, layer, text, created_at, seq
                FROM messages
                WHERE run_id = ?
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            StoredChatMessage(
                id=row["id"],
                kind=row["kind"],
                layer=int(row["layer"]),
                text=row["text"],
                created_at=row["created_at"],
                seq=int(row["seq"]),
            )
            for row in rows
        ]

    def append_message(
        self,
        run_id: str,
        *,
        kind: str,
        layer: int,
        text: str,
        message_id: str | None = None,
    ) -> StoredChatMessage:
        mid = message_id or str(uuid.uuid4())
        now = utc_now()
        with _connect(self._db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not exists:
                raise KeyError(f"Unknown run {run_id}")
            seq = (
                conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM messages WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
                + 1
            )
            conn.execute(
                """
                INSERT INTO messages (id, run_id, seq, kind, layer, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mid, run_id, seq, kind, layer, text, now),
            )
            conn.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            conn.commit()
        return StoredChatMessage(
            id=mid, kind=kind, layer=layer, text=text, created_at=now, seq=seq
        )

    def session(self, run_id: str) -> RunSession | None:
        state = self.get(run_id)
        if not state:
            return None
        return RunSession(
            envelope=state.envelope,
            original_text=state.original_text,
            original_url=state.original_url,
            messages=self.list_messages(run_id),
            snapshots={str(key): value for key, value in state.snapshots.items()},
        )

    def _import_json_once(self) -> None:
        with _connect(self._db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if count:
            return
        if not self._runs_dir.is_dir():
            return
        for path in sorted(self._runs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            envelope_data = payload.get("envelope") or {}
            run_id = envelope_data.get("run_id")
            if not run_id:
                continue
            try:
                envelope = RunEnvelope.model_validate(envelope_data)
            except Exception:
                continue
            snapshots = {
                int(key): value
                for key, value in (payload.get("snapshots") or {}).items()
            }
            state = RunState(
                envelope=envelope,
                original_text=payload.get("original_text") or "",
                original_url=payload.get("original_url") or "",
                snapshots=snapshots,
                db_path=self._db_path,
            )
            save_run(state)


def save_run(state: RunState) -> None:
    envelope = state.envelope
    now = utc_now()
    with _connect(state.db_path) as conn:
        existing = conn.execute(
            "SELECT created_at FROM runs WHERE run_id = ?",
            (envelope.run_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing else (envelope.created_at or now)
        payload = (
            envelope.run_id,
            created_at,
            now,
            state.original_text,
            state.original_url,
            _headline(state),
            envelope.phase,
            envelope.status,
            envelope.completed_layer,
            json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(
                {str(key): value for key, value in state.snapshots.items()},
                ensure_ascii=False,
            ),
        )
        conn.execute(
            """
            INSERT INTO runs (
              run_id, created_at, updated_at, original_text, original_url,
              headline, phase, status, completed_layer, envelope_json, snapshots_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              updated_at = excluded.updated_at,
              original_text = excluded.original_text,
              original_url = excluded.original_url,
              headline = excluded.headline,
              phase = excluded.phase,
              status = excluded.status,
              completed_layer = excluded.completed_layer,
              envelope_json = excluded.envelope_json,
              snapshots_json = excluded.snapshots_json
            """,
            payload,
        )
        conn.commit()


def load_run(run_id: str, db_path: Path | None = None) -> RunState | None:
    path = Path(db_path) if db_path is not None else _DEFAULT_DB
    if not path.is_file():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            """
            SELECT original_text, original_url, envelope_json, snapshots_json
            FROM runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if not row:
        return None
    try:
        envelope = RunEnvelope.model_validate(json.loads(row["envelope_json"] or "{}"))
        raw_snaps = json.loads(row["snapshots_json"] or "{}")
    except (json.JSONDecodeError, Exception):
        return None
    snapshots = {int(key): value for key, value in raw_snaps.items()}
    interrupted = _apply_interrupt(envelope)
    state = RunState(
        envelope=envelope,
        original_text=row["original_text"] or "",
        original_url=row["original_url"] or "",
        snapshots=snapshots,
        db_path=path,
    )
    if envelope.phase in {"complete", "error"}:
        state.done.set()
    if interrupted:
        state.save()
    return state
