"""Distinct documents, distinct sources, and an honest account of our reach.

This module carries the central argument of the layer: **volume is not
corroboration**. A single wire report can surface as fifty pages under fifty
mastheads, and counting pages would present that as fifty confirmations when it
is one newsroom's work republished. Two numbers therefore exist and are never
allowed to merge:

  `document_count`            how many distinct pages we retrieved.
  `independent_source_count`  how many genuinely separate newsrooms are behind
                              them. The only one that supports corroboration.

`dedupe` produces the first, `resolve_independence` the second, and the split
between them is load-bearing. Deduping removes *the same page seen twice* — an
AMP variant, a tracking-parameter twin, the same URL returned by two adapters.
It deliberately does NOT collapse one wire story across twenty papers: those are
twenty real documents, and flattening them here would hide the syndication that
`resolve_independence` exists to expose. Collapsing at the wrong stage would
make the count look honest while destroying the evidence for it.

Nothing in this module judges truth. Grouping two outlets says their text shares
an origin, not that either is right; leaving an outlet ungrouped says we found
no evidence of shared origin, not that its reporting is sound.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.retrieval.adapters.base import ArticleContext
from app.retrieval.ladder import LadderResult
from app.schemas.retrieval import (
    AdapterReport,
    CoverageReport,
    IndependentSource,
    MergeReason,
    ExistenceClass,
    RetrievalPayload,
    SearchHit,
)
from app.scoring.urls import grouping_url, registrable_domain

_OWNERSHIP_PATH = Path(__file__).resolve().parent.parent / "data" / "publisher_ownership.json"

# Word-level shingle width. Five is long enough that ordinary shared phrasing
# ("the government said on Tuesday") does not register as a duplicate.
SHINGLE_SIZE = 5

# Same page seen twice, under one publisher. Strict, because a false merge here
# deletes a document from the count entirely.
DUPLICATE_JACCARD = 0.9

# One wire story across mastheads. Looser, because papers trim and re-top wire
# copy while republishing it, and the wire credit is already strong evidence.
WIRE_JACCARD = 0.8

# A verbatim republication with no wire credit to explain it.
REPRINT_JACCARD = 0.9

# Precedence for why a group was collapsed. Lower binds first: a page that is
# both wire copy and stablemate is reported as wire copy, because the wire is
# the more specific and more consequential explanation.
_MERGE_PRECEDENCE: tuple[MergeReason, ...] = ("same_wire", "same_owner", "reprint")

_WORD = re.compile(r"[a-z0-9]+")

# How many outlets a merge_evidence string names before summarising the rest.
_EVIDENCE_OUTLET_LIMIT = 6


def _words(text: Any) -> list[str]:
    return _WORD.findall(text.lower()) if isinstance(text, str) else []


def shingles(text: Any, size: int = SHINGLE_SIZE) -> frozenset[tuple[str, ...]]:
    """Overlapping word n-grams of `text`.

    Text shorter than `size` degrades to a single shingle of the whole thing,
    so two identical short snippets still compare as identical rather than
    silently scoring zero.
    """
    words = _words(text)
    if not words:
        return frozenset()
    if len(words) < size:
        return frozenset({tuple(words)})
    return frozenset(
        tuple(words[i : i + size]) for i in range(len(words) - size + 1)
    )


def shingle_jaccard(a: Any, b: Any) -> float:
    """Jaccard overlap of two texts' shingle sets."""
    sa, sb = (a if isinstance(a, frozenset) else shingles(a)), (
        b if isinstance(b, frozenset) else shingles(b)
    )
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def comparable_text(hit: SearchHit) -> str:
    """The most body-like text an adapter gave us for this page.

    Most news APIs return a headline and a description, not article bodies, so
    this is usually title plus lead. Similarity computed over a lead is weaker
    evidence of duplication than similarity over a full body, which is why
    identical `body_hash` values short-circuit ahead of it wherever both exist.
    """
    return f"{hit.title} {hit.snippet or ''}".strip()


