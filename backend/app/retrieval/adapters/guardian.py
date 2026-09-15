"""Guardian Content API adapter. Ported from app/tools/guardian.py."""

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

ENDPOINT = "https://content.guardianapis.com/search"
GUARDIAN_DOMAIN = "theguardian.com"


class GuardianAdapter(SourceAdapter):
    name = "guardian"

    def __init__(self, page_size: int = 8, include_body: bool = True):
        self.page_size = page_size
        self.include_body = include_body
        self.capabilities = Capability(
            # The Guardian's open archive goes back decades, so no age gate.
            max_age_days=None,
            languages=["en"],
            regions=None,
            # bodyText is requested, so claims can be matched against the body.
            searches_full_text=include_body,
            requires_key=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> GuardianAdapter:
        return cls(**kwargs)

    def api_key(self, settings: Settings) -> str:
        return settings.guardian_api_key

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        fields = "headline,trailText,byline,firstPublicationDate"
        if self.include_body:
            fields += ",bodyText"
        params: dict[str, Any] = {
            "q": (query.query_text or "")[:200],
            "api-key": self.api_key(settings),
            "show-fields": fields,
            "page-size": self.page_size,
            "order-by": "relevance",
        }
        if query.date_from:
            params["from-date"] = query.date_from[:10]
        if query.date_to:
            params["to-date"] = query.date_to[:10]

        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response, detail_keys=("message",))
        results = (response.json().get("response") or {}).get("results") or []

        hits: list[SearchHit] = []
        for article in results:
            fields_obj = article.get("fields") or {}
            body = fields_obj.get("bodyText")
            snippet = fields_obj.get("trailText") or ""
            if body:
                snippet = f"{snippet}\n{body}"[:1200]
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=article.get("webUrl"),
                title=fields_obj.get("headline") or article.get("webTitle"),
                snippet=snippet,
                published_at=(
                    fields_obj.get("firstPublicationDate")
                    or article.get("webPublicationDate")
                ),
                byline=fields_obj.get("byline"),
                language="en",
                body=body,
                outlet_hint=GUARDIAN_DOMAIN,
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code
