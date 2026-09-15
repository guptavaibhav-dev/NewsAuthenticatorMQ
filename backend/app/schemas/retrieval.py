"""Data contracts for Layer 3 — Retrieval and Independence.

Layer 3 finds out what else has been published about an article and how many
genuinely separate newsrooms are behind it. It does not decide whether the
article is true.

Two rules run through every model here:

1. Reach is not evidence. If an adapter cannot cover an article's date or
   language, if a key is missing, or if a search simply returns nothing, that
   is a gap in what we can see. It is never a signal that the story is false.
   Statuses and counts in this module record coverage, not verdicts.
2. Volume is not corroboration. Syndication means one wire report can appear
   as fifty pages. `document_count` is a page count; only
   `independent_source_count` speaks to corroboration.

This module intentionally imports nothing from `envelope.py` so the two can be
evolved separately. `ExistenceClass` lives here: the coarser five-member type
that used to sit on `envelope.py` was deleted in stage 6.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ExistenceClass = Literal[
    "exact_url",
    "title_match",
    "near_duplicate",
    "syndicated",
    "not_found",
    "out_of_range",
]
"""Whether we found the article itself somewhere else.

- exact_url: a retrieved page has the same canonical URL as the input.
- title_match: a retrieved page carries the same normalised title.
- near_duplicate: the body is substantially the same text.
- syndicated: the same report republished under another masthead, usually
  from a wire. One story, several pages — not several sources.
- not_found: We searched and got nothing. An open question, not evidence the
  story is false. It may be too recent, behind a paywall, outside our
  adapters' reach, or in a language we did not search.
- out_of_range: we never got to look, because no configured adapter covers
  this article's date or language. Distinct from not_found: not_found means
  we searched, out_of_range means we could not. Neither is a verdict.
"""

TitleMatchStrength = Literal["exact", "loose", "keyword", "none"]
"""How closely a retrieved title matches the input title.

- exact: identical after normalisation.
- loose: same title allowing for subheads, outlet suffixes, or punctuation.
- keyword: only the distinctive keywords overlap; weak, easily coincidental.
- none: no title-level match was established. Descriptive only — a weak or
  absent title match says nothing about whether the article is accurate.
"""

AdapterStatus = Literal[
    "ok",
    "empty",
    "skipped_out_of_range",
    "skipped_no_key",
    "error",
]
"""Outcome of asking one retrieval adapter to run.

- ok: the adapter ran and returned at least one hit.
- empty: the adapter ran and returned nothing. Absence of coverage, not
  absence of truth.
- skipped_out_of_range: The source cannot cover this article's date or
  language. A gap in our reach, never a signal.
- skipped_no_key: no API key is configured, so the adapter never ran. An
  operator configuration gap, not a finding about the article.
- error: the adapter failed (network, quota, bad response). A fault on our
  side of the wire. Nothing about the article may be inferred from it.
"""

MergeReason = Literal["same_owner", "same_wire", "reprint", "none"]
"""Why several pages were collapsed into one independent source.

- same_owner: the mastheads share a corporate owner.
- same_wire: both carry the same wire credit (AP, Reuters, AAP, …).
- reprint: one is a verbatim or near-verbatim republication of the other.
- none: nothing was merged; this source stands alone.
"""

QueryKind = Literal["existence", "claim", "factcheck", "entity"]
"""What a planned query is for.

- existence: locate the submitted article itself (the three-rung ladder).
- claim: search for coverage of one selected Layer 2 claim.
- factcheck: search prior reviews that appear to concern that claim.
- entity: look up a Layer 2 PERSON/ORG/GPE in a knowledge base.
"""

ExistenceSearchOutcome = Literal["not_planned", "matched", "exhausted"]
"""What happened to the existence ladder — whether we looked at all.

- not_planned: no existence query was ever built, because Layer 2 produced no
  headline. We never looked for the article elsewhere.
- matched: a rung of the ladder returned hits.
- exhausted: every rung ran and all returned nothing.

