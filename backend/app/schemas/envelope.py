from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.retrieval import RetrievalPayload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ContentType = Literal["article", "claim", "headline", "social_post", "mixed", "unknown"]
ClaimKind = Literal["fact", "opinion", "unclear", "unspecified"]
Grounding = Literal["exact", "normalised", "not_found"]
ClaimSource = Literal["pasted", "fetched", "spans_both"]
ClaimAgreement = Literal["both", "pass_a_only", "pass_b_only"]
EntityType = Literal["PERSON", "ORG", "GPE", "DATE", "EVENT", "OTHER"]
ToolStatus = Literal["ok", "empty", "error", "skipped"]
TraceStatus = Literal["running", "ok", "empty", "error", "skipped"]
CanonicalSource = Literal["link_rel", "og_url", "final_url"]
FetchReason = Literal[
    "ok",
    "skipped_no_url",
    "empty_paywall",
    "empty_js_required",
    "empty_not_article",
    "error_dns",
    "error_timeout",
    "error_tls",
    "error_blocked",
    "error_not_found",
    "error_server",
    "error_unsupported_type",
    "error_too_large",
    "error_other",
]


def fetch_status_for_reason(reason: FetchReason) -> ToolStatus:
    """Map fetch_reason onto the coarse fetch_status enum.

    The two fields must not disagree. A non-ok reason is a coverage gap, never
    a signal of falsity.
    """
    if reason == "ok":
        return "ok"
    if reason == "skipped_no_url":
        return "skipped"
    if reason.startswith("empty_"):
        return "empty"
    return "error"
NliLabel = Literal["entailment", "contradiction", "neutral"]
Stance = Literal["supports", "refutes", "unrelated", "mixed"]
ExistenceClass = Literal[
    "exact_url_match",
    "title_match",
    "near_duplicate",
    "syndicated_or_reprint",
    "not_found",
]
CorroborationState = Literal[
    "corroborated_coverage",
    "event_corroborated",
    "single_source",
    "contested_reporting",
    "no_corroboration_found",
    "contested",
]
EngineAgreement = Literal["convergent", "contested", "nli_only", "llm_only", "none"]
SourceBand = Literal["known_legacy", "aggregator", "unknown"]
EditorialDecision = Literal[
    "verified",
    "misleading",
    "manipulated",
    "unsupported",
    "unverifiable",
    "needs_investigation",
]
PublicationRisk = Literal["low", "moderate", "high", "unknown"]
RunStatus = Literal["queued", "running", "complete", "error"]
RunPhase = Literal["idle", "running_layer", "awaiting_decision", "complete", "error"]
StepAction = Literal["proceed", "rerun"]


class RunRequest(BaseModel):
    text: str = ""
    url: str = ""


class DecisionRequest(BaseModel):
    decision: EditorialDecision
    notes: str = ""


class StepRequest(BaseModel):
    action: StepAction = "proceed"


class AskRequest(BaseModel):
    layer: int
    question: str = ""


class TraceEvent(BaseModel):
    ts: str = Field(default_factory=utc_now)
    layer: str
    parameter: str
    process: str
    tool: str | None = None
    status: TraceStatus
    detail: str = ""


class TextSegment(BaseModel):
    """A contiguous span of `raw_text` attributed to one intake source.

    Offsets are half-open Python indices `[start, end)` into `raw_text`.
    This records where characters came from (journalist paste vs fetched
    publisher body). It is not a claim about authorship quality, copyright,
    or authenticity.
    """

    source: Literal["pasted", "fetched"]
    start: int
    end: int


