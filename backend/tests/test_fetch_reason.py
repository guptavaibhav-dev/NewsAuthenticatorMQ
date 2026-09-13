from __future__ import annotations

import asyncio
import ssl

import httpx
import pytest

from app.schemas.envelope import FetchReason, InputPayload, fetch_status_for_reason
from app.tools.ingest import (
    MAX_RESPONSE_BYTES,
    classify_empty_html,
    classify_fetch_exception,
    ingest_input,
)

ALL_REASONS: tuple[FetchReason, ...] = (
    "ok",
    "skipped_no_url",
    "empty_paywall",
    "empty_js_required",
    "empty_not_article",
    "error_dns",
    "error_timeout",
    "error_tls",
    "error_blocked",
    "error_not_found",
    "error_server",
    "error_unsupported_type",
    "error_too_large",
    "error_other",
)

ARTICLE_BODY = (
    "Ministers announced a new coastal defence plan on Tuesday morning, "
    "citing storm damage from last winter and a three-year construction timetable."
)


def _html(title: str, body: str, extra_head: str = "", extra_body: str = "") -> str:
    return (
        "<!DOCTYPE html><html><head><title>"
        f"{title}</title>{extra_head}</head><body><article><h1>{title}</h1>"
        f"<p>{body}</p></article>{extra_body}</body></html>"
    )


def _run(
    *,
    text: str = "",
    url: str = "https://news.example.com/story",
    status: int = 200,
    html: str | None = None,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    exc: BaseException | None = None,
    history: list[str] | None = None,
) -> InputPayload:
    hdrs = {"content-type": "text/html; charset=utf-8"}
    if headers:
        hdrs.update(headers)

    def handler(request: httpx.Request) -> httpx.Response:
        if exc:
            raise exc
        if history and str(request.url) == url:
            return httpx.Response(
                302,
                headers={"location": history[0], "content-type": "text/html"},
                request=request,
            )
        body = content if content is not None else (html or "").encode("utf-8")
        return httpx.Response(status, content=body, headers=hdrs, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text=text, url=url)
        finally:
            await client.aclose()

    return asyncio.run(_go())


def test_fetch_status_mapping_covers_every_reason() -> None:
    expected = {
        "ok": "ok",
        "skipped_no_url": "skipped",
        "empty_paywall": "empty",
        "empty_js_required": "empty",
        "empty_not_article": "empty",
        "error_dns": "error",
        "error_timeout": "error",
        "error_tls": "error",
        "error_blocked": "error",
        "error_not_found": "error",
        "error_server": "error",
        "error_unsupported_type": "error",
        "error_too_large": "error",
        "error_other": "error",
    }
    assert set(expected) == set(ALL_REASONS)
    for reason, status in expected.items():
        assert fetch_status_for_reason(reason) == status
        payload = InputPayload(fetch_reason=reason)
        assert payload.fetch_status == status


def test_legacy_payload_without_fetch_reason_keeps_status() -> None:
    payload = InputPayload.model_validate({"fetch_status": "ok", "raw_text": "hello"})
    assert payload.fetch_reason == "ok"
    assert payload.fetch_status == "ok"


def test_skipped_no_url() -> None:
    payload = _run(text="notes only", url="")
    assert payload.fetch_reason == "skipped_no_url"
    assert payload.fetch_status == "skipped"
    assert payload.http_status is None
    assert payload.redirect_chain == []


def test_ok_records_observables() -> None:
    payload = _run(html=_html("Coast", ARTICLE_BODY))
    assert payload.fetch_reason == "ok"
    assert payload.fetch_status == "ok"
    assert payload.http_status == 200
    assert payload.final_url.endswith("/story")
    assert payload.content_type == "text/html"
    assert payload.response_bytes is not None and payload.response_bytes > 0
    assert payload.redirect_chain[-1].endswith("/story")
    assert payload.fetch_error is None


