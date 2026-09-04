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
    publisher_domain: string | null
    fetch_timestamp: string | null
    fetch_status: string
    fetch_error: string | null
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
  { id: 'verification', label: 'Verification', n: 3 },
  { id: 'evidence', label: 'Evidence', n: 4 },
  { id: 'uncertainty', label: 'Uncertainty', n: 5 },
  { id: 'editorial', label: 'Editorial', n: 6 },
  { id: 'documentation', label: 'Record', n: 7 },
] as const

export const PIPELINE_LAYERS = [
  { n: 1, id: 'input', title: 'Input' },
  { n: 2, id: 'preprocess', title: 'Pre-processing and Classification' },
  { n: 3, id: 'verification', title: 'Verification Tool Layer' },
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
