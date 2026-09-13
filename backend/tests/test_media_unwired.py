from __future__ import annotations

import ast
from pathlib import Path

from app.pipeline.orchestrator import _run_input
from app.schemas.envelope import InputPayload
from app.tools import media as media_mod


ROOT = Path(__file__).resolve().parents[1]


def test_inspect_media_is_not_a_callable() -> None:
    assert not hasattr(media_mod, "inspect_media")
    assert "C2PA" in (media_mod.__doc__ or "")
    assert "not wired" in (media_mod.__doc__ or "").lower()


def test_run_input_does_not_call_media() -> None:
    source = Path(_run_input.__code__.co_filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_input"
    )
    called = [
        ast.unparse(n.func)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
    ]
    assert "inspect_media" not in called
    imports = [
        ast.unparse(n)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    assert not any("inspect_media" in row for row in imports)


def test_input_payload_has_no_media_fields() -> None:
    assert all("media" not in name.lower() for name in InputPayload.model_fields)


def test_readme_mentions_media_future_work() -> None:
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    assert "media.py" in readme.lower() or "Media provenance" in readme
    assert "C2PA" in readme
