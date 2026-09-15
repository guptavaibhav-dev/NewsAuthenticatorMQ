"""GDELT DOC 2.0 adapter. New in this stage — no key, multilingual, noisy.

GDELT is the widest net available without an API key, which makes it valuable
precisely when the keyed sources report skipped_no_key. It is also the noisiest:
it indexes aggregators, syndication and low-quality republishers alongside
original reporting, so its hits lean heavily on the independence collapsing in
stage 4 and must not be read as breadth of corroboration on their own.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.retrieval.adapters.base import (
    AdapterError,
    ArticleContext,
    SourceAdapter,
    build_hit,
    parse_timestamp,
    raise_for_api_status,
)
from app.schemas.retrieval import Capability, SearchHit

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

_GDELT_STAMP = "%Y%m%d%H%M%S"


def _stamp(value: str | None, *, end_of_day: bool) -> str | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    if len(value or "") <= 10:
        parsed = parsed.replace(
            hour=23 if end_of_day else 0,
            minute=59 if end_of_day else 0,
            second=59 if end_of_day else 0,
        )
    return parsed.strftime(_GDELT_STAMP)


class GdeltAdapter(SourceAdapter):
    name = "gdelt"

    def __init__(self, max_records: int = 25):
        self.max_records = max_records
        self.capabilities = Capability(
            # GDELT's DOC index starts in 2017, deeper than any article this
            # tool realistically sees, so no age gate is applied.
            max_age_days=None,
            # Genuinely multilingual: no language gate.
            languages=None,
            regions=None,
            searches_full_text=False,
            requires_key=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> GdeltAdapter:
        return cls(max_records=settings.gdelt_max_records)

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        params: dict[str, Any] = {
            "query": (query.query_text or "")[:200],
            "mode": "ArtList",
            "format": "json",
            "maxrecords": self.max_records,
            "sort": "HybridRel",
        }
        start = _stamp(query.date_from, end_of_day=False)
        end = _stamp(query.date_to, end_of_day=True)
        if start:
            params["startdatetime"] = start
        if end:
            params["enddatetime"] = end

        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response)
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            # GDELT answers malformed queries with plain text and a 200. That is
            # our query's problem, not evidence about the article.
            raise AdapterError(
                f"GDELT returned non-JSON: {response.text[:120]}", response.status_code
            ) from None
        articles = (payload or {}).get("articles") or []

        hits: list[SearchHit] = []
        for article in articles:
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=article.get("url"),
                title=article.get("title"),
                snippet=None,
                published_at=_iso(article.get("seendate")),
                # GDELT reports language as a name ("English"), not an ISO code.
                # Passed through unmapped rather than guessed at.
                language=article.get("language"),
                outlet_hint=article.get("domain"),
            )
            if hit:
                hits.append(hit)
        return hits, response.status_code


def _iso(seendate: Any) -> str | None:
    parsed = parse_timestamp(seendate)
    return parsed.isoformat() if parsed else None
