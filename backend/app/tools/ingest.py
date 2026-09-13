from __future__ import annotations

import html as html_lib
import json
import re
import socket
import ssl
import unicodedata
from datetime import datetime, timezone
from typing import Literal

import httpx
import trafilatura
from trafilatura.settings import use_config

from app.config import INGEST_ACCEPT, get_settings
from app.schemas.envelope import FetchReason, InputPayload, TextSegment, fetch_status_for_reason
from app.scoring.urls import canonical_url, publisher_identity, registrable_domain, resolve_canonical_url

_CFG = use_config()
# Parsing budget only. HTTP connect/read timeouts are set per request on ingest.
_CFG.set("DEFAULT", "EXTRACTION_TIMEOUT", "20")

MAX_RESPONSE_BYTES = 5_000_000
MIN_OK_EXTRACTED_CHARS = 80
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscribe to read",
    "subscription-required",
    "piano-paywall",
    "data-paywall",
    "id=\"paywall\"",
    "class=\"paywall\"",
    "this article is for subscribers",
    "become a subscriber",
    "already a subscriber",
    "metered_paywall",
)
_SEP = "\n\n"
_QUOTE_DASH_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2032": "'",
        "\u2033": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def normalize_for_compare(text: str) -> str:
    """Normalise text for overlap checks only. Never applied to `raw_text`."""
    folded = unicodedata.normalize("NFKC", text or "").translate(_QUOTE_DASH_MAP).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def paste_already_in_fetched(pasted: str, fetched: str) -> bool:
    """True when the journalist paste is already present in the publisher body.

    Comparison uses normalised forms only. A match is a coverage overlap, not
    evidence that the paste is a publisher quote or that the article is authentic.
    """
    if not pasted or not fetched:
        return False
    return normalize_for_compare(pasted) in normalize_for_compare(fetched)


def build_raw_text_and_segments(pasted: str, fetched: str) -> tuple[str, list[TextSegment]]:
    """Concatenate paste and fetched body and emit tiling segments.

    `raw_text` stays the concatenation so Layer 2 can keep reading one string.
    The separator between sources, if any, is attached to the preceding span
    so segments stay ordered, non-overlapping, and exhaustive. Does not score
    or classify the content.
    """
    pasted = pasted or ""
    fetched = fetched or ""
    if pasted and fetched and paste_already_in_fetched(pasted, fetched):
        return fetched, [TextSegment(source="fetched", start=0, end=len(fetched))]
    parts: list[tuple[Literal["pasted", "fetched"], str]] = []
    if pasted:
        parts.append(("pasted", pasted))
    if fetched:
        parts.append(("fetched", fetched))
    if not parts:
        return "", []
    if len(parts) == 1:
        source, text = parts[0]
        return text, [TextSegment(source=source, start=0, end=len(text))]
    raw = parts[0][1] + _SEP + parts[1][1]
    split_at = len(parts[0][1]) + len(_SEP)
    return raw, [
        TextSegment(source=parts[0][0], start=0, end=split_at),
        TextSegment(source=parts[1][0], start=split_at, end=len(raw)),
    ]


def segment_text(payload: InputPayload, source: Literal["pasted", "fetched"]) -> str:
    """Return the concatenated `raw_text` slice(s) for one source kind.

    Empty string if that source is absent. Does not normalise, strip, or
    interpret the text.
    """
    return "".join(
        payload.raw_text[seg.start : seg.end] for seg in payload.segments if seg.source == source
    )


def _apply_text(payload: InputPayload, pasted: str, fetched: str) -> None:
    raw, segments = build_raw_text_and_segments(pasted, fetched)
    payload.raw_text = raw
    payload.segments = segments
    payload.text_merged = any(s.source == "pasted" for s in segments) and any(
        s.source == "fetched" for s in segments
    )


def _set_fetch(payload: InputPayload, reason: FetchReason, error: str | None = None) -> None:
    payload.fetch_reason = reason
    payload.fetch_status = fetch_status_for_reason(reason)
    payload.fetch_error = error[:240] if error else None


