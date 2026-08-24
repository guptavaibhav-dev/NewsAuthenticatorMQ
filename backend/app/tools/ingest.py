from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timezone

import httpx
import trafilatura
from trafilatura.settings import use_config

from app.config import APP_USER_AGENT
from app.schemas.envelope import InputPayload
from app.scoring.urls import canonical_url, registrable_domain

_CFG = use_config()
_CFG.set("DEFAULT", "EXTRACTION_TIMEOUT", "20")


async def ingest_input(
    client: httpx.AsyncClient,
    *,
    text: str,
    url: str,
) -> InputPayload:
    cleaned_text = (text or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return InputPayload(
            raw_text=cleaned_text,
            url=None,
            fetch_status="skipped",
        )

    payload = InputPayload(
        raw_text=cleaned_text,
        url=cleaned_url,
        canonical_url=canonical_url(cleaned_url),
        publisher_domain=registrable_domain(cleaned_url),
        fetch_timestamp=datetime.now(timezone.utc).isoformat(),
        fetch_status="error",
    )
    try:
        response = await client.get(
            cleaned_url,
            follow_redirects=True,
            headers={"User-Agent": APP_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        html = response.text or ""
        extracted = trafilatura.extract(
            html,
            url=str(response.url),
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
        combined = body.strip()
        if cleaned_text and cleaned_text not in combined:
            combined = f"{cleaned_text}\n\n{combined}".strip()
        payload.raw_text = combined or cleaned_text
        payload.fetched_title = title
        payload.canonical_url = canonical_url(str(response.url))
        payload.publisher_domain = registrable_domain(str(response.url))
        if combined:
            payload.fetch_status = "ok"
        elif response.is_success:
            payload.fetch_status = "empty"
        else:
            payload.fetch_status = "error"
            payload.fetch_error = f"HTTP {response.status_code}"
        return payload
    except Exception as exc:
        payload.raw_text = cleaned_text
        payload.fetch_status = "error"
        payload.fetched_title = None
        payload.fetch_error = str(exc)[:240]
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
