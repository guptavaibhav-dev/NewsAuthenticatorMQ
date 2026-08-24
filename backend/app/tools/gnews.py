from __future__ import annotations

import httpx

from app.config import Settings
from app.schemas.envelope import EvidenceItem, ToolResult
from app.scoring.source_independence import publisher_family, source_band
from app.scoring.urls import registrable_domain


async def search_second_aggregator(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 8,
) -> tuple[list[EvidenceItem], ToolResult]:
    if settings.gnews_api_key:
        return await _gnews(
            client, settings, query=query, date_from=date_from, date_to=date_to, page_size=page_size
        )
    if settings.newsdata_api_key:
        return await _newsdata(
            client, settings, query=query, date_from=date_from, date_to=date_to, page_size=page_size
        )
    return [], ToolResult(
        tool="gnews",
        status="skipped",
        detail="GNEWS_API_KEY / NEWSDATA_API_KEY not set",
    )


async def _gnews(client, settings: Settings, *, query, date_from, date_to, page_size):
    params = {
        "q": query[:200],
        "lang": "en",
        "max": page_size,
        "token": settings.gnews_api_key,
    }
    if date_from:
        params["from"] = date_from
    if date_to:
        params["to"] = date_to
    try:
        response = await client.get("https://gnews.io/api/v4/search", params=params)
        response.raise_for_status()
        articles = response.json().get("articles") or []
        items = [
            _item("gnews", i, article.get("source", {}).get("name"), article.get("url"), article.get("title"), article.get("publishedAt"), article.get("description") or article.get("content") or "")
            for i, article in enumerate(articles)
            if article.get("url")
        ]
        return items, ToolResult(tool="gnews", status="ok" if items else "empty", hit_count=len(items))
    except Exception as exc:
        return [], ToolResult(tool="gnews", status="error", detail=str(exc)[:240])


async def _newsdata(client, settings: Settings, *, query, date_from, date_to, page_size):
    params = {
        "q": query[:200],
        "language": "en",
        "apikey": settings.newsdata_api_key,
    }
    if date_from:
        params["from_date"] = date_from[:10]
    if date_to:
        params["to_date"] = date_to[:10]
    try:
        response = await client.get("https://newsdata.io/api/1/news", params=params)
        response.raise_for_status()
        results = response.json().get("results") or []
        items = []
        for i, article in enumerate(results[:page_size]):
            url = article.get("link") or ""
            if not url:
                continue
            items.append(
                _item(
                    "newsdata",
                    i,
                    article.get("source_id") or article.get("source_name"),
                    url,
                    article.get("title"),
                    article.get("pubDate"),
                    article.get("description") or article.get("content") or "",
                )
            )
        return items, ToolResult(
            tool="newsdata", status="ok" if items else "empty", hit_count=len(items)
        )
    except Exception as exc:
        return [], ToolResult(tool="newsdata", status="error", detail=str(exc)[:240])


def _item(tool: str, i: int, outlet, url, title, published, snippet) -> EvidenceItem:
    url = url or ""
    return EvidenceItem(
        source_id=f"{tool}-{i+1}",
        outlet=outlet or registrable_domain(url),
        domain=registrable_domain(url),
        url=url,
        title=title or "",
        published_at=published,
        snippet=(snippet or "")[:800],
        tool=tool,
        publisher_family=publisher_family(url),
        source_band=source_band(url),
    )