def metadata_completeness(hit: SearchHit) -> int:
    """How much we know about a page, for choosing a group's representative.

    Completeness is about how useful the record is to a journalist — does it
    name an author, a date, a wire credit — and says nothing about the quality
    of the publication.
    """
    fields = (hit.title, hit.snippet, hit.body_hash, hit.published_at, hit.byline,
              hit.wire_credit, hit.language)
    return sum(1 for value in fields if value)


def _representative_key(hit: SearchHit) -> tuple:
    """Most complete first, then a stable tiebreak so runs are reproducible."""
    return (-metadata_completeness(hit), hit.canonical_url, hit.url)


def _best(hits: list[SearchHit]) -> SearchHit:
    return sorted(hits, key=_representative_key)[0]


# --- ownership map -----------------------------------------------------------


@lru_cache
def ownership_map() -> dict[str, str]:
    """Domain -> parent group, loaded from data at runtime.

    A missing or malformed file yields an empty map rather than an exception:
    every publisher then counts as independent, which overstates corroboration
    in a way a reader can see, instead of taking the layer down.
    """
    try:
        raw = json.loads(_OWNERSHIP_PATH.read_text(encoding="utf-8"))
        table = raw.get("ownership") if isinstance(raw, dict) else None
        if not isinstance(table, dict):
            return {}
        return {
            str(domain).lower(): str(group)
            for domain, group in table.items()
            if domain and group
        }
    except Exception:
        return {}


def parent_group(hit_or_domain: Any) -> str | None:
    """Parent group for a publisher, or None when we do not know of one.

    None means *absent from our map*, never *independently owned*. The two are
    indistinguishable from here, and the map is documented as incomplete, so an
    unknown domain is left standing alone rather than guessed at.
    """
    if isinstance(hit_or_domain, SearchHit):
        candidates = [hit_or_domain.publisher_domain, hit_or_domain.publisher_id,
                      hit_or_domain.url]
    else:
        candidates = [hit_or_domain]

    table = ownership_map()
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        key = candidate.strip().lower()
        if key in table:
            return table[key]
        domain = registrable_domain(key)
        if domain and domain in table:
            return table[domain]
    return None


# --- E1: dedupe --------------------------------------------------------------


def dedupe(hits: Iterable[SearchHit]) -> list[SearchHit]:
    """Collapse the same page seen more than once. Returns distinct DOCUMENTS.

    Two passes: exact `canonical_url` equality, then near-identical text —
    but the second pass only ever compares pages from the SAME publisher.
    That restriction is the point. Twenty papers running one Reuters story have
    near-identical text and must survive here as twenty documents, so that
    `resolve_independence` can collapse them to one *source* and say why. If
    dedupe swallowed them, the count would look right for the wrong reason and
    the journalist would never see the syndication.
    """
    rows = [hit for hit in hits if isinstance(hit, SearchHit)]

    by_url: dict[str, list[SearchHit]] = {}
    for hit in rows:
        by_url.setdefault(grouping_url(hit), []).append(hit)
    unique = [_best(group) for group in by_url.values()]

    kept: list[SearchHit] = []
    shingle_cache: dict[int, frozenset[tuple[str, ...]]] = {}
    for hit in unique:
        shingle_cache[id(hit)] = shingles(comparable_text(hit))
        duplicate_of: int | None = None
        for index, existing in enumerate(kept):
            # Different mastheads are different documents, whatever the text.
            if existing.publisher_id != hit.publisher_id:
                continue
            if hit.body_hash and existing.body_hash:
                if hit.body_hash == existing.body_hash:
                    duplicate_of = index
                    break
                continue
            if shingle_jaccard(shingle_cache[id(hit)], shingle_cache[id(existing)]) >= (
                DUPLICATE_JACCARD
            ):
                duplicate_of = index
                break
        if duplicate_of is None:
            kept.append(hit)
        else:
            kept[duplicate_of] = _best([kept[duplicate_of], hit])
    return kept


