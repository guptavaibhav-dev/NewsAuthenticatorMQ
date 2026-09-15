"""NewsAPI.org adapter. Ported from app/tools/newsapi.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import Settings
from app.retrieval.adapters.base import (
    ArticleContext,
    SourceAdapter,
    build_hit,
    raise_for_api_status,
)
from app.schemas.retrieval import Capability, SearchHit

ENDPOINT = "https://newsapi.org/v2/everything"

# 14 of the ISO-639-1 codes NewsAPI documents for /v2/everything.
NEWSAPI_LANGUAGES = [
    "ar", "de", "en", "es", "fr", "he", "it",
    "nl", "no", "pt", "ru", "sv", "ud", "zh",
]


def clamp_from_date(date_from: str, max_age_days: int) -> str:
    """Never ask NewsAPI for a window older than the plan allows.

    The plan floor is applied to the query, not used to reject the article —
    the capability gate has already decided whether it is worth asking at all.
    """
    floor = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date()
    try:
        requested = datetime.fromisoformat(date_from[:10]).date()
    except ValueError:
        return floor.isoformat()
    return floor.isoformat() if requested < floor else date_from[:10]


class NewsApiAdapter(SourceAdapter):
    name = "newsapi"

    def __init__(self, max_age_days: int | None = None, page_size: int = 10):
        self.page_size = page_size
        self.capabilities = Capability(
            max_age_days=max_age_days,
            languages=NEWSAPI_LANGUAGES,
            regions=None,
            searches_full_text=False,
            requires_key=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings, page_size: int = 10) -> NewsApiAdapter:
        return cls(max_age_days=settings.newsapi_max_age_days, page_size=page_size)

    def api_key(self, settings: Settings) -> str:
        return settings.newsapi_key

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        params: dict[str, Any] = {
            "q": (query.query_text or "")[:500],
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": self.page_size,
            "apiKey": self.api_key(settings),
        }
        if query.date_from and self.capabilities.max_age_days is not None:
            params["from"] = clamp_from_date(query.date_from, self.capabilities.max_age_days)
        elif query.date_from:
            params["from"] = query.date_from[:10]
        if query.date_to:
            params["to"] = query.date_to[:10]
        if getattr(query, "kind", None) == "existence":
            params["searchIn"] = "title"

        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response, detail_keys=("message", "code"))
        articles = response.json().get("articles") or []

        hits: list[SearchHit] = []
        for article in articles:
            source = article.get("source") or {}
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=article.get("url"),
                title=article.get("title"),
                snippet=article.get("description") or article.get("content"),
                published_at=article.get("publishedAt"),
                byline=article.get("author"),
                language="en",
                outlet_hint=source.get("name"),
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code
