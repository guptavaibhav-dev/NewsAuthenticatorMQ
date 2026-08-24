export type TraceStatus = 'running' | 'ok' | 'empty' | 'error' | 'skipped'
export type RunStatus = 'queued' | 'running' | 'complete' | 'error'
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

export type Claim = {
  id: string
  text: string
  checkworthy: boolean
  kind: string
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

export type RunEnvelope = {
  run_id: string
  status: RunStatus
  error: string | null
  input: {
    raw_text: string
    url: string | null
    fetched_title: string | null
    canonical_url: string | null
    publisher_domain: string | null
    fetch_status: string
    fetch_error: string | null
  }
  classification: {
    content_type: string
    headline: string | null
    claims: Claim[]
    entities: Entity[]
    date_window: { start: string | null; end: string | null; confidence: string }
    disagreements: string[]
    preprocess_model: string | null
    ner_engine: string | null
  }
  queries: {
    quoted_headline: string | null
    event_boolean: string | null
    factcheck_query: string | null
    planner_model: string | null
    planner_mode: string
  }
  evidence_items: EvidenceItem[]
  wiki_hits: WikiHit[]
  tool_results: { tool: string; status: string; detail: string; hit_count: number }[]
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

export type Health = {
  ok: boolean
  providers: Record<string, boolean>
  models: Record<string, string>
}

export const LAYERS = [
  { id: 'input', label: 'Input' },
  { id: 'preprocess', label: 'Pre-process' },
  { id: 'verification', label: 'Verification' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'uncertainty', label: 'Uncertainty' },
  { id: 'documentation', label: 'Record' },
  { id: 'editorial', label: 'Editorial' },
] as const

export const DECISIONS: EditorialDecision[] = [
  'verified',
  'misleading',
  'manipulated',
  'unsupported',
  'unverifiable',
  'needs_investigation',
]