class InputPayload(BaseModel):
    raw_text: str = ""
    url: str | None = None
    fetched_title: str | None = None
    canonical_url: str | None = Field(
        default=None,
        description=(
            "Stable URL key after redirector unwrap, publisher canonical/og:url "
            "(same registrable domain only), AMP unwrap, and tracking-param strip. "
            "Used for dedup. Not a statement that the page is authentic or that "
            "the publisher's declared canonical was trusted blindly."
        ),
    )
    canonical_source: CanonicalSource | None = Field(
        default=None,
        description=(
            "Which candidate produced canonical_url: link_rel, og_url, or final_url. "
            "Does not rank source quality and is not an authenticity signal."
        ),
    )
    publisher_domain: str | None = Field(
        default=None,
        description=(
            "Registrable domain (eTLD+1) of the fetched URL via tldextract. "
            "Unchanged meaning. Does not distinguish authors on shared platforms "
            "and does not group cross-TLD brands (bbc.com vs bbc.co.uk)."
        ),
    )
    publisher_id: str | None = Field(
        default=None,
        description=(
            "Finer-grained publisher identity. For PLATFORM_HOSTS this is "
            "'<domain>/<extracted>' (subdomain or first path segment). Otherwise "
            "equal to publisher_domain. Identifies who published, not whether "
            "the content is authentic."
        ),
    )
    publisher_is_platform: bool = Field(
        default=False,
        description=(
            "True when publisher_domain is a known shared publishing platform "
            "listed in PLATFORM_HOSTS. Not a quality or authenticity rating."
        ),
    )
    fetch_timestamp: str | None = None
    fetch_status: ToolStatus = "skipped"
    fetch_reason: FetchReason = Field(
        default="skipped_no_url",
        description=(
            "Machine-readable why fetch_status is what it is (ok, skipped_no_url, "
            "empty_paywall / empty_js_required / empty_not_article, error_dns / "
            "error_timeout / error_tls / error_blocked / error_not_found / "
            "error_server / error_unsupported_type / error_too_large / error_other). "
            "A failed or empty fetch is a coverage gap, never a signal of falsity."
        ),
    )
    fetch_error: str | None = Field(
        default=None,
        description=(
            "Truncated exception or HTTP diagnostic string for humans and logs. "
            "Diagnostic only: nothing downstream should branch on its contents; "
            "use fetch_reason instead. Not an authenticity signal."
        ),
    )
    http_status: int | None = Field(
        default=None,
        description=(
            "Final HTTP status code when a response was received. Absent on DNS, "
            "timeout, or skipped fetches. Not a judgement of the article."
        ),
    )
    final_url: str | None = Field(
        default=None,
        description=(
            "URL after redirects (pre-canonical hygiene). Observability only; "
            "canonical_url is the dedup key. None if no request was made."
        ),
    )
    content_type: str | None = Field(
        default=None,
        description=(
            "Response Content-Type (type/subtype, no parameters) when present. "
            "Does not imply the payload is an article or that it is authentic."
        ),
    )
    redirect_chain: list[str] = Field(
        default_factory=list,
        description=(
            "Response URLs from the original request through redirects to the "
            "final URL. Empty when no HTTP round-trip occurred. Not a trust chain."
        ),
    )
    response_bytes: int | None = Field(
        default=None,
        description=(
            "Encoded body size in bytes when known (Content-Length or read length). "
            "Not a quality or authenticity metric."
        ),
    )
    retry_after: str | None = Field(
        default=None,
        description=(
            "Retry-After header value when the server sent one (typically on 429). "
            "Advisory for the operator; not a schedule and not an authenticity signal."
        ),
    )
    extracted_char_count: int = 0
    text_merged: bool = Field(
        default=False,
        description=(
            "Convenience bool: true iff `segments` contains both 'pasted' and "
            "'fetched' sources. Derived from segments; not an independent flag. "
            "Does not mean the paste is a publisher quote, and does not score authenticity."
        ),
    )
    segments: list[TextSegment] = Field(
        default_factory=list,
        description=(
            "Ordered, non-overlapping spans that tile `raw_text` exactly. "
            "Each span's source is 'pasted' (journalist-supplied) or 'fetched' "
            "(publisher body). Downstream layers must use this — not substring "
            "heuristics — to attribute characters. Does not imply that fetched "
            "text is true or that pasted notes are claims."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_fetch_reason(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "fetch_reason" not in data and "fetch_status" in data:
            data = dict(data)
            data["fetch_reason"] = {
                "ok": "ok",
                "skipped": "skipped_no_url",
                "empty": "empty_not_article",
                "error": "error_other",
            }.get(data.get("fetch_status"), "skipped_no_url")
        return data

    @model_validator(mode="after")
    def _derive_convenience_fields(self) -> InputPayload:
        kinds = {seg.source for seg in self.segments}
        self.text_merged = "pasted" in kinds and "fetched" in kinds
        self.fetch_status = fetch_status_for_reason(self.fetch_reason)
        return self


class Claim(BaseModel):
    id: str
    text: str
    checkworthy: bool = True
    kind: ClaimKind = "unspecified"
    source_quote: str | None = Field(
        default=None,
        description=(
            "The article substring the model said this claim came from, as the "
            "model returned it. Provenance only: it says where the claim was "
            "read from, never that the claim is true or that the quote is "
            "accurate reporting."
        ),
    )
    span_start: int | None = Field(
        default=None,
        description=(
            "Start index of source_quote inside InputPayload.raw_text, or None "
            "when the quote could not be located. An offset, not a confidence "
            "score."
        ),
    )
    span_end: int | None = Field(
        default=None,
        description=(
            "End index (exclusive) of source_quote inside raw_text, so "
            "raw_text[span_start:span_end] is the located passage. None when "
            "the quote could not be located."
        ),
    )
    grounding: Grounding = Field(
        default="not_found",
        description=(
            "How the quote was located: 'exact' (verbatim substring of "
            "raw_text), 'normalised' (matched after NFKC, whitespace collapse, "
            "and curly quote/dash folding on both sides), or 'not_found' (the "
            "quote is not in the article — likely fabricated, so the claim is "
            "kept and flagged rather than dropped). Grounding means ONLY that "
            "this text exists in the article. It does NOT mean the claim is "
            "true, accurate, or corroborated; no web search or truth judgement "
            "happens in Layer 2."
        ),
    )
    claim_source: ClaimSource | None = Field(
        default=None,
        description=(
            "Which Layer 1 text segment the located span falls inside: "
            "'pasted' (journalist-supplied), 'fetched' (publisher body), or "
            "'spans_both'. None when the claim is ungrounded or Layer 1 "
            "recorded no segments. Attribution of characters only — it does "
            "not rank the reliability of either source."
        ),
    )
    agreement: ClaimAgreement = Field(
        default="both",
        description=(
            "Which of the two independent extraction passes produced this "
            "claim: 'both' (their spans overlapped), 'pass_a_only', or "
            "'pass_b_only'. This describes EXTRACTOR AGREEMENT ONLY. 'both' "
            "does NOT mean the claim is true, corroborated, or important — two "
            "models can agree on a false statement. 'pass_a_only' and "
            "'pass_b_only' mean lower extraction confidence, not that the claim "
            "is wrong. No downstream layer may read this as a truth signal. "
            "Check passes_independent before interpreting it at all: when only "
            "one pass ran, every claim is 'both' by construction."
        ),
    )
    agreement_note: str | None = Field(
        default=None,
        description=(
            "Short human-readable reason for the agreement value, e.g. which "
            "pass found it or that the passes disagreed on label. Display text "
            "for the journalist; nothing should branch on its contents."
        ),
    )
    variant_texts: list[str] = Field(
        default_factory=list,
        description=(
            "One entry per pass that produced this claim, in pass order, as "
            "each pass worded it. Two entries means both passes described the "
            "same span. Kept so the journalist can see the wording differ; it "
            "is not a vote count and carries no truth weight."
        ),
    )


class Entity(BaseModel):
    text: str
    type: EntityType
    source: Literal["llm", "ner", "both"] = "llm"


class DateWindow(BaseModel):
    start: str | None = None
    end: str | None = None
    confidence: Literal["high", "weak", "none"] = "none"


class ClassificationPayload(BaseModel):
    content_type: ContentType = "unknown"
    headline: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    date_window: DateWindow = Field(default_factory=DateWindow)
    disagreements: list[str] = Field(default_factory=list)
    ungrounded_claim_count: int = Field(
        default=0,
        description=(
            "How many claims have grounding == 'not_found', i.e. the model "
            "supplied a quote that is not in the article. These claims are kept "
            "and surfaced, never dropped. A high count signals extraction "
            "trouble, not that the article is false."
        ),
    )
    total_claims: int = Field(
        default=0,
        description="Number of claims kept from both passes combined.",
    )
    claim_agreement_rate: float = Field(
        default=0.0,
        description=(
            "Fraction of claims with agreement == 'both' (both / total), 0.0 "
            "when there are no claims. Measures how much the two extraction "
            "passes overlapped. It is NOT a confidence, accuracy, or truth "
            "score for the article, and it is meaningless when "
            "passes_independent is false."
        ),
    )
    pass_a_model: str | None = Field(
        default=None,
        description="Model that produced extraction pass A, or 'heuristic'.",
    )
    pass_b_model: str | None = Field(
        default=None,
        description=(
            "Model that produced extraction pass B, or None when only one pass "
            "ran (CLAIM_PASSES=1, no provider configured, or pass B failed)."
        ),
    )
    passes_independent: bool = Field(
        default=False,
        description=(
            "True only when the two passes resolved to different models. False "
            "when one pass ran, or both passes used the same model with "
            "differently worded prompts. When false, `agreement` is not a "
            "cross-check and must not be presented as one."
        ),
    )
    preprocess_model: str | None = None
    ner_engine: str | None = None


class SearchQueries(BaseModel):
    quoted_headline: str | None = None
    event_boolean: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    entity_queries: list[str] = Field(default_factory=list)
    factcheck_query: str | None = None
    planner_model: str | None = None
    planner_mode: Literal["llm", "deterministic"] = "deterministic"


class EvidenceItem(BaseModel):
    source_id: str
    outlet: str
    domain: str
    url: str
    title: str
    published_at: str | None = None
    snippet: str
    tool: str
    matched_claim_id: str | None = None
    publisher_family: str | None = None
    source_band: SourceBand = "unknown"
    similarity: float | None = None


class FactCheckItem(BaseModel):
    claim_text: str
    textual_rating: str | None = None
    publisher: str | None = None
    url: str | None = None
    review_date: str | None = None
    similarity: float | None = None


class WikiHit(BaseModel):
    query: str
    title: str | None = None
    url: str | None = None
    description: str | None = None
    found: bool = False


class ToolResult(BaseModel):
    tool: str
    status: ToolStatus
    detail: str = ""
    hit_count: int = 0


class ExistenceResult(BaseModel):
    existence_class: ExistenceClass = "not_found"
    matched_url: str | None = None
    matched_title: str | None = None
    similarity: float | None = None
    notes: str = ""


class PairAnalysis(BaseModel):
    claim_id: str
    source_id: str
    nli_label: NliLabel = "neutral"
    nli_score: float = 0.0
    nli_probs: dict[str, float] = Field(default_factory=dict)
    gemini_stance: Stance | None = None
    independence: bool = True
    temporal_relation: Literal["before", "after", "unknown"] | None = "unknown"


class Inconsistency(BaseModel):
    slot: Literal["date", "place", "number", "actor", "other"]
    summary: str
    source_ids: list[str] = Field(default_factory=list)


class GeminiClaimAnalysis(BaseModel):
    claim_id: str
    supported_by: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)
    unrelated: list[str] = Field(default_factory=list)
    inconsistencies: list[Inconsistency] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)


class ClaimCorroboration(BaseModel):
    claim_id: str
    nli_support: int = 0
    nli_contradict: int = 0
    llm_support: int = 0
    llm_contradict: int = 0
    independent_support_outlets: int = 0
    independent_contradict_outlets: int = 0
    agreement: EngineAgreement = "none"
    state: CorroborationState = "no_corroboration_found"


class CorroborationPayload(BaseModel):
    existence: ExistenceResult = Field(default_factory=ExistenceResult)
    overall_state: CorroborationState = "no_corroboration_found"
    independent_source_count: int = 0
    claims: list[ClaimCorroboration] = Field(default_factory=list)
    fact_checks: list[FactCheckItem] = Field(default_factory=list)


class UncertaintyPayload(BaseModel):
    unknowns: list[str] = Field(default_factory=list)
    weak_evidence: list[str] = Field(default_factory=list)
    source_independence_note: str = ""
    publication_risk: PublicationRisk = "unknown"
    recommended_decision: EditorialDecision | None = None
    rationale: str = ""
    model: str | None = None


class DocumentationPayload(BaseModel):
    claim_summary: str = ""
    source_assessment: str = ""
    evidence_summary: str = ""
    cross_source_notes: str = ""
    uncertainty_statement: str = ""
    editorial_recommendation: str = ""
    citations: list[str] = Field(default_factory=list)
    model: str | None = None
    caveat: str = (
        "Decision support only. This record is not an authenticity verdict. "
        "Final judgement remains with the journalist."
    )


class HumanDecision(BaseModel):
    decision: EditorialDecision | None = None
    notes: str = ""
    decided_at: str | None = None


class RunEnvelope(BaseModel):
    run_id: str
    status: RunStatus = "queued"
    phase: RunPhase = "idle"
    current_layer: int | None = None
    completed_layer: int = 0
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None
    input: InputPayload = Field(default_factory=InputPayload)
    classification: ClassificationPayload = Field(default_factory=ClassificationPayload)
    queries: SearchQueries = Field(default_factory=SearchQueries)
    retrieval: RetrievalPayload | None = Field(
        default=None,
        description=(
            "Layer 3 retrieval and independence output. None until Layer 3 has "
            "run. The legacy queries / evidence_items / wiki_hits / "
            "tool_results / corroboration fields are still authoritative for "
            "downstream layers until the stage 5 migration."
        ),
    )
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    wiki_hits: list[WikiHit] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    analysis: list[PairAnalysis] = Field(default_factory=list)
    gemini_analysis: list[GeminiClaimAnalysis] = Field(default_factory=list)
    corroboration: CorroborationPayload = Field(default_factory=CorroborationPayload)
    uncertainty: UncertaintyPayload = Field(default_factory=UncertaintyPayload)
    record: DocumentationPayload = Field(default_factory=DocumentationPayload)
    human_decision: HumanDecision = Field(default_factory=HumanDecision)
    trace: list[TraceEvent] = Field(default_factory=list)
    engines_used: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
