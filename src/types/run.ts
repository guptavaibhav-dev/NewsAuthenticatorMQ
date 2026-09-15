export type TraceStatus = 'running' | 'ok' | 'empty' | 'error' | 'skipped'
export type RunStatus = 'queued' | 'running' | 'complete' | 'error'
export type RunPhase =
  | 'idle'
  | 'running_layer'
  | 'awaiting_decision'
  | 'complete'
  | 'error'
export type EditorialDecision =
  | 'verified'
  | 'misleading'
  | 'manipulated'
  | 'unsupported'
  | 'unverifiable'
  | 'needs_investigation'

export type TraceEvent = {
  ts: string
  layer: string
  parameter: string
  process: string
  tool: string | null
  status: TraceStatus
  detail: string
  type?: string
}

export type Grounding = 'exact' | 'normalised' | 'not_found'

/** Which extraction pass found the claim. Extractor overlap only — never truth. */
export type ClaimAgreement = 'both' | 'pass_a_only' | 'pass_b_only'

export type Claim = {
  id: string
  text: string
  checkworthy: boolean
  kind: string
  source_quote?: string | null
  span_start?: number | null
  span_end?: number | null
  grounding?: Grounding
  claim_source?: 'pasted' | 'fetched' | 'spans_both' | null
  agreement?: ClaimAgreement
  agreement_note?: string | null
  variant_texts?: string[]
}

export type Entity = {
  text: string
  type: string
  source: string
}

export type EvidenceItem = {
  source_id: string
  outlet: string
  domain: string
  url: string
  title: string
  published_at: string | null
  snippet: string
  tool: string
  source_band: string
  publisher_family: string | null
  similarity: number | null
}

export type PairAnalysis = {
  claim_id: string
  source_id: string
  nli_label: 'entailment' | 'contradiction' | 'neutral'
  nli_score: number
  gemini_stance: string | null
}

export type ClaimCorroboration = {
  claim_id: string
  nli_support: number
  nli_contradict: number
  llm_support: number
  llm_contradict: number
  independent_support_outlets?: number
  independent_contradict_outlets?: number
  agreement: string
  state: string
}

export type FactCheckItem = {
  claim_text: string
  textual_rating: string | null
  publisher: string | null
  url: string | null
  review_date: string | null
}

export type WikiHit = {
  query: string
  title: string | null
  url: string | null
  description: string | null
  found: boolean
}

export type RetrievalExistenceClass =
  | 'exact_url'
  | 'title_match'
  | 'near_duplicate'
  | 'syndicated'
  | 'not_found'
  | 'out_of_range'

export type TitleMatchStrength = 'exact' | 'loose' | 'keyword' | 'none'
export type ExistenceSearchOutcome = 'not_planned' | 'matched' | 'exhausted'
export type MergeReason = 'same_wire' | 'same_owner' | 'reprint' | 'none'
export type AdapterStatus =
  | 'ok'
  | 'empty'
  | 'skipped_out_of_range'
  | 'skipped_no_key'
  | 'error'

export type PlannedQuery = {
  query_id: string
  kind: 'existence' | 'claim' | 'factcheck' | 'entity'
  claim_id: string | null
  query_text: string
  template_id: string
  attempt: number
  date_from: string | null
  date_to: string | null
}

export type SearchHit = {
  url: string
  canonical_url: string
  title: string
  snippet: string | null
  body_hash: string | null
  published_at: string | null
  publisher_domain: string
  publisher_id: string
  byline: string | null
  wire_credit: string | null
  source_adapter: string
  query_id: string
  claim_id: string | null
  language: string | null
  relevance_score: number | null
}

export type IndependentSource = {
  source_id: string
  representative_url: string
  member_urls: string[]
  publisher_ids: string[]
  merge_reason: MergeReason
  merge_evidence: string
}

export type AdapterReport = {
  adapter: string
  status: AdapterStatus
  queries_run: number
  hits_returned: number
  reason: string | null
  checks_skipped: string[]
  http_status: number | null
}

export type CoverageReport = {
  claims_total: number
  claims_searched: string[]
  claims_skipped: string[]
  article_language: string | null
  language_checks_applied: boolean
  languages_covered: string[]
  earliest_reachable_date: string | null
  adapters: AdapterReport[]
  capability_notes: string[]
  existence_search: ExistenceSearchOutcome
  existence_rungs_planned: number
  existence_keyword_rung_skipped: boolean
  scoring_fields_missing: string[]
}

export type FactCheckRecord = {
  claim_id: string
  reviewer_name: string
  rating_text: string
  review_url: string
  reviewed_claim_text: string
}

export type EntityGrounding = {
  entity_text: string
  entity_type: string
  entity_is_well_known: boolean
  matched_title: string | null
  near_match_suggestion: string | null
}

export type RetrievalPayload = {
  planned_queries: PlannedQuery[]
  planner_model: string | null
  planner_template_version: string
  documents: SearchHit[]
  document_count: number
  independent_sources: IndependentSource[]
  independent_source_count: number
  existence_class: RetrievalExistenceClass
  title_match_strength: TitleMatchStrength
  factchecks: FactCheckRecord[]
  entity_grounding: EntityGrounding[]
  ranking_method: string
  ranking_engine_name: string
  coverage: CoverageReport
}