# --- E2: independence --------------------------------------------------------


class _Union:
    """Minimal union-find, recording why each merge happened."""

    def __init__(self, size: int):
        self.parent = list(range(size))
        self.reasons: dict[int, set[MergeReason]] = {}

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int, reason: MergeReason) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            # Already one group. The earlier, higher-precedence reason stands;
            # this is how a wire merge beats an ownership merge on the same pair.
            return False
        root, other = (ra, rb) if ra <= rb else (rb, ra)
        self.parent[other] = root
        merged = self.reasons.pop(other, set()) | self.reasons.get(root, set())
        merged.add(reason)
        self.reasons[root] = merged
        return True


def _same_wire(a: SearchHit, b: SearchHit, sa, sb) -> bool:
    if not a.wire_credit or not b.wire_credit:
        return False
    if a.wire_credit.strip().lower() != b.wire_credit.strip().lower():
        return False
    if a.body_hash and b.body_hash and a.body_hash == b.body_hash:
        return True
    return shingle_jaccard(sa, sb) >= WIRE_JACCARD


def _same_owner(a: SearchHit, b: SearchHit) -> bool:
    group_a, group_b = parent_group(a), parent_group(b)
    return group_a is not None and group_a == group_b


def _reprint(a: SearchHit, b: SearchHit, sa, sb) -> bool:
    if a.wire_credit or b.wire_credit:
        # A credited wire story is same_wire's business, not a bare reprint.
        return False
    if a.publisher_id == b.publisher_id:
        return False
    if a.body_hash and b.body_hash:
        return a.body_hash == b.body_hash
    return shingle_jaccard(sa, sb) >= REPRINT_JACCARD


def _evidence(reason: MergeReason, members: list[SearchHit]) -> str:
    """Say which outlets were collapsed and on what grounds.

    A smaller number on its own is not checkable. The journalist has to be able
    to disagree with a merge, which means seeing the outlets and the reason.
    """
    if len(members) == 1:
        return "Stands alone; no other retrieved page shares its text or owner."

    outlets = sorted({hit.publisher_domain or hit.publisher_id for hit in members})
    shown = ", ".join(outlets[:_EVIDENCE_OUTLET_LIMIT])
    if len(outlets) > _EVIDENCE_OUTLET_LIMIT:
        shown += f", and {len(outlets) - _EVIDENCE_OUTLET_LIMIT} more"

    if reason == "same_wire":
        wire = next((hit.wire_credit for hit in members if hit.wire_credit), "a wire")
        return (
            f"{len(members)} pages across {len(outlets)} outlets all credit {wire} "
            f"and carry near-identical text: one wire report republished, not "
            f"{len(outlets)} independent confirmations ({shown})."
        )
    if reason == "same_owner":
        group = next((g for g in (parent_group(h) for h in members) if g), "one group")
        return (
            f"{len(members)} pages from mastheads under the same parent group "
            f"({group}), counted once ({shown})."
        )
    if reason == "reprint":
        return (
            f"{len(members)} pages carry near-identical text under different "
            f"mastheads with no wire credit to explain it, so they are treated "
            f"as one report republished ({shown})."
        )
    return f"{len(members)} pages grouped ({shown})."


