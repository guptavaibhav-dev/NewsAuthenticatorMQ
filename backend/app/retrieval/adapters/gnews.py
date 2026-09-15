"""GNews adapter. Ported from the _gnews branch of app/tools/gnews.py."""

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

ENDPOINT = "https://gnews.io/api/v4/search"


class GNewsAdapter(SourceAdapter):
    name = "gnews"

    def __init__(self, max_age_days: int | None = None, page_size: int = 8):
        self.page_size = page_size
        self.capabilities = Capability(
            max_age_days=max_age_days,
            # GNews indexes many languages; we query one at a time but do not
            # claim a limit we have not verified.
            languages=None,
            regions=None,
            searches_full_text=False,
            requires_key=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings, page_size: int = 8) -> GNewsAdapter:
        return cls(max_age_days=settings.gnews_max_age_days, page_size=page_size)

    def api_key(self, settings: Settings) -> str:
        return settings.gnews_api_key

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
            "lang": "en",
            "max": self.page_size,
            "token": self.api_key(settings),
        }
        if query.date_from:
            params["from"] = query.date_from
        if query.date_to:
            params["to"] = query.date_to

        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response, detail_keys=("errors", "message"))
        articles = response.json().get("articles") or []

        hits: list[SearchHit] = []
        for article in articles:
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=article.get("url"),
                title=article.get("title"),
                snippet=article.get("description") or article.get("content"),
                published_at=article.get("publishedAt"),
                language="en",
                outlet_hint=(article.get("source") or {}).get("name"),
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code