def _content_type(response: httpx.Response) -> str | None:
    raw = response.headers.get("content-type")
    if not raw:
        return None
    return raw.split(";", 1)[0].strip().lower() or None


def _redirect_chain(response: httpx.Response) -> list[str]:
    urls = [str(hop.url) for hop in response.history]
    final = str(response.url)
    if not urls or urls[-1] != final:
        urls.append(final)
    return urls


def _record_response_observables(payload: InputPayload, response: httpx.Response) -> None:
    payload.http_status = response.status_code
    payload.final_url = str(response.url)
    payload.content_type = _content_type(response)
    payload.redirect_chain = _redirect_chain(response)
    header_len = response.headers.get("content-length")
    if header_len and header_len.isdigit():
        payload.response_bytes = int(header_len)


def _caused_by(exc: BaseException, *types: type[BaseException]) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, types):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def classify_fetch_exception(exc: BaseException) -> FetchReason:
    """Map a transport exception to fetch_reason. Diagnostic, not a falsity label."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "error_timeout"
    if _caused_by(exc, ssl.SSLError) or "ssl" in type(exc).__name__.lower():
        return "error_tls"
    if _caused_by(exc, socket.gaierror) or isinstance(exc, httpx.ConnectError):
        text = str(exc).lower()
        if _caused_by(exc, socket.gaierror) or any(
            needle in text
            for needle in (
                "getaddrinfo",
                "name or service not known",
                "nodename nor servname",
                "failed to resolve",
                "name resolution",
                "temporary failure in name resolution",
            )
        ):
            return "error_dns"
        if _caused_by(exc, ssl.SSLError):
            return "error_tls"
        return "error_other"
    return "error_other"


def _status_reason(status: int) -> FetchReason | None:
    if status in {401, 403, 429}:
        return "error_blocked"
    if status in {404, 410}:
        return "error_not_found"
    if 500 <= status <= 599:
        return "error_server"
    if status >= 400:
        return "error_other"
    return None


def _is_html_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    return content_type in _HTML_TYPES


def _has_paywall_markers(html: str) -> bool:
    lowered = (html or "").lower()
    return any(marker in lowered for marker in _PAYWALL_MARKERS)


def _is_js_required(html: str, extracted_chars: int) -> bool:
    if extracted_chars >= MIN_OK_EXTRACTED_CHARS:
        return False
    scripts = len(re.findall(r"<script\b", html or "", re.I))
    return scripts >= 8 or (scripts >= 5 and len(html or "") > 1500)


def classify_empty_html(html: str, extracted_chars: int) -> FetchReason:
    """Why extracted text is missing. Coverage taxonomy only — not authenticity."""
    if _has_paywall_markers(html):
        return "empty_paywall"
    if _is_js_required(html, extracted_chars):
        return "empty_js_required"
    return "empty_not_article"


def _extract_article(html: str, url: str) -> tuple[str | None, str]:
    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        config=_CFG,
        output_format="json",
    )
    title = None
    body = ""
    if extracted:
        data = json.loads(extracted)
        title = data.get("title")
        body = data.get("text") or ""
    if not title:
        title = _title_from_html(html)
    if not body:
        body = trafilatura.extract(html) or ""
    return title, (body or "").strip()


async def ingest_input(
    client: httpx.AsyncClient,
    *,
    text: str,
    url: str,
) -> InputPayload:
    cleaned_text = (text or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        raw, segments = build_raw_text_and_segments(cleaned_text, "")
        return InputPayload(
            raw_text=raw,
            url=None,
            fetch_status="skipped",
            fetch_reason="skipped_no_url",
            extracted_char_count=0,
            segments=segments,
        )

    domain, publisher_id, is_platform = publisher_identity(cleaned_url)
    payload = InputPayload(
        raw_text=cleaned_text,
        url=cleaned_url,
        canonical_url=canonical_url(cleaned_url),
        canonical_source="final_url",
        publisher_domain=domain or None,
        publisher_id=publisher_id or None,
        publisher_is_platform=is_platform,
        fetch_timestamp=datetime.now(timezone.utc).isoformat(),
        fetch_status="error",
        fetch_reason="error_other",
        segments=[TextSegment(source="pasted", start=0, end=len(cleaned_text))]
        if cleaned_text
        else [],
    )
    try:
        settings = get_settings()
        response = await client.get(
            cleaned_url,
            follow_redirects=True,
            headers={
                "User-Agent": settings.app_user_agent,
                "Accept": INGEST_ACCEPT,
            },
            timeout=httpx.Timeout(
                connect=settings.ingest_connect_timeout_s,
                read=settings.ingest_read_timeout_s,
                write=settings.ingest_read_timeout_s,
                pool=settings.ingest_connect_timeout_s,
            ),
        )
        _record_response_observables(payload, response)
        retry_after = response.headers.get("retry-after")
        if retry_after:
            payload.retry_after = retry_after
        resolved, source = resolve_canonical_url("", str(response.url))
        payload.canonical_url = resolved
        payload.canonical_source = source
        domain, publisher_id, is_platform = publisher_identity(str(response.url))
        payload.publisher_domain = domain or registrable_domain(str(response.url)) or None
        payload.publisher_id = publisher_id or None
        payload.publisher_is_platform = is_platform

        status_reason = _status_reason(response.status_code)
        if status_reason:
            _apply_text(payload, cleaned_text, "")
            detail = f"HTTP {response.status_code}"
            if response.status_code == 429 and retry_after:
                detail += f"; Retry-After: {retry_after}"
            _set_fetch(payload, status_reason, detail)
            return payload

        header_len = payload.response_bytes
        if header_len is not None and header_len > MAX_RESPONSE_BYTES:
            _apply_text(payload, cleaned_text, "")
            _set_fetch(payload, "error_too_large", f"Content-Length {header_len}")
            return payload

        content_type = payload.content_type or ""
        if content_type.startswith("application/pdf"):
            # TODO: add a PDF text extractor for press releases and government
            # reports. Until then this is a coverage gap, not a falsity signal.
            payload.response_bytes = len(response.content)
            _apply_text(payload, cleaned_text, "")
            _set_fetch(
                payload,
                "error_unsupported_type",
                f"unsupported content-type {payload.content_type}",
            )
            return payload

        if not _is_html_type(payload.content_type):
            payload.response_bytes = len(response.content)
            _apply_text(payload, cleaned_text, "")
            _set_fetch(
                payload,
                "error_unsupported_type",
                f"unsupported content-type {payload.content_type}",
            )
            return payload

        html = response.text or ""
        payload.response_bytes = len(response.content)
        if payload.response_bytes > MAX_RESPONSE_BYTES:
            _apply_text(payload, cleaned_text, "")
            _set_fetch(payload, "error_too_large", f"body {payload.response_bytes} bytes")
            return payload

        title, fetched_body = _extract_article(html, str(response.url))
        resolved, source = resolve_canonical_url(html, str(response.url))
        payload.canonical_url = resolved
        payload.canonical_source = source
        payload.fetched_title = title
        payload.extracted_char_count = len(fetched_body)
        if len(fetched_body) >= MIN_OK_EXTRACTED_CHARS:
            _apply_text(payload, cleaned_text, fetched_body)
            _set_fetch(payload, "ok")
            return payload
        _apply_text(payload, cleaned_text, fetched_body)
        _set_fetch(payload, classify_empty_html(html, len(fetched_body)))
        return payload
    except Exception as exc:
        _apply_text(payload, cleaned_text, "")
        payload.fetched_title = None
        _set_fetch(payload, classify_fetch_exception(exc), str(exc))
        return payload


def _title_from_html(html: str) -> str | None:
    patterns = (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
        r"<title[^>]*>([^<]+)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I)
        if not match:
            continue
        title = html_lib.unescape(match.group(1)).strip()
        title = re.sub(r"\s+", " ", title)
        if title and title.lower() not in {"bbc news", "bbc"}:
            return title[:240]
    return None