def resolve_independence(documents: Iterable[SearchHit]) -> list[IndependentSource]:
    """Group documents that are NOT independent of one another.

    Precedence is same_wire, then same_owner, then reprint, applied in that
    order so the most specific explanation wins. Anything left unmatched stands
    alone with merge_reason "none" — including every publisher missing from the
    ownership map, which stays independent rather than being guessed at.
    """
    rows = [hit for hit in documents if isinstance(hit, SearchHit)]
    if not rows:
        return []

    cached = [shingles(comparable_text(hit)) for hit in rows]
    union = _Union(len(rows))

    for reason in _MERGE_PRECEDENCE:
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if reason == "same_wire":
                    matched = _same_wire(a, b, cached[i], cached[j])
                elif reason == "same_owner":
                    matched = _same_owner(a, b)
                else:
                    matched = _reprint(a, b, cached[i], cached[j])
                if matched:
                    union.union(i, j, reason)

    grouped: dict[int, list[int]] = {}
    for index in range(len(rows)):
        grouped.setdefault(union.find(index), []).append(index)

    sources: list[IndependentSource] = []
    for order, root in enumerate(sorted(grouped, key=lambda r: min(grouped[r]))):
        members = [rows[i] for i in grouped[root]]
        reasons = union.reasons.get(root, set())
        reason: MergeReason = next(
            (r for r in _MERGE_PRECEDENCE if r in reasons), "none"
        )
        representative = _best(members)
        sources.append(
            IndependentSource(
                source_id=f"src_{order}",
                representative_url=representative.url,
                member_urls=[grouping_url(hit) for hit in members],
                publisher_ids=sorted({hit.publisher_id for hit in members}),
                merge_reason=reason,
                merge_evidence=_evidence(reason, members),
            )
        )
    return sources


# --- E4: coverage ------------------------------------------------------------


@dataclass
class PlanCoverage:
    """What stage 2's planner managed to build, carried into the report."""

    claims_total: int = 0
    claims_searched: list[str] | None = None
    claims_skipped: list[str] | None = None
    fields_missing: list[str] | None = None
    existence_rungs_planned: int = 0
    keyword_rung_skipped: bool = False


def _ran(report: AdapterReport) -> bool:
    """True when the adapter actually issued a query."""
    return report.status in {"ok", "empty", "error"}


def build_coverage_report(
    *,
    adapter_reports: Iterable[AdapterReport],
    adapters: Iterable[Any],
    context: ArticleContext,
    ladder: LadderResult,
    plan: PlanCoverage,
    scoring_fields_missing: Iterable[str] = (),
    now: datetime | None = None,
) -> CoverageReport:
    """Assemble the honesty record for the run.

    Three separate ways a run can be narrower than it looks all land here, and
    all three stay distinguishable without counting planned_queries:
    `capability_notes` says which checks never ran and why, `existence_search`
    separates "never looked" from "looked and found nothing", and
    `existence_rungs_planned` with `existence_keyword_rung_skipped` exposes a
    headline that was too thin to build the broadest query from.
    """
    reports = list(adapter_reports)
    by_name = {getattr(a, "name", ""): a for a in adapters}

    notes: list[str] = []
    for report in reports:
        if report.checks_skipped and report.reason:
            notes.append(f"{report.adapter}: {report.reason}")
    # Deduplicated because each adapter reports the same note once per query.
    notes = sorted(set(notes))

    languages: set[str] = set()
    age_limits: list[int | None] = []
    for report in reports:
        adapter = by_name.get(report.adapter)
        caps = getattr(adapter, "capabilities", None)
        if adapter is None or caps is None or not _ran(report):
            continue
        # "any" rather than an invented list: an adapter with no declared limit
        # searched every language, and naming only the ones we know of would
        # under-report our reach as badly as over-reporting it.
        languages.update(caps.languages or ["any"])
        age_limits.append(caps.max_age_days)

    earliest: str | None = None
    if age_limits and all(limit is not None for limit in age_limits):
        reference = now or datetime.now(timezone.utc)
        deepest = max(limit for limit in age_limits if limit is not None)
        earliest = (reference - timedelta(days=deepest)).date().isoformat()

    missing = sorted({*(scoring_fields_missing or ()), *(plan.fields_missing or ())})

    return CoverageReport(
        claims_total=plan.claims_total,
        claims_searched=list(plan.claims_searched or []),
        claims_skipped=list(plan.claims_skipped or []),
        article_language=context.article_language,
        # False whenever the language is unknown, so an unfiltered search is
        # never presented as a filtered one.
        language_checks_applied=(
            context.article_language is not None
            and any(
                getattr(getattr(a, "capabilities", None), "languages", None) is not None
                for a in by_name.values()
            )
        ),
        languages_covered=sorted(languages),
        earliest_reachable_date=earliest,
        adapters=reports,
        capability_notes=notes,
        existence_search=ladder.outcome,
        existence_rungs_planned=plan.existence_rungs_planned,
        existence_keyword_rung_skipped=plan.keyword_rung_skipped,
        scoring_fields_missing=missing,
    )


