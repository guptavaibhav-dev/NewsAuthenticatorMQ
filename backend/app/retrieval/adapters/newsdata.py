"""Newsdata.io adapter. Ported from the _newsdata branch of app/tools/gnews.py."""

from __future__ import annotations

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

ENDPOINT = "https://newsdata.io/api/1/news"


class NewsdataAdapter(SourceAdapter):
    name = "newsdata"

    def __init__(self, max_age_days: int | None = None, page_size: int = 8):
        self.page_size = page_size
        self.capabilities = Capability(
            max_age_days=max_age_days,
            languages=None,
            # Newsdata's selling point over NewsAPI is wider country coverage,
            # which is why it is kept alongside rather than as a duplicate.
            regions=None,
            searches_full_text=False,
            requires_key=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings, page_size: int = 8) -> NewsdataAdapter:
        return cls(max_age_days=settings.newsdata_max_age_days, page_size=page_size)

    def api_key(self, settings: Settings) -> str:
        return settings.newsdata_api_key

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        params: dict[str, Any] = {
            "q": (query.query_text or "")[:200],
            "language": "en",
            "apikey": self.api_key(settings),
        }
        if query.date_from:
            params["from_date"] = query.date_from[:10]
        if query.date_to:
            params["to_date"] = query.date_to[:10]

        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response, detail_keys=("message", "results"))
        results = response.json().get("results") or []

        hits: list[SearchHit] = []
        for article in results[: self.page_size]:
            creators = article.get("creator")
            byline = ", ".join(creators) if isinstance(creators, list) else creators
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=article.get("link"),
                title=article.get("title"),
                snippet=article.get("description") or article.get("content"),
                published_at=article.get("pubDate"),
                byline=byline,
                language=article.get("language"),
                outlet_hint=article.get("source_id") or article.get("source_name"),
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code