not_planned and exhausted both leave title_match_strength at "none" and both
tend to leave existence_class at not_found or out_of_range, which is exactly why
they are recorded separately. "We never looked" and "we looked everywhere and
found nothing" are opposite statements to a journalist, and no count elsewhere
in this payload distinguishes them.
"""


class PlannedQuery(BaseModel):
    """One search we intend to run, recorded before it runs.

    Planning is logged separately from results so a journalist can see what
    was asked, not only what came back. A query that returns nothing is still
    a fact about our search, and is kept.
    """

    query_id: str = Field(
        description=(
            "Stable id for this query, e.g. 'q_exist_1', 'q_claim_c3', "
            "'q_fc_c3', 'q_entity_0'. Hits point back at it."
        ),
    )
    kind: QueryKind = Field(
        description=(
            "What the query is for: locating the article itself (existence), "
            "a specific claim, a prior fact-check, or an entity lookup."
        ),
    )
    claim_id: str | None = Field(
        default=None,
        description=(
            "The Layer 2 claim this query serves, or None for existence and "
            "entity queries that are not claim-specific."
        ),
    )
    query_text: str = Field(description="The query string as sent to the adapter.")
    template_id: str = Field(
        description=(
            "Which query template produced query_text, so phrasing can be "
            "audited and compared across runs."
        ),
    )
    attempt: int = Field(
        default=1,
        description=(
            "1 for the first phrasing, incrementing for each broadened retry. "
            "A high attempt number means the search was hard, not that the "
            "claim is doubtful."
        ),
    )
    date_from: str | None = Field(
        default=None,
        description="Inclusive ISO date lower bound, or None for no bound.",
    )
    date_to: str | None = Field(
        default=None,
        description="Inclusive ISO date upper bound, or None for no bound.",
    )


class SearchHit(BaseModel):
    """One retrieved page.

    A hit is something we found, nothing more. It is not a vote for or
    against the article, and its presence here implies no assessment of the
    publisher.
    """

    url: str = Field(description="URL as returned by the adapter.")
    canonical_url: str = Field(
        description=(
            "Normalised URL used as the dedup key. Identity for matching, not "
            "a claim that the page is authentic."
        ),
    )
    title: str = Field(description="Headline as returned by the adapter.")
    snippet: str | None = Field(
        default=None,
        description="Description or lead text, when the adapter supplies one.",
    )
    body_hash: str | None = Field(
        default=None,
        description=(
            "Hash of the normalised body, used to spot verbatim reprints. "
            "None when no body text was available — which blocks reprint "
            "detection for this hit rather than proving it is original."
        ),
    )
    published_at: str | None = Field(
        default=None,
        description=(
            "Publication timestamp as reported by the source. Publisher-"
            "supplied and not independently verified; None when absent."
        ),
    )
    publisher_domain: str = Field(
        description="Registrable domain (eTLD+1) of the page.",
    )
    publisher_id: str = Field(
        description=(
            "Finer publisher identity, splitting shared platforms by author "
            "where possible. Identifies who published, not their quality."
        ),
    )
    byline: str | None = Field(
        default=None,
        description="Author string when present. Not verified as a real person.",
    )
    wire_credit: str | None = Field(
        default=None,
        description=(
            "Wire agency credited on the page (AP, Reuters, AAP, …), when one "
            "is stated. Used to collapse syndicated copies into one source. "
            "None means no credit was found, not that the report is original."
        ),
    )
    source_adapter: str = Field(description="Which adapter returned this hit.")
    query_id: str = Field(description="PlannedQuery.query_id that produced this hit.")
    claim_id: str | None = Field(
        default=None,
        description="The claim this hit was retrieved for, when query-specific.",
    )
    language: str | None = Field(
        default=None,
        description=(
            "Language of the page as reported by the adapter. None means "
            "unknown, not English."
        ),
    )
    relevance_score: float | None = Field(
        default=None,
        description=(
            "Ranking score from the ranking method named in "
            "RetrievalPayload.ranking_method. Ordering only: it measures "
            "textual similarity to the query, never agreement with the "
            "article or the credibility of the source. None when unranked."
        ),
    )


class IndependentSource(BaseModel):
    """A group of pages judged to come from one newsroom.

    Collapsing exists so syndication cannot be mistaken for corroboration.
    Grouping is a statement about ownership and provenance of the text, not
    about whether any member is right.
    """

    source_id: str = Field(description="Stable id for this group within the run.")
    representative_url: str = Field(
        description="The member chosen to stand for the group when displaying it.",
    )
    member_urls: list[str] = Field(
        default_factory=list,
        description="Canonical URLs of every page collapsed into this group.",
    )
    publisher_ids: list[str] = Field(
        default_factory=list,
        description="Distinct publisher_ids represented in the group.",
    )
    merge_reason: MergeReason = Field(
        default="none",
        description=(
            "Why the members were treated as one source, or 'none' when the "
            "source stands alone."
        ),
    )
    merge_evidence: str = Field(
        default="",
        description=(
            "Short human-readable justification for the merge, e.g. the shared "
            "wire credit or owner. Display text; nothing branches on it."
        ),
    )


class Capability(BaseModel):
    """What one adapter can and cannot reach.

    Declared up front so an adapter can be skipped honestly, with
    skipped_out_of_range, instead of being queried and returning a misleading
    empty result. Every field describes our reach, not source quality.
    """

    max_age_days: int | None = Field(
        description=(
            "How far back the source can be searched, in days. None means an "
            "unlimited archive."
        ),
    )
    languages: list[str] | None = Field(
        description=(
            "Language codes the source can search. None means any language, "
            "or that the limits are unknown — either way no language filter "
            "is applied."
        ),
    )
    regions: list[str] | None = Field(
        description=(
            "Region codes the source covers. None means unrestricted or "
            "unknown. Limited regional reach is a gap in coverage, not a "
            "judgement about stories from elsewhere."
        ),
    )
    searches_full_text: bool = Field(
        description=(
            "True when the source searches article bodies, false when it only "
            "searches titles and metadata. A title-only source missing a claim "
            "says little about that claim."
        ),
    )
    requires_key: bool = Field(
        description="True when the adapter needs an API key to run at all.",
    )


class AdapterReport(BaseModel):
    """What one adapter actually did on this run.

    Kept for every configured adapter, including those that were skipped, so
    silence is visible and attributable.
    """

    adapter: str = Field(description="Adapter name.")
    status: AdapterStatus = Field(description="Outcome. See AdapterStatus.")
    queries_run: int = Field(
        default=0,
        description="How many planned queries were actually sent to this adapter.",
    )
    hits_returned: int = Field(
        default=0,
        description=(
            "Raw hits before dedup and collapsing. A page count from one "
            "source; it does not corroborate anything on its own."
        ),
    )
    reason: str | None = Field(
        default=None,
        description=(
            "Human-readable explanation, required in spirit for any status "
            "other than ok — which key is missing, which date or language "
            "bound was exceeded, or what failed. Explains our reach, never "
            "the article."
        ),
    )
    checks_skipped: list[str] = Field(
        default_factory=list,
        description=(
            "Capability checks that did not run because our own metadata was "
            "missing, e.g. 'age' when the article has no known publication "
            "date, or 'language' when no detector identified one. A skipped "
            "check means this adapter was queried without that filter, so the "
            "result is broader than the declared capabilities imply — the "
            "opposite of a coverage gap, and worth seeing either way."
        ),
    )
    http_status: int | None = Field(
        default=None,
        description="Final HTTP status when a response was received, else None.",
    )


class CoverageReport(BaseModel):
    """What we were able to look for, and what we could not.

    This is the honesty record of the layer. A journalist reading a thin
    result must be able to tell "nobody else reported this" apart from "we
    could not go and look", and this model is what lets them.
    """

    claims_total: int = Field(
        default=0,
        description="How many claims Layer 2 produced.",
    )
    claims_searched: list[str] = Field(
        default_factory=list,
        description="Claim ids we ran at least one query for.",
    )
    claims_skipped: list[str] = Field(
        default_factory=list,
        description=(
            "Claim ids we ran no query for, e.g. beyond the top-k budget or "
            "lacking usable text. Unsearched, not unsupported."
        ),
    )
    article_language: str | None = Field(
        default=None,
        description=(
            "None means we do not know the language, not that the article has "
            "none. Language capability checks are skipped entirely when this "
            "is None."
        ),
    )
    language_checks_applied: bool = Field(
        default=False,
        description=(
            "True only when article_language is known and adapter language "
            "capabilities were enforced. Always False when article_language is "
            "None, so an unfiltered search is never reported as a filtered one."
        ),
    )
    languages_covered: list[str] = Field(
        default_factory=list,
        description=(
            "Languages the adapters that ran were able to search. A language "
            "absent here was not searched; nothing follows about what it "
            "contains."
        ),
    )
    earliest_reachable_date: str | None = Field(
        default=None,
        description=(
            "Earliest ISO date any adapter that ran could reach. An article "
            "older than this is outside our archive window, which explains an "
            "empty result rather than casting doubt on it. None when unbounded "
            "or when no adapter ran."
        ),
    )
    adapters: list[AdapterReport] = Field(
        default_factory=list,
        description="One report per configured adapter, including skipped ones.",
    )
    capability_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Every capability check that did not run, attributed to its "
            "adapter and in plain words. These are the cases where our own "
            "missing metadata — an unknown publication date, an undetected "
            "language — meant a declared limit was never enforced. Surfaced "
            "here so a reader does not have to open each AdapterReport to "
            "learn that the search was less filtered than it appears."
        ),
    )
    existence_search: ExistenceSearchOutcome = Field(
        default="not_planned",
        description=(
            "Whether we looked for the article elsewhere at all, and what "
            "came of it. See ExistenceSearchOutcome. Read this before reading "
            "existence_class: 'not_planned' means the class below is the "
            "absence of a search, not the result of one."
        ),
    )
    existence_rungs_planned: int = Field(
        default=0,
        description=(
            "How many rungs the existence ladder had: 3 normally, 2 when the "
            "headline yielded no distinctive keywords, 0 when there was no "
            "headline. Stated directly so a reader need not count "
            "planned_queries to discover the search was narrower than usual."
        ),
    )
    existence_keyword_rung_skipped: bool = Field(
        default=False,
        description=(
            "True when a headline existed but consisted entirely of stopwords, "
            "so the broadest rung of the ladder was never built. The search "
            "stopped one step short of where it normally would; that is a "
            "limit of the headline's wording, not a finding about the article."
        ),
    )
    scoring_fields_missing: list[str] = Field(
        default_factory=list,
        description=(
            "Fields later layers expect but which retrieval could not fill, "
            "e.g. 'published_at' or 'body_hash'. Downstream scoring must treat "
            "these as unknown rather than as zero or negative evidence."
        ),
    )


class FactCheckRecord(BaseModel):
    """A prior published fact-check that appears to concern one of our claims.

    Recording a reviewer's verdict is not adopting it. The rating belongs to
    the reviewer; this layer neither endorses nor applies it.
    """

    claim_id: str = Field(description="The claim this review was matched to.")
    reviewer_name: str = Field(description="Organisation that published the review.")
    rating_text: str = Field(
        description=(
            "The reviewer's own verdict string, verbatim and unmapped. It is "
            "not normalised onto our scale and does not set our output."
        ),
    )
    review_url: str = Field(description="Link to the published review.")
    reviewed_claim_text: str = Field(
        description=(
            "The claim as the reviewer stated it, so a journalist can check "
            "that it really is the same claim as ours."
        ),
    )


class EntityGrounding(BaseModel):
    """Whether an entity from Layer 2 exists in a public knowledge base.

    This establishes that a name is known, nothing more. An ungrounded entity
    is usually obscure, new, or misspelled — it is not evidence of invention,
    and must never be scored as such.
    """

    entity_text: str = Field(description="The entity string from Layer 2.")
    entity_type: str = Field(description="Entity type from Layer 2, e.g. PERSON.")
    entity_is_well_known: bool = Field(
        default=False,
        description=(
            "True when the entity was found in a public knowledge base. False "
            "means not found there — a gap in reference coverage, not a claim "
            "that the entity is fictitious."
        ),
    )
    matched_title: str | None = Field(
        default=None,
        description="Title of the matched entry, or None when nothing matched.",
    )
    near_match_suggestion: str | None = Field(
        default=None,
        description=(
            "A close but unconfirmed alternative spelling for the journalist "
            "to consider. A prompt to check, never an assertion of error."
        ),
    )


class RetrievalPayload(BaseModel):
    """Everything Layer 3 found, and everything it could not reach.

    Retrieval answers "who else has published on this, and how many of them
    are genuinely separate". It performs no truth judgement, and no field
    here may be read as one by a later layer.
    """

    planned_queries: list[PlannedQuery] = Field(
        default_factory=list,
        description="Every query planned, including ones that returned nothing.",
    )
    planner_model: str | None = Field(
        default=None,
        description="Model that planned the queries, or None when deterministic.",
    )
    planner_template_version: str = Field(
        default="",
        description=(
            "Version of the query template set, so results stay comparable "
            "across runs when the templates change."
        ),
    )
    documents: list[SearchHit] = Field(
        default_factory=list,
        description="Distinct pages retrieved, after dedup by canonical URL.",
    )
    document_count: int = Field(
        default=0,
        description=(
            "How many distinct pages were found. Inflated by syndication. "
            "MUST NOT be read as corroboration."
        ),
    )
    independent_sources: list[IndependentSource] = Field(
        default_factory=list,
        description="Documents grouped into genuinely separate newsrooms.",
    )
    independent_source_count: int = Field(
        default=0,
        description=(
            "How many genuinely separate newsrooms remain after ownership, "
            "wire-credit and reprint collapsing. The only count that supports "
            "corroboration."
        ),
    )
    existence_class: ExistenceClass = Field(
        default="not_found",
        description=(
            "Whether the article itself was found elsewhere. See "
            "ExistenceClass: 'not_found' and 'out_of_range' are both "
            "coverage outcomes, never findings against the article."
        ),
    )
    title_match_strength: TitleMatchStrength = Field(
        default="none",
        description="How strong the best title-level match was. See TitleMatchStrength.",
    )
    factchecks: list[FactCheckRecord] = Field(
        default_factory=list,
        description=(
            "Prior reviews that appear to concern our claims, recorded with "
            "the reviewers' own wording. Not adopted as our verdict."
        ),
    )
    entity_grounding: list[EntityGrounding] = Field(
        default_factory=list,
        description="Knowledge-base lookups for entities from Layer 2.",
    )
    ranking_method: str = Field(
        default="",
        description=(
            "How documents were ordered, e.g. 'embedding_cosine' or "
            "'char_trigram_cosine'. Scores are NOT comparable across ranking "
            "methods: a 0.6 from one method means nothing like a 0.6 from "
            "another, so never compare relevance_score between runs, or "
            "threshold one method's scores with a number tuned on another's. "
            "The 0.22 relevance floor and 0.88 near-duplicate threshold "
            "inherited from the old Layer 3 were tuned against char-trigram "
            "cosine, not semantic embeddings, and do not transfer. "
            "Within a single method scores ARE now comparable across runs: the "
            "char-ngram fallback used to bucket trigrams with Python's salted "
            "built-in hash, so an unchanged article scored differently after "
            "every restart. That is fixed, and comparing two runs of the same "
            "article under the same ranking_method is now meaningful. Across "
            "methods it is still not."
        ),
    )
    ranking_engine_name: str = Field(
        default="",
        description=(
            "The concrete engine behind ranking_method, including any fallback "
            "actually used, so a degraded run is visible rather than silent. "
            "Read it together with ranking_method before interpreting any "
            "relevance_score: the same method name can be served by a hosted "
            "embedding model or by a local n-gram fallback, and their scores "
            "are on unrelated scales."
        ),
    )
    coverage: CoverageReport = Field(
        default_factory=CoverageReport,
        description=(
            "What we could and could not search. Read this before reading any "
            "count above: a low count from a narrow search means something "
            "very different from a low count from a wide one."
        ),
    )

    @model_validator(mode="after")
    def _counts_follow_their_lists(self) -> RetrievalPayload:
        """Derive both counts, so neither can drift from what it summarises.

        A count that disagrees with its list is the one way this layer could
        quietly misreport corroboration: `independent_source_count` is the
        number a journalist acts on, and if it ever exceeded
        `len(independent_sources)` it would invent newsrooms that were never
        found. Deriving rather than checking makes the bug unrepresentable
        instead of merely detectable, and unlike an `assert` it survives
        `python -O`.
        """
        object.__setattr__(self, "document_count", len(self.documents))
        object.__setattr__(
            self, "independent_source_count", len(self.independent_sources)
        )
        return self
