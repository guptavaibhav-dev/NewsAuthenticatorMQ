"""Adapter base class and the capability gate every source passes through.

The gate exists to keep two very different things apart:

  * a **capability limit** — this source cannot reach that date, that language,
    or cannot run at all because no key is configured; and
  * a **retrieval outcome** — we searched and found nothing.

The old Layer 3 collapsed the first into the second and reported `not_found`
either way, which read to a journalist as "nobody else has this story" when the
truth was "we never looked". Separating them is the whole point of this
rewrite, so the gate lives in the base class and adapters cannot bypass it.

The gate is also asymmetric on purpose. Our own missing metadata never causes a
skip: an unknown publication date is not an old one, and an unknown language is
not a foreign one. Both skip the corresponding check and say so in the report.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import WIRE_SERVICES, Settings
from app.schemas.retrieval import AdapterReport, AdapterStatus, Capability, SearchHit
from app.scoring.urls import canonical_url, publisher_identity


class ArticleContext(BaseModel):
    """Facts about the SUBMITTED article that the capability gate needs.

    Everything here describes the article the journalist gave us, not the pages
    we are going out to find. Getting that backwards would gate every adapter on
    the wrong date.
    """

    published_at: str | None = Field(
        default=None,
        description=(
            "The submitted article's publication date, from Layer 1. None when "
            "unknown — which must never be treated as old. Adapter age gates "
            "are skipped entirely when this is None."
        ),
    )
    article_language: str | None = Field(
        default=None,
        description=(
            "Language of the submitted article. Always None today: no language "
            "detector exists anywhere in the codebase. None means unknown, not "
            "'no language', and disables adapter language gates entirely."
        ),
    )
    canonical_url: str = Field(
        default="",
        description="The submitted article's own canonical URL, for self-matching.",
    )
    publisher_domain: str = Field(
        default="",
        description="Registrable domain of the submitted article.",
    )
    headline: str | None = Field(
        default=None,
        description=(
            "The submitted article's headline, for title-level matching "
            "against retrieved pages. None when Layer 2 found none, which "
            "is also why the existence ladder would be empty."
        ),
    )
    body_hash: str | None = Field(
        default=None,
        description=(
            "Hash of the submitted article's normalised body, from the same "
            "helper adapters use on retrieved pages, so the two are "
            "comparable. None when no body text was extracted — which blocks "
            "duplicate detection rather than proving the article is original."
        ),
    )


class AdapterError(Exception):
    """A source failed in a way worth reporting, with an HTTP status if we got one."""

    def __init__(self, reason: str, http_status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


@dataclass
class _Gate:
    """Outcome of the capability gate: a skip report, or notes to carry forward."""

    report: AdapterReport | None = None
    notes: list[str] = field(default_factory=list)
    # Which checks did not run, as bare names, so the coverage report can
    # aggregate them without parsing the prose in `notes`.
    skipped: list[str] = field(default_factory=list)


_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%dT%H%M%S")


def parse_timestamp(value: Any) -> datetime | None:
    """Tolerantly parse a publication timestamp. None when we cannot."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        base = re.split(r"[+]|\.\d", text)[0]
        for fmt in _ISO_FORMATS:
            try:
                parsed = datetime.strptime(base, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def article_age_days(published_at: Any, *, now: datetime | None = None) -> int | None:
    """Age of the submitted article in days, or None when the date is unknown."""
    parsed = parse_timestamp(published_at)
    if parsed is None:
        return None
    reference = now or datetime.now(timezone.utc)
    return max(0, (reference - parsed).days)


_WIRE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE))
    # Longest first so "Associated Press" is credited before bare "AP", and so
    # the word-boundary guards stop "AP" matching inside "cheap" or "APPLE".
    for name in sorted(WIRE_SERVICES, key=len, reverse=True)
)


