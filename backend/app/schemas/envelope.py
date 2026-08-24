from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ContentType = Literal["article", "claim", "headline", "social_post", "mixed", "unknown"]
ClaimKind = Literal["fact", "opinion", "unspecified"]
EntityType = Literal["PERSON", "ORG", "GPE", "DATE", "EVENT", "OTHER"]
ToolStatus = Literal["ok", "empty", "error", "skipped"]
TraceStatus = Literal["running", "ok", "empty", "error", "skipped"]
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


class RunRequest(BaseModel):
    text: str = ""
    url: str = ""


class DecisionRequest(BaseModel):
    decision: EditorialDecision
    notes: str = ""


class TraceEvent(BaseModel):
    ts: str = Field(default_factory=utc_now)
    layer: str
    parameter: str
    process: str
    tool: str | None = None
    status: TraceStatus
    detail: str = ""


class InputPayload(BaseModel):
    raw_text: str = ""
    url: str | None = None
    fetched_title: str | None = None
    canonical_url: str | None = None
    publisher_domain: str | None = None
    fetch_timestamp: str | None = None
    fetch_status: ToolStatus = "skipped"
    fetch_error: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    checkworthy: bool = True
    kind: ClaimKind = "unspecified"


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
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None
    input: InputPayload = Field(default_factory=InputPayload)
    classification: ClassificationPayload = Field(default_factory=ClassificationPayload)
    queries: SearchQueries = Field(default_factory=SearchQueries)
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