# --- existence classification ------------------------------------------------


def _normalise_title(title: Any) -> str:
    return " ".join(_words(title))


def classify_existence(
    *,
    documents: list[SearchHit],
    sources: list[IndependentSource],
    ladder: LadderResult,
    context: ArticleContext,
    adapter_reports: Iterable[AdapterReport] = (),
) -> ExistenceClass:
    """Did we find the article itself somewhere else, and how sure are we?

    Ordered most to least specific. `not_found` and `out_of_range` are both
    coverage outcomes and neither is evidence the article is false: the first
    means we searched and came back empty, the second that we were never able
    to look.
    """
    if context.canonical_url:
        for hit in documents:
            if hit.canonical_url and hit.canonical_url == context.canonical_url:
                return "exact_url"

    wire_members = {
        url
        for source in sources
        if source.merge_reason == "same_wire"
        for url in source.member_urls
    }

    title = _normalise_title(context.headline)
    matches = [
        hit
        for hit in documents
        if (title and _normalise_title(hit.title) == title)
        or (context.body_hash and hit.body_hash == context.body_hash)
    ]
    for hit in matches:
        if grouping_url(hit) in wire_members:
            return "syndicated"
    for hit in matches:
        if context.body_hash and hit.body_hash == context.body_hash:
            return "near_duplicate"
    if matches:
        return "title_match"

    if ladder.outcome == "matched" and ladder.title_match_strength in {"exact", "loose"}:
        # The exact-phrase or loose-phrase title rung found pages. Weaker than a
        # normalised title equality, but still a title-level match.
        return "title_match"

    reports = list(adapter_reports)
    nothing_ran = bool(reports) and not any(_ran(report) for report in reports)
    if nothing_ran or ladder.outcome == "not_planned":
        # We never got to look: every adapter was skipped, or there was no
        # headline to search for. Distinct from not_found, which means we did.
        return "out_of_range"
    return "not_found"


def build_payload(
    *,
    hits: Iterable[SearchHit],
    ladder: LadderResult,
    context: ArticleContext,
    coverage: CoverageReport,
    planned_queries: Iterable[Any] = (),
    planner_model: str | None = None,
    planner_template_version: str = "",
    ranking_method: str = "",
    ranking_engine_name: str = "",
    factchecks: Iterable[Any] = (),
    entity_grounding: Iterable[Any] = (),
) -> RetrievalPayload:
    """Run dedupe and independence, then assemble the layer's output.

    `hits` are deduped here rather than trusted to have been deduped already,
    because dedupe is idempotent and the alternative is a caller that forgets.
    `document_count` and `independent_source_count` are not passed in at all:
    RetrievalPayload derives both from the lists they summarise, so a count can
    never drift from its evidence.
    """
    documents = dedupe(hits)
    sources = resolve_independence(documents)
    return RetrievalPayload(
        planned_queries=list(planned_queries),
        planner_model=planner_model,
        planner_template_version=planner_template_version,
        documents=documents,
        independent_sources=sources,
        existence_class=classify_existence(
            documents=documents,
            sources=sources,
            ladder=ladder,
            context=context,
            adapter_reports=coverage.adapters,
        ),
        title_match_strength=ladder.title_match_strength,
        factchecks=list(factchecks),
        entity_grounding=list(entity_grounding),
        ranking_method=ranking_method,
        ranking_engine_name=ranking_engine_name,
        coverage=coverage,
    )
