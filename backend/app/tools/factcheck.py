from __future__ import annotations

import httpx

from app.config import Settings
from app.schemas.envelope import FactCheckItem, ToolResult


async def search_factchecks(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    query: str,
    page_size: int = 8,
) -> tuple[list[FactCheckItem], ToolResult]:
    key = settings.factcheck_key
    if not key:
        return [], ToolResult(
            tool="factcheck",
            status="skipped",
            detail="FACTCHECK_API_KEY / GOOGLE_API_KEY not set",
        )
    if not query:
        return [], ToolResult(tool="factcheck", status="empty", detail="empty query")
    try:
        response = await client.get(
            "https://factchecktools.googleapis.com/v1alpha1/claims:search",
            params={"query": query[:300], "pageSize": page_size, "key": key, "languageCode": "en"},
        )
        response.raise_for_status()
        claims = response.json().get("claims") or []
        items: list[FactCheckItem] = []
        for claim in claims:
            reviews = claim.get("claimReview") or []
            review = reviews[0] if reviews else {}
            publisher = (review.get("publisher") or {}).get("name")
            items.append(
                FactCheckItem(
                    claim_text=claim.get("text") or "",
                    textual_rating=review.get("textualRating"),
                    publisher=publisher,
                    url=review.get("url"),
                    review_date=review.get("reviewDate") or claim.get("claimDate"),
                )
            )
        return items, ToolResult(
            tool="factcheck", status="ok" if items else "empty", hit_count=len(items)
        )
    except Exception as exc:
        return [], ToolResult(tool="factcheck", status="error", detail=str(exc)[:240])
