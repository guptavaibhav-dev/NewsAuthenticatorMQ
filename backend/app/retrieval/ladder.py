"""Execution of the existence ladder: exact phrase, then loose, then keywords.

The ladder answers "has this article appeared anywhere else?" and stops at the
first rung that finds anything, so a run does not pay for three searches when
one succeeds. The rung that succeeded becomes the `TitleMatchStrength`, which
records how hard we had to loosen the query — a keyword match is a weaker
statement about sameness than an exact phrase match, and must be labelled that
way rather than presented as an equal find.

The empty ladder is a first-class outcome. Stage 2 emits no existence queries
when Layer 2 had no headline, and that is not an error: it means we never had
an article title to look for. "We never looked" and "we looked everywhere and
found nothing" carry opposite weight for a journalist, so `LadderOutcome` keeps
them apart and neither is ever reported as evidence about the article.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.retrieval.adapters.base import ArticleContext, SourceAdapter
from app.schemas.retrieval import (
    AdapterReport,
    ExistenceSearchOutcome,
    PlannedQuery,
    SearchHit,
    TitleMatchStrength,
)

# The outcome type lives in the schema module because CoverageReport records it;
# this alias keeps the name the ladder code reads best by.
LadderOutcome = ExistenceSearchOutcome

# The planner's template ids, mapped onto how strong a match that rung implies.
_STRENGTH_BY_TEMPLATE: dict[str, TitleMatchStrength] = {
    "exist_exact": "exact",
    "exist_loose": "loose",
    "exist_keyword": "keyword",
}


@dataclass
class LadderResult:
    """Outcome of running the existence ladder."""

    hits: list[SearchHit] = field(default_factory=list)
    title_match_strength: TitleMatchStrength = "none"
    outcome: LadderOutcome = "not_planned"
    attempts_run: list[str] = field(default_factory=list)
    reports: list[AdapterReport] = field(default_factory=list)

    @property
    def searched(self) -> bool:
        """True when at least one rung actually ran."""
        return self.outcome != "not_planned"


def existence_queries(queries: Any) -> list[PlannedQuery]:
    """The existence rungs from a plan, in attempt order.

    Tolerates a ladder of zero rungs (no headline) or two (a headline that was
    entirely stopwords, so the keyword rung was never built). Neither is an
    error and neither is padded out with an invented query.
    """
    rungs = [q for q in queries or () if getattr(q, "kind", None) == "existence"]
    return sorted(rungs, key=lambda q: getattr(q, "attempt", 1))


async def run_existence_ladder(
    client: httpx.AsyncClient,
    queries: Any,
    adapters: list[SourceAdapter],
    *,
    settings: Settings,
    context: ArticleContext,
) -> LadderResult:
    """Run the ladder, stopping at the first rung that returns hits."""
    rungs = existence_queries(queries)
    if not rungs:
        # Nothing to run. Deliberately distinguishable from an exhausted ladder.
        return LadderResult(outcome="not_planned")

    result = LadderResult(outcome="exhausted")
    for rung in rungs:
        result.attempts_run.append(rung.query_id)
        # Rungs are sequential by design — the whole point is to stop early —
        # but the adapters within one rung have no reason to wait for each
        # other. Adapters never raise, so gather cannot be poisoned here.
        outcomes = await asyncio.gather(
            *(
                adapter.search(client, rung, settings=settings, context=context)
                for adapter in adapters
            )
        )
        rung_hits: list[SearchHit] = []
        for hits, report in outcomes:
            result.reports.append(report)
            rung_hits.extend(hits)
        if rung_hits:
            result.hits = rung_hits
            result.title_match_strength = _STRENGTH_BY_TEMPLATE.get(
                getattr(rung, "template_id", ""), "keyword"
            )
            result.outcome = "matched"
            return result

    # Every rung ran and found nothing. title_match_strength stays "none".
    return result
