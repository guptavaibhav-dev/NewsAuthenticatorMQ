from __future__ import annotations

import httpx

from app.config import Settings
from app.schemas.envelope import EvidenceItem, ToolResult
from app.scoring.source_independence import publisher_family, source_band
from app.scoring.urls import registrable_domain


async def search_newsapi(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    search_in: str | None = None,
    page_size: int = 10,
    id_prefix: str = "newsapi",
) -> tuple[list[EvidenceItem], ToolResult]:
    if not settings.newsapi_key:
        return [], ToolResult(tool="newsapi", status="skipped", detail="NEWSAPI_KEY not set")
    if not query:
        return [], ToolResult(tool="newsapi", status="empty", detail="empty query")
    params: dict[str, str | int] = {
        "q": query[:500],
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": page_size,
        "apiKey": settings.newsapi_key,
    }
    if date_from:
        params["from"] = date_from
    if date_to:
        params["to"] = date_to
    if search_in:
        params["searchIn"] = search_in
    try:
        response = await client.get("https://newsapi.org/v2/everything", params=params)
        if response.status_code >= 400:
            message = ""
            try:
                payload = response.json()
                message = str(payload.get("message") or payload.get("code") or payload)
            except Exception:
                message = response.text[:200]
            return [], ToolResult(
                tool="newsapi",
                status="error",
                detail=f"HTTP {response.status_code} {message}"[:240],
            )
        articles = response.json().get("articles") or []
        items: list[EvidenceItem] = []
        for i, article in enumerate(articles):
            url = article.get("url") or ""
            if not url:
                continue
            items.append(
                EvidenceItem(
                    source_id=f"{id_prefix}-{i+1}",
                    outlet=(article.get("source") or {}).get("name") or registrable_domain(url),
                    domain=registrable_domain(url),
                    url=url,
                    title=article.get("title") or "",
                    published_at=article.get("publishedAt"),
                    snippet=(article.get("description") or article.get("content") or "")[:800],
                    tool="newsapi",
                    publisher_family=publisher_family(url),
                    source_band=source_band(url),
                )
            )
        status = "ok" if items else "empty"
        return items, ToolResult(tool="newsapi", status=status, hit_count=len(items))
    except Exception as exc:
        return [], ToolResult(tool="newsapi", status="error", detail=str(exc)[:240])
