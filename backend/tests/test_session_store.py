"""SQLite run store: persist envelopes, list history, keep Q&A, import leftover JSON."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.pipeline.store import RunStore
from app.schemas.envelope import ClassificationPayload, RunEnvelope


def _store(tmp_path: Path) -> RunStore:
    return RunStore(
        db_path=tmp_path / "newsauth.db",
        runs_dir=tmp_path / "runs",
        import_json=True,
    )


def test_save_load_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = RunEnvelope(run_id="run-a", phase="awaiting_decision", completed_layer=2)
    envelope.classification = ClassificationPayload(headline="Coastal defence plan")
    state = store.create(envelope, text="Ministers announced a plan.", url="https://example.com/a")
    state.snapshots[1] = {"run_id": "run-a", "completed_layer": 0}
    state.save()

    store._runs.clear()
    loaded = store.get("run-a")
    assert loaded is not None
    assert loaded.original_text == "Ministers announced a plan."
    assert loaded.original_url == "https://example.com/a"
    assert loaded.envelope.classification.headline == "Coastal defence plan"
    assert loaded.snapshots[1]["completed_layer"] == 0


def test_list_newest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create(RunEnvelope(run_id="older"), text="first")
    first.envelope.phase = "complete"
    first.save()
    second = store.create(RunEnvelope(run_id="newer"), text="second")
    second.envelope.phase = "awaiting_decision"
    second.save()

    rows = store.list_runs()
    assert [row.run_id for row in rows] == ["newer", "older"]
    assert rows[0].title == "second"


def test_messages_survive_reload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(RunEnvelope(run_id="chat"), text="article")
    store.append_message("chat", kind="question", layer=4, text="What is backed?")
    store.append_message("chat", kind="answer", layer=4, text="Two of five scored claims.")

    store._runs.clear()
    session = store.session("chat")
    assert session is not None
    assert [row.kind for row in session.messages] == ["question", "answer"]
    assert session.messages[0].text == "What is backed?"
    assert session.messages[1].text == "Two of five scored claims."
    assert session.original_text == "article"


def test_pairs_scored_false_does_not_write_json_sidecar(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(RunEnvelope(run_id="no-json"), text="x")
    assert not (tmp_path / "runs" / "no-json.json").exists()
    assert (tmp_path / "newsauth.db").is_file()


def test_json_import_once(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    payload = {
        "original_text": "imported paste",
        "original_url": "https://example.com/old",
        "snapshots": {"1": {"run_id": "from-json"}},
        "envelope": {
            "run_id": "from-json",
            "phase": "complete",
            "completed_layer": 7,
            "classification": {"headline": "Imported headline"},
        },
    }
    (runs_dir / "from-json.json").write_text(json.dumps(payload), encoding="utf-8")

    store = RunStore(db_path=tmp_path / "newsauth.db", runs_dir=runs_dir)
    loaded = store.get("from-json")
    assert loaded is not None
    assert loaded.original_text == "imported paste"
    assert loaded.envelope.classification.headline == "Imported headline"

    (runs_dir / "second.json").write_text(
        json.dumps(
            {
                "original_text": "should not import",
                "envelope": {"run_id": "second"},
            }
        ),
        encoding="utf-8",
    )
    again = RunStore(db_path=tmp_path / "newsauth.db", runs_dir=runs_dir)
    assert again.get("second") is None
    assert again.get("from-json") is not None


def test_list_and_session_http(tmp_path: Path, monkeypatch) -> None:
    from app import main

    store = _store(tmp_path)
    envelope = RunEnvelope(run_id="http-run", phase="awaiting_decision", completed_layer=3)
    store.create(envelope, text="http paste", url="https://example.com/http")
    store.append_message("http-run", kind="question", layer=3, text="Why one newsroom?")
    store.append_message("http-run", kind="answer", layer=3, text="Wire copies collapsed.")
    monkeypatch.setattr(main, "store", store)

    client = TestClient(main.app)
    listed = client.get("/api/runs")
    assert listed.status_code == 200
    body = listed.json()
    assert body[0]["run_id"] == "http-run"
    assert "title" in body[0]

    session = client.get("/api/runs/http-run/session")
    assert session.status_code == 200
    data = session.json()
    assert data["original_text"] == "http paste"
    assert data["envelope"]["run_id"] == "http-run"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["kind"] == "question"