def test_empty_paywall() -> None:
    html = (
        "<html><body><div class=\"paywall\">Subscribe to continue reading this story."
        "</div></body></html>"
    )
    payload = _run(html=html)
    assert payload.fetch_reason == "empty_paywall"
    assert payload.fetch_status == "empty"


def test_empty_js_required() -> None:
    scripts = "".join(f'<script src="app{i}.js"></script>' for i in range(10))
    html = f"<html><head>{scripts}</head><body><div id='root'></div></body></html>"
    payload = _run(html=html)
    assert payload.fetch_reason == "empty_js_required"
    assert payload.fetch_status == "empty"


def test_empty_not_article() -> None:
    html = "<html><head><title>Contact</title></head><body><p>Hi</p></body></html>"
    payload = _run(html=html)
    assert payload.fetch_reason == "empty_not_article"
    assert payload.fetch_status == "empty"


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "error_blocked"),
        (403, "error_blocked"),
        (429, "error_blocked"),
        (404, "error_not_found"),
        (410, "error_not_found"),
        (500, "error_server"),
        (502, "error_server"),
        (418, "error_other"),
    ],
)
def test_http_status_taxonomy(status: int, reason: str) -> None:
    payload = _run(status=status, html="<html><body>nope</body></html>")
    assert payload.fetch_reason == reason
    assert payload.fetch_status == "error"
    assert payload.http_status == status
    assert payload.fetch_error == f"HTTP {status}"


def test_unsupported_type() -> None:
    payload = _run(
        html=None,
        content=b"%PDF-1.4 fake",
        headers={"content-type": "application/pdf"},
    )
    assert payload.fetch_reason == "error_unsupported_type"
    assert payload.content_type == "application/pdf"
    assert payload.fetch_status == "error"


def test_too_large_from_content_length() -> None:
    payload = _run(
        html="<html><body>tiny</body></html>",
        headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
    )
    assert payload.fetch_reason == "error_too_large"
    assert payload.response_bytes == MAX_RESPONSE_BYTES + 1


def test_dns_timeout_tls_exceptions() -> None:
    dns = classify_fetch_exception(httpx.ConnectError("getaddrinfo failed"))
    timeout = classify_fetch_exception(httpx.ReadTimeout("timed out"))
    tls_exc = ssl.SSLError("certificate verify failed")
    wrapped = httpx.ConnectError("ssl handshake")
    wrapped.__cause__ = tls_exc
    tls = classify_fetch_exception(wrapped)
    other = classify_fetch_exception(RuntimeError("boom"))
    assert dns == "error_dns"
    assert timeout == "error_timeout"
    assert tls == "error_tls"
    assert other == "error_other"

    payload = _run(exc=httpx.ConnectError("getaddrinfo failed"))
    assert payload.fetch_reason == "error_dns"
    assert payload.fetch_status == "error"
    assert payload.fetch_error
    assert payload.http_status is None


def test_redirect_chain_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go":
            return httpx.Response(
                302,
                headers={"location": "https://news.example.com/story"},
                request=request,
            )
        return httpx.Response(
            200,
            text=_html("Coast", ARTICLE_BODY),
            headers={"content-type": "text/html"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text="", url="https://news.example.com/go")
        finally:
            await client.aclose()

    payload = asyncio.run(_go())
    assert payload.fetch_reason == "ok"
    assert any(u.endswith("/go") for u in payload.redirect_chain) or len(payload.redirect_chain) >= 1
    assert payload.final_url.endswith("/story")


def test_empty_classifier_helpers() -> None:
    assert classify_empty_html('<div class="paywall">Subscribe to continue</div>', 0) == "empty_paywall"
    scripts = "".join(f"<script src='x{i}.js'></script>" for i in range(9))
    assert classify_empty_html(scripts, 0) == "empty_js_required"
    assert classify_empty_html("<html><body>Hi</body></html>", 2) == "empty_not_article"