export type RunEnvelope = {
  run_id: string
  status: RunStatus
  phase: RunPhase
  current_layer: number | null
  completed_layer: number
  error: string | null
  input: {
    raw_text: string
    url: string | null
    fetched_title: string | null
    canonical_url: string | null
    canonical_source?: string | null
    publisher_domain: string | null
    publisher_id?: string | null
    publisher_is_platform?: boolean
    fetch_timestamp: string | null
    fetch_status: string
    fetch_reason?: string
    fetch_error: string | null
    http_status?: number | null
    final_url?: string | null
    content_type?: string | null
    redirect_chain?: string[]
    retry_after?: string | null
    extracted_char_count: number
    text_merged: boolean
  }
  classification: {
    content_type: string
    headline: string | null
    claims: Claim[]
    entities: Entity[]
    date_window: { start: string | null; end: string | null; confidence: string }
    disagreements: string[]
    ungrounded_claim_count?: number
    total_claims?: number
    claim_agreement_rate?: number
    pass_a_model?: string | null
    pass_b_model?: string | null
    passes_independent?: boolean
    preprocess_model: string | null
    ner_engine: string | null
  }
  queries: {
    quoted_headline: string | null
    event_boolean: string | null
    factcheck_query: string | null
    planner_model: string | null
    planner_mode: string
    entity_queries?: string[]
    date_from?: string | null
    date_to?: string | null
  }
  evidence_items: EvidenceItem[]
  wiki_hits: WikiHit[]
  tool_results: { tool: string; status: string; detail: string; hit_count: number }[]
  retrieval?: RetrievalPayload | null
  analysis: PairAnalysis[]
  corroboration: {
    existence: {
      existence_class: string
      matched_url: string | null
      matched_title: string | null
      similarity: number | null
      notes: string
    }
    overall_state: string
    independent_source_count: number
    claims: ClaimCorroboration[]
    fact_checks: FactCheckItem[]
  }
  uncertainty: {
    unknowns: string[]
    weak_evidence: string[]
    source_independence_note: string
    publication_risk: string
    recommended_decision: EditorialDecision | null
    rationale: string
    model: string | null
  }
  record: {
    claim_summary: string
    source_assessment: string
    evidence_summary: string
    cross_source_notes: string
    uncertainty_statement: string
    editorial_recommendation: string
    citations: string[]
    model: string | null
    caveat: string
  }
  human_decision: {
    decision: EditorialDecision | null
    notes: string
    decided_at: string | null
  }
  engines_used: Record<string, string>
  trace: TraceEvent[]
}

export type HealthStatus =
  | 'working'
  | 'configured'
  | 'missing'
  | 'error'
  | 'fallback'
  | 'unavailable'
  | 'ready'
  | 'degraded'

export type HealthKey = {
  id: string
  env: string
  label: string
  used_by: string[]
  configured: boolean
  status: HealthStatus
  detail: string
}

export type HealthEngine = {
  id: string
  role: string
  model: string
  key: string | null
  status: HealthStatus
  detail: string
}

export type HealthService = {
  id: string
  label: string
  kind: string
  status: HealthStatus
  detail: string
  key: string | null
}

export type HealthModule = {
  id: string
  label: string
  layer: string
  status: HealthStatus
  detail: string
}

export type HealthLayer = {
  id: string
  order: number
  label: string
  status: HealthStatus
  detail: string
  depends_on: string[]
}

export type Health = {
  ok: boolean
  probed?: boolean
  checked_at?: string
  summary?: {
    keys_working: number
    keys_configured: number
    keys_total: number
    layers_ready: number
    layers_total: number
  }
  keys?: HealthKey[]
  engines?: HealthEngine[]
  services?: HealthService[]
  modules?: HealthModule[]
  layers?: HealthLayer[]
  providers: Record<string, boolean>
  models: Record<string, string>
}

export const LAYERS = [
  { id: 'input', label: 'Input', n: 1 },
  { id: 'preprocess', label: 'Pre-process', n: 2 },
  { id: 'verification', label: 'Retrieval', n: 3 },
  { id: 'evidence', label: 'Evidence', n: 4 },
  { id: 'uncertainty', label: 'Uncertainty', n: 5 },
  { id: 'editorial', label: 'Editorial', n: 6 },
  { id: 'documentation', label: 'Record', n: 7 },
] as const

export const PIPELINE_LAYERS = [
  { n: 1, id: 'input', title: 'Input' },
  { n: 2, id: 'preprocess', title: 'Pre-processing and Classification' },
  { n: 3, id: 'verification', title: 'Retrieval and Independence' },
  { n: 4, id: 'evidence', title: 'Evidence Analysis' },
  { n: 5, id: 'uncertainty', title: 'Uncertainty and Risk Assessment' },
  { n: 6, id: 'editorial', title: 'Human Editorial Decision' },
  { n: 7, id: 'documentation', title: 'Output and Documentation' },
] as const

export const EDITORIAL_LAYER = 6
export const LAST_LAYER = 7

export type ChatMessage =
  | {
      id: string
      kind: 'layer'
      layer: number
      envelope: RunEnvelope
      superseded?: boolean
    }
  | {
      id: string
      kind: 'error'
      layer: number
      detail: string
      superseded?: boolean
    }
  | { id: string; kind: 'question'; layer: number; text: string }
  | { id: string; kind: 'answer'; layer: number; text: string }

export const DECISIONS: EditorialDecision[] = [
  'verified',
  'misleading',
  'manipulated',
  'unsupported',
  'unverifiable',
  'needs_investigation',
]