def detect_wire_credit(*fields: Any) -> str | None:
    """Find a wire agency credited in a byline or snippet.

    A credit means the text arrived down a wire and is therefore not an
    independent newsroom for corroboration purposes. It is not a quality
    judgement, and its absence does not prove a report is original — many
    outlets simply omit the credit.
    """
    haystack = " ".join(value for value in fields if isinstance(value, str))
    if not haystack.strip():
        return None
    for name, pattern in _WIRE_PATTERNS:
        if pattern.search(haystack):
            return name
    return None


def body_hash(text: Any) -> str | None:
    """Hash of normalised body text, for spotting verbatim reprints."""
    if not isinstance(text, str) or not text.strip():
        return None
    normalised = " ".join(text.split()).lower()
    return f"sha256:{hashlib.sha256(normalised.encode('utf-8')).hexdigest()[:32]}"


def build_hit(
    *,
    adapter: str,
    query: Any,
    url: Any,
    title: Any,
    snippet: Any = None,
    published_at: Any = None,
    byline: Any = None,
    language: Any = None,
    body: Any = None,
    outlet_hint: Any = None,
) -> SearchHit | None:
    """Normalise one source's row into a SearchHit. None when it has no URL.

    Canonicalisation is delegated to the Layer 1 helper so every layer agrees on
    what counts as the same page; reimplementing it here would let dedup drift.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    raw_url = url.strip()
    domain, publisher_id, _is_platform = publisher_identity(raw_url)
    if not domain and isinstance(outlet_hint, str):
        domain, publisher_id, _is_platform = publisher_identity(outlet_hint)
    return SearchHit(
        url=raw_url,
        canonical_url=canonical_url(raw_url),
        title=title.strip() if isinstance(title, str) else "",
        snippet=snippet.strip()[:800] if isinstance(snippet, str) and snippet.strip() else None,
        body_hash=body_hash(body),
        published_at=published_at if isinstance(published_at, str) and published_at else None,
        publisher_domain=domain,
        publisher_id=publisher_id or domain,
        byline=byline.strip() if isinstance(byline, str) and byline.strip() else None,
        wire_credit=detect_wire_credit(byline, snippet),
        source_adapter=adapter,
        query_id=getattr(query, "query_id", ""),
        claim_id=getattr(query, "claim_id", None),
        language=language if isinstance(language, str) and language else None,
    )


class SourceAdapter:
    """One retrieval source. Subclasses implement `_fetch` and nothing else.

    `search` is a template method: it runs the capability gate, calls `_fetch`,
    and turns whatever happens into an AdapterReport. Adapters never raise into
    the orchestrator and never decide their own status, so "ran and found
    nothing" cannot be confused with "could not run".
    """

    name: str = "adapter"
    capabilities: Capability

    def api_key(self, settings: Settings) -> str:
        """The key this adapter needs, or "" when it has none configured."""
        return ""

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], int | None]:
        raise NotImplementedError

    def _gate(self, *, settings: Settings, context: ArticleContext) -> _Gate:
        notes: list[str] = []
        skipped: list[str] = []
        caps = self.capabilities

        # 1. Age. An unknown date is not an old one.
        if caps.max_age_days is None:
            notes.append("no age limit declared")
        else:
            age = article_age_days(context.published_at)
            if age is None:
                skipped.append("age")
                notes.append(
                    "age check skipped: the submitted article has no usable "
                    "publication date, which is not the same as being old"
                )
            elif age > caps.max_age_days:
                return _Gate(
                    report=self._report(
                        # Capability limit, NOT a retrieval outcome. This path
                        # must never produce not_found: we did not search and
                        # found nothing, we were never able to look. Reporting
                        # absence here would read as "no other outlet has this
                        # story" when the truth is "this source cannot reach
                        # that date" — the exact defect this rewrite removes.
                        status="skipped_out_of_range",
                        hits=0,
                        queries_run=0,
                        reason=(
                            f"article is {age} days old; {self.name} reaches back "
                            f"{caps.max_age_days} days"
                        ),
                    )
                )

        # 2. Key.
        if caps.requires_key and not self.api_key(settings):
            return _Gate(
                report=self._report(
                    # Also a capability limit: an operator has not configured a
                    # key. Never not_found — nothing was searched.
                    status="skipped_no_key",
                    hits=0,
                    queries_run=0,
                    reason=f"no API key configured for {self.name}",
                )
            )

        # 3. Language. An unknown language is not a foreign one.
        if caps.languages is None:
            notes.append("no language limit declared")
        elif context.article_language is None:
            skipped.append("language")
            notes.append(
                "language check skipped: the article's language is unknown "
                "(no detector exists), which is not the same as unsupported"
            )
        elif context.article_language not in caps.languages:
            return _Gate(
                report=self._report(
                    # Capability limit again, never not_found.
                    status="skipped_out_of_range",
                    hits=0,
                    queries_run=0,
                    reason=(
                        f"{self.name} searches {', '.join(caps.languages)}; "
                        f"the article is in {context.article_language}"
                    ),
                )
            )

        return _Gate(notes=notes, skipped=skipped)

    def _report(
        self,
        *,
        status: AdapterStatus,
        hits: int,
        queries_run: int,
        reason: str | None = None,
        http_status: int | None = None,
        checks_skipped: list[str] | None = None,
    ) -> AdapterReport:
        return AdapterReport(
            adapter=self.name,
            status=status,
            queries_run=queries_run,
            hits_returned=hits,
            reason=reason,
            checks_skipped=checks_skipped or [],
            http_status=http_status,
        )

    async def search(
        self,
        client: httpx.AsyncClient,
        query: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[SearchHit], AdapterReport]:
        return await self.guarded(
            lambda: self._fetch(client, query, settings=settings, context=context),
            settings=settings,
            context=context,
        )

    async def guarded(
        self,
        fetch: Any,
        *,
        settings: Settings,
        context: ArticleContext,
    ) -> tuple[list[Any], AdapterReport]:
        """Run the gate, then `fetch`, turning any outcome into a report.

        Every way out of an adapter goes through here, so no alternative entry
        point can skip the capability gate or leak an exception into the run.
        """
        gate = self._gate(settings=settings, context=context)
        if gate.report is not None:
            return [], gate.report

        # A check that was skipped still happened, whatever the call does next,
        # so every exit below carries it.
        skipped = gate.skipped
        try:
            rows, http_status = await fetch()
        except AdapterError as exc:
            return [], self._report(
                status="error",
                hits=0,
                queries_run=1,
                reason=exc.reason,
                http_status=exc.http_status,
                checks_skipped=skipped,
            )
        except httpx.HTTPStatusError as exc:
            return [], self._report(
                status="error",
                hits=0,
                queries_run=1,
                reason=f"HTTP {exc.response.status_code}",
                http_status=exc.response.status_code,
                checks_skipped=skipped,
            )
        except httpx.TimeoutException:
            return [], self._report(
                status="error",
                hits=0,
                queries_run=1,
                reason="request timed out",
                checks_skipped=skipped,
            )
        except Exception as exc:  # noqa: BLE001 - nothing may escape into the run
            return [], self._report(
                status="error",
                hits=0,
                queries_run=1,
                reason=str(exc)[:240],
                checks_skipped=skipped,
            )

        # A successful response with no rows is empty, never error: the source
        # worked, it simply has no coverage to offer.
        report = self._report(
            status="ok" if rows else "empty",
            hits=len(rows),
            queries_run=1,
            reason="; ".join(gate.notes) or None,
            http_status=http_status,
            checks_skipped=skipped,
        )
        return rows, report


def raise_for_api_status(response: httpx.Response, *, detail_keys: tuple[str, ...] = ()) -> None:
    """Turn a >=400 response into an AdapterError carrying the status code."""
    if response.status_code < 400:
        return
    message = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in detail_keys:
                if payload.get(key):
                    message = str(payload[key])
                    break
            if not message:
                message = str(payload)[:160]
    except Exception:
        message = response.text[:160]
    raise AdapterError(
        f"HTTP {response.status_code} {message}".strip()[:240], response.status_code
    )
