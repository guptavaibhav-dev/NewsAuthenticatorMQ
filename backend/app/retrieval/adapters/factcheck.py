"""Google Fact Check Tools adapter. Ported from app/tools/factcheck.py.

Returns ClaimReview records published by fact-checking organisations. Recording
a reviewer's rating is not adopting it: the rating belongs to the reviewer, is
kept verbatim, and is never mapped onto our own output.
"""

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
from app.schemas.retrieval import AdapterReport, Capability, FactCheckRecord, SearchHit

ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


class GoogleFactCheckAdapter(SourceAdapter):
    name = "google_factcheck"

    def __init__(self, page_size: int = 8):
        self.page_size = page_size
        self.capabilities = Capability(
            # ClaimReview markup has no archive horizon.
            max_age_days=None,
            languages=["en"],
            regions=None,
            searches_full_text=False,
            requires_key=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings, page_size: int = 8) -> GoogleFactCheckAdapter:
        return cls(page_size=page_size)

    def api_key(self, settings: Settings) -> str:
        return settings.factcheck_key

    async def _claims(
        self, client: httpx.AsyncClient, query: Any, *, settings: Settings
    ) -> tuple[list[dict], int | None]:
        params = {
            "query": (query.query_text or "")[:300],
            "pageSize": self.page_size,
            "key": self.api_key(settings),
            "languageCode": "en",
        }
        response = await client.get(ENDPOINT, params=params)
        raise_for_api_status(response, detail_keys=("error", "message"))
        claims = response.json().get("claims") or []
        return [row for row in claims if isinstance(row, dict)], response.status_code

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        claims, http_status = await self._claims(client, query, settings=settings)
        hits: list[SearchHit] = []
        for claim in claims:
            review = (claim.get("claimReview") or [{}])[0]
            publisher = (review.get("publisher") or {}).get("name")
            hit = build_hit(
                adapter=self.name,
                query=query,
                url=review.get("url"),
                title=review.get("title") or claim.get("text"),
                # The reviewer's own wording, kept as the snippet so nothing
                # downstream has to re-infer what they concluded.
                snippet=claim.get("text"),
                published_at=review.get("reviewDate") or claim.get("claimDate"),
                byline=publisher,
                language="en",
                outlet_hint=publisher,
            )
            if hit:
                hits.append(hit)
        return hits, http_status

    async def _records(
        self, client: httpx.AsyncClient, query: Any, *, settings: Settings
    ) -> tuple[list[FactCheckRecord], int | None]:
        claims, http_status = await self._claims(client, query, settings=settings)
        claim_id = getattr(query, "claim_id", None) or ""
        records: list[FactCheckRecord] = []
        for claim in claims:
            review = (claim.get("claimReview") or [{}])[0]
            url = review.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            records.append(
                FactCheckRecord(
                    claim_id=claim_id,
                    reviewer_name=(review.get("publisher") or {}).get("name") or "",
                    # The reviewer's verdict, verbatim and unmapped.
                    rating_text=review.get("textualRating") or "",
                    review_url=url.strip(),
                    reviewed_claim_text=claim.get("text") or "",
                )
            )
        return records, http_status

    async def search_records(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[FactCheckRecord], AdapterReport]:
        """Same search, shaped as FactCheckRecord for RetrievalPayload.factchecks.

        Routed through `guarded` so this door cannot bypass the capability gate
        or leak an exception, exactly as `search` cannot.
        """
        return await self.guarded(
            lambda: self._records(client, query, settings=settings),
            settings=settings,
            context=context,
        )
