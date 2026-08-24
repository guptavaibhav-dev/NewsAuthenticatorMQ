from __future__ import annotations

import httpx

from app.config import Settings
from app.schemas.envelope import EvidenceItem, ToolResult
from app.scoring.source_independence import publisher_family, source_band
from app.scoring.urls import registrable_domain

GUARDIAN_DOMAIN = "theguardian.com"


async def search_guardian(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 8,
    include_body: bool = False,
    id_prefix: str = "guardian",
) -> tuple[list[EvidenceItem], ToolResult]:
    if not settings.guardian_api_key:
        return [], ToolResult(
            tool="guardian", status="skipped", detail="GUARDIAN_API_KEY not set"
        )
    if not query:
        return [], ToolResult(tool="guardian", status="empty", detail="empty query")
    fields = "headline,trailText,byline,firstPublicationDate"
    if include_body:
        fields += ",bodyText"
    params: dict[str, str | int] = {
        "q": query[:200],
        "api-key": settings.guardian_api_key,
        "show-fields": fields,
        "page-size": page_size,
        "order-by": "relevance",
    }
    if date_from:
        params["from-date"] = date_from[:10]
    if date_to:
        params["to-date"] = date_to[:10]
    try:
        response = await client.get("https://content.guardianapis.com/search", params=params)
        response.raise_for_status()
        results = (response.json().get("response") or {}).get("results") or []
        items: list[EvidenceItem] = []
        for i, article in enumerate(results):
            fields_obj = article.get("fields") or {}
            url = article.get("webUrl") or ""
            snippet = fields_obj.get("trailText") or ""
            if include_body and fields_obj.get("bodyText"):
                snippet = (snippet + "\n" + fields_obj["bodyText"])[:1200]
            items.append(
                EvidenceItem(
                    source_id=f"{id_prefix}-{i+1}",
                    outlet="The Guardian",
                    domain=GUARDIAN_DOMAIN,
                    url=url,
                    title=fields_obj.get("headline") or article.get("webTitle") or "",
                    published_at=fields_obj.get("firstPublicationDate")
                    or article.get("webPublicationDate"),
                    snippet=snippet[:800],
                    tool="guardian",
                    publisher_family=publisher_family(url or GUARDIAN_DOMAIN),
                    source_band=source_band(url or GUARDIAN_DOMAIN),
                )
            )
        status = "ok" if items else "empty"
        return items, ToolResult(tool="guardian", status=status, hit_count=len(items))
    except Exception as exc:
        return [], ToolResult(tool="guardian", status="error", detail=str(exc)[:240])
