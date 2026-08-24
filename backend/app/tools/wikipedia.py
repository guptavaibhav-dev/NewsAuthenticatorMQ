from __future__ import annotations

import httpx

from app.config import APP_USER_AGENT
from app.schemas.envelope import ToolResult, WikiHit

WIKI_HEADERS = {
    "User-Agent": APP_USER_AGENT,
    "Accept": "application/json",
}


async def search_wikipedia(
    client: httpx.AsyncClient,
    *,
    query: str,
) -> tuple[WikiHit, ToolResult]:
    if not query:
        return WikiHit(query=query, found=False), ToolResult(
            tool="wikipedia", status="empty", detail="empty query"
        )
    try:
        response = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
                "origin": "*",
            },
            headers=WIKI_HEADERS,
        )
        response.raise_for_status()
        rows = ((response.json().get("query") or {}).get("search") or [])
        if rows:
            title = rows[0].get("title")
            hit = WikiHit(
                query=query,
                title=title,
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}" if title else None,
                description=_strip_html(rows[0].get("snippet") or ""),
                found=True,
            )
            return hit, ToolResult(tool="wikipedia", status="ok", hit_count=1)

        wd = await _wikidata(client, query)
        return wd, ToolResult(
            tool="wikipedia",
            status="ok" if wd.found else "empty",
            hit_count=int(wd.found),
            detail="wikidata fallback" if wd.found else "no page",
        )
    except Exception as exc:
        wd = await _wikidata(client, query)
        if wd.found:
            return wd, ToolResult(tool="wikipedia", status="ok", hit_count=1, detail="wikidata fallback")
        return WikiHit(query=query, found=False), ToolResult(
            tool="wikipedia", status="error", detail=str(exc)[:240]
        )


async def _wikidata(client: httpx.AsyncClient, query: str) -> WikiHit:
    try:
        response = await client.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": "en",
                "format": "json",
                "limit": 1,
                "origin": "*",
            },
            headers=WIKI_HEADERS,
        )
        response.raise_for_status()
        rows = response.json().get("search") or []
        if not rows:
            return WikiHit(query=query, found=False)
        row = rows[0]
        return WikiHit(
            query=query,
            title=row.get("label"),
            url=row.get("concepturi") or row.get("url"),
            description=row.get("description"),
            found=True,
        )
    except Exception:
        return WikiHit(query=query, found=False)


def _strip_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", value)
