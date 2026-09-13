from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import (
    DEV_CONTACT_PLACEHOLDER,
    INGEST_ACCEPT,
    Settings,
    build_user_agent,
    get_settings,
)
from app.schemas.envelope import InputPayload
from app.tools.ingest import ingest_input

ARTICLE_BODY = (
    "Ministers announced a new coastal defence plan on Tuesday morning, "
    "citing storm damage from last winter and a three-year construction timetable."
)
ARTICLE_HTML = (
    "<!DOCTYPE html><html><head><title>Coast</title></head>"
    f"<body><article><p>{ARTICLE_BODY}</p></article></body></html>"
)


def test_user_agent_uses_contact_url() -> None:
    assert (
        build_user_agent("https://example.edu/newsauth", "development")
        == "NewsAuthBot/1.0 (+https://example.edu/newsauth)"
    )


def test_user_agent_placeholder_in_dev() -> None:
    ua = build_user_agent("", "development")
    assert ua == f"NewsAuthBot/1.0 (+{DEV_CONTACT_PLACEHOLDER})"


def test_user_agent_required_in_production() -> None:
    with pytest.raises(RuntimeError, match="CONTACT_URL"):
        build_user_agent("", "production")
    with pytest.raises(RuntimeError, match="CONTACT_URL"):
        Settings(environment="production", contact_url="")


def test_ingest_sends_identifying_headers_and_timeouts() -> None:
    seen: dict[str, object] = {}

    class RecordingClient(httpx.AsyncClient):
        async def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["headers"] = kwargs.get("headers") or {}
            seen["timeout"] = kwargs.get("timeout")
            return await super().get(url, **kwargs)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=ARTICLE_HTML,
            headers={"content-type": "text/html"},
            request=request,
        )

    client = RecordingClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text="", url="https://news.example.com/story")
        finally:
            await client.aclose()

    payload = asyncio.run(_go())
    assert payload.fetch_reason == "ok"
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == get_settings().app_user_agent
    assert headers["Accept"] == INGEST_ACCEPT
    timeout = seen["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 5.0
    assert timeout.read == 20.0


def test_pdf_is_unsupported_coverage_gap_not_parsed_as_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4 press-release",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text="pasted notes", url="https://gov.example.com/pr.pdf")
        finally:
            await client.aclose()

    payload = asyncio.run(_go())
    assert payload.fetch_reason == "error_unsupported_type"
    assert payload.fetch_status == "error"
    assert payload.content_type == "application/pdf"
    assert payload.extracted_char_count == 0
    assert "pasted notes" in payload.raw_text


def test_429_surfaces_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text="slow down",
            headers={"content-type": "text/html", "retry-after": "120"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text="", url="https://news.example.com/story")
        finally:
            await client.aclose()

    payload = asyncio.run(_go())
    assert payload.fetch_reason == "error_blocked"
    assert payload.http_status == 429
    assert payload.retry_after == "120"
    assert payload.fetch_error == "HTTP 429; Retry-After: 120"
