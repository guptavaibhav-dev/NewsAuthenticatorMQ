"""Wikipedia / Wikidata adapter. Ported from app/tools/wikipedia.py.

Entity lookups only. A hit means the name exists in a public reference work; a
miss means it does not exist *there*, which is usually obscurity, novelty or a
spelling variant. Neither outcome is evidence about the article.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import APP_USER_AGENT, Settings
from app.retrieval.adapters.base import (
    ArticleContext,
    SourceAdapter,
    build_hit,
    raise_for_api_status,
)
from app.schemas.retrieval import Capability, SearchHit

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
WIKIDATA_ENDPOINT = "https://www.wikidata.org/w/api.php"

WIKI_HEADERS = {"User-Agent": APP_USER_AGENT, "Accept": "application/json"}

_TAG = re.compile(r"<[^>]+>")


class WikipediaAdapter(SourceAdapter):
    name = "wikipedia"

    def __init__(self, limit: int = 1):
        self.limit = limit
        self.capabilities = Capability(
            max_age_days=None,
            # We query the English editions only. That is a limit on our reach,
            # not a view about entities documented in other languages.
            languages=["en"],
            regions=None,
            searches_full_text=False,
            requires_key=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings, limit: int = 1) -> WikipediaAdapter:
        return cls(limit=limit)

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        term = (query.query_text or "").strip()
        if not term:
            return [], None

        response = await client.get(
            WIKIPEDIA_ENDPOINT,
            params={
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srlimit": self.limit,
                "format": "json",
                "origin": "*",
            },
            headers=WIKI_HEADERS,
        )
        raise_for_api_status(response)
        rows = ((response.json().get("query") or {}).get("search") or [])

        hits: list[SearchHit] = []
        for row in rows:
            title = row.get("title")
            if not isinstance(title, str) or not title:
                continue
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                title=title,
                snippet=_TAG.sub("", row.get("snippet") or ""),
                language="en",
            )
            if hit:
                hits.append(hit)
        if hits:
            return hits, response.status_code

        wikidata, status = await self._wikidata(client, query, term)
        return wikidata, status or response.status_code

    async def _wikidata(
        self, client: httpx.AsyncClient, query: Any, term: str
    ) -> tuple[list[SearchHit], int | None]:
        """Fall back to Wikidata, which covers entities with no article yet."""
        response = await client.get(
            WIKIDATA_ENDPOINT,
            params={
                "action": "wbsearchentities",
                "search": term,
                "language": "en",
                "format": "json",
                "limit": self.limit,
                "origin": "*",
            },
            headers=WIKI_HEADERS,
        )
        raise_for_api_status(response)
        rows = response.json().get("search") or []
        hits: list[SearchHit] = []
        for row in rows:
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=row.get("concepturi") or row.get("url"),
                title=row.get("label"),
                snippet=row.get("description"),
                language="en",
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code
