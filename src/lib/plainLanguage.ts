export type PlainEntry = {
  label: string
  gloss: string
}

const TABLE: Record<string, PlainEntry> = {
  // Tool / fetch / adapter status
  ok: {
    label: 'Succeeded',
    gloss: 'This step ran and returned something we could use',
  },
  empty: {
    label: 'Searched, found nothing',
    gloss: 'We looked and this source had nothing to return',
  },
  error: {
    label: "Couldn't complete",
    gloss: 'This step failed on our side of the wire — not a finding about the article',
  },
  skipped: {
    label: 'Not run',
    gloss: 'This step was not run',
  },
  running: {
    label: 'In progress',
    gloss: 'This step is still running',
  },

  // Fetch reasons
  skipped_no_url: {
    label: 'No link to fetch',
    gloss: 'You did not provide a URL, so there was nothing to fetch',
  },
  empty_paywall: {
    label: 'Behind a paywall',
    gloss: 'The page looks paywalled, so we could not read the article',
  },
  empty_js_required: {
    label: 'Needs a full browser',
    gloss: 'The page did not yield an article without running its scripts',
  },
  empty_not_article: {
    label: 'Not an article page',
    gloss: 'The page did not look like an article we could extract',
  },
  error_dns: {
    label: 'Address not found',
    gloss: 'We could not resolve the website address',
  },
  error_timeout: {
    label: 'Timed out',
    gloss: 'The site did not respond in time',
  },
  error_tls: {
    label: 'Secure connection failed',
    gloss: 'We could not open a trusted connection to the site',
  },
  error_blocked: {
    label: 'Blocked',
    gloss: 'The site blocked our request',
  },
  error_not_found: {
    label: 'Page not found',
    gloss: 'The site said this page does not exist',
  },
  error_server: {
    label: 'Site error',
    gloss: 'The site returned a server error',
  },
  error_unsupported_type: {
    label: 'Unsupported file type',
    gloss: 'We only fetch ordinary web articles',
  },
  error_too_large: {
    label: 'Page too large',
    gloss: 'The response was larger than we accept',
  },
  error_other: {
    label: "Couldn't fetch",
    gloss: 'The request failed for another reason — not a finding about the article',
  },

  // Canonical URL method
  link_rel: {
    label: 'Publisher canonical link',
    gloss: 'Taken from the page’s own canonical link tag',
  },
  og_url: {
    label: 'Social-share URL',
    gloss: 'Taken from the page’s social-share address',
  },
  final_url: {
    label: 'Final address after redirects',
    gloss: 'The address we landed on after following redirects',
  },

  // Content type (Layer 2 classification)
  article: { label: 'Article', gloss: 'Treated as a news article' },
  claim: { label: 'Standalone claim', gloss: 'Treated as a single claim, not a full article' },
  headline: { label: 'Headline', gloss: 'Treated as a headline rather than a full article' },
  social_post: { label: 'Social post', gloss: 'Treated as a social-media post' },
  unknown: { label: 'Unclassified', gloss: 'We did not assign a content type' },

  // Claim kind
  fact: { label: 'Fact', gloss: 'Worded as something that can be checked' },
  opinion: { label: 'Opinion', gloss: 'Worded as a judgement or view, not a checkable fact' },
  unclear: { label: 'Unclear', gloss: 'Not clearly a fact or an opinion' },
  unspecified: { label: 'Unspecified', gloss: 'No kind was assigned' },

  // Grounding
  exact: { label: 'Verbatim', gloss: 'The quote appears in the article as written' },
  normalised: {
    label: 'Matched after cleanup',
    gloss: 'The quote matches the article after punctuation and spacing were normalised',
  },
  not_found: {
    label: 'Searched, found nothing',
    gloss: 'We looked and no other outlet has this',
  },

  // Claim source
  pasted: { label: 'From your paste', gloss: 'This quote sits in the text you pasted' },
  fetched: { label: 'From the fetched page', gloss: 'This quote sits in the article we fetched' },
  spans_both: {
    label: 'From both',
    gloss: 'This quote crosses your pasted text and the fetched article',
  },

  // Claim agreement
  both: { label: 'Both passes', gloss: 'Both extraction passes picked this claim' },
  pass_a_only: { label: 'One pass only', gloss: 'Only the first extraction pass picked this claim' },
  pass_b_only: { label: 'One pass only', gloss: 'Only the second extraction pass picked this claim' },

  // Entities
  PERSON: { label: 'People', gloss: 'Named people' },
  ORG: { label: 'Organisations', gloss: 'Companies, institutions, and other organisations' },
  GPE: { label: 'Places', gloss: 'Countries, cities, and other places' },
  DATE: { label: 'Dates', gloss: 'Dates and times mentioned in the text' },
  EVENT: { label: 'Events', gloss: 'Named events' },
  OTHER: { label: 'Other', gloss: 'Named things that did not fit another type' },

  // Existence
  exact_url: {
    label: 'Same article found',
    gloss: 'Another page has the same web address as this article',
  },
  title_match: {
    label: 'Same title found',
    gloss: 'Another page carries the same title',
  },
  near_duplicate: {
    label: 'Near-duplicate found',
    gloss: 'Another page is nearly the same article',
  },
  syndicated: {
    label: 'Republished report',
    gloss: 'The same report was republished under other names — one story, several pages',
  },
  out_of_range: {
    label: "Couldn't check",
    gloss: "These sources don't cover articles this old or in this language",
  },

  // Title match
  loose: {
    label: 'Loose title match',
    gloss: 'The titles are close, allowing for subheads or outlet suffixes',
  },
  keyword: {
    label: 'Keyword overlap only',
    gloss: 'Only distinctive words overlap — a weak title match',
  },
  none: {
    label: 'None',
    gloss: 'Nothing was recorded for this field',
  },

  // Existence search ladder
  not_planned: {
    label: 'Search not planned',
    gloss: 'We never set up a search for this article on other outlets',
  },
  matched: {
    label: 'Search found a match',
    gloss: 'A planned search found a matching page',
  },
  exhausted: {
    label: 'Searched, found nothing',
    gloss: 'Every planned search ran and none found a match',
  },

  // Merge
  same_wire: {
    label: 'Same wire story',
    gloss: 'These outlets all ran one agency report, so they count as one source',
  },
  same_owner: {
    label: 'Same owner',
    gloss: 'These mastheads belong to the same owner, so they count as one source',
  },
  reprint: {
    label: 'Reprint',
    gloss: 'This is the same report reprinted under another name',
  },

  // Adapter status (more specific than tool status)
  skipped_out_of_range: {
    label: "Couldn't check",
    gloss: "This source doesn't cover articles this old or in this language",
  },
  skipped_no_key: {
    label: 'Not configured',
    gloss: 'No access key is set, so this source was never searched',
  },

  // NLI
  entailment: { label: 'Supports', gloss: 'This page supports the claim' },
  contradiction: { label: 'Contradicts', gloss: 'This page contradicts the claim' },
  neutral: { label: "Doesn't say", gloss: 'This page does not take a position on the claim' },

  // LLM stance
  supports: { label: 'Supports', gloss: 'The analyst read this page as supporting the claim' },
  refutes: { label: 'Contradicts', gloss: 'The analyst read this page as contradicting the claim' },
  unrelated: { label: "Doesn't say", gloss: 'The analyst read this page as unrelated to the claim' },
  mixed: { label: 'Mixed', gloss: 'The analyst read this page as mixed on the claim' },

  // Corroboration
  corroborated_coverage: {
    label: 'Same article, engines agree',
    gloss: 'We found the same article elsewhere and both scoring engines read support',
  },
  event_corroborated: {
    label: 'Independent reporting agrees',
    gloss: 'Two or more independent newsrooms support this claim',
  },
  single_source: {
    label: 'One newsroom',
    gloss: 'Exactly one independent newsroom supports this claim',
  },
  contested_reporting: {
    label: 'Newsrooms disagree',
    gloss: 'Independent newsrooms both support and contradict this claim',
  },
  no_corroboration_found: {
    label: 'Looked, found no support',
    gloss: 'We scored the available pages and none supported this claim',
  },
  contested: {
    label: 'Engines disagree',
    gloss: 'The two scoring engines disagreed on the direction of the evidence',
  },
  not_assessed: {
    label: 'Not assessed',
    gloss: 'No evidence was scored for this claim',
  },

  // Engine agreement
  convergent: { label: 'Engines agree', gloss: 'Both scoring engines pointed the same way' },
  nli_only: {
    label: 'Detector only',
    gloss: 'Only the automated detector scored this claim',
  },
  llm_only: {
    label: 'Analyst only',
    gloss: 'Only the AI analyst scored this claim',
  },

  // Why nothing was scored
  no_documents: {
    label: 'No pages to score',
    gloss: 'There were no retrieved pages to compare the claims against',
  },
  no_claims: {
    label: 'No claims to score',
    gloss: 'There were no claims to score',
  },
  support_rate_not_assessed: {
    label: 'Not assessed',
    gloss: 'Independent-reporting support was not scored — not a finding about the article',
  },
  support_rate_out_of_range: {
    label: "Couldn't check",
    gloss: 'We could not search other outlets, so there is no support rate',
  },
  support_rate_no_claims: {
    label: 'No claims to score',
    gloss: 'There were no claims, so there is no support rate',
  },
  documents_filtered: {
    label: 'Pages had no scorable text',
    gloss: 'Pages were retrieved but none had text we could score',
  },

  // Editorial
  verified: { label: 'Verified', gloss: 'The journalist records the claims as verified' },
  misleading: { label: 'Misleading', gloss: 'The journalist records the piece as misleading' },
  manipulated: { label: 'Manipulated', gloss: 'The journalist records the piece as manipulated' },
  unsupported: { label: 'Unsupported', gloss: 'The journalist records the claims as unsupported' },
  unverifiable: {
    label: 'Unverifiable',
    gloss: 'The journalist records the claims as not currently verifiable',
  },
  needs_investigation: {
    label: 'Needs investigation',
    gloss: 'The journalist records that this still needs investigation',
  },

  // Publication risk
  low: { label: 'Low', gloss: 'The system sees a low publication risk' },
  moderate: { label: 'Moderate', gloss: 'The system sees a moderate publication risk' },
  high: { label: 'High', gloss: 'The system sees a high publication risk' },

  // Date-window confidence
  weak: { label: 'Approximate', gloss: 'The dates are a best guess, not a tight window' },

  // Query kinds
  existence: { label: 'Find the article', gloss: 'A search for this article on other outlets' },
  factcheck: { label: 'Prior fact-checks', gloss: 'A search for earlier fact-check reviews' },
  entity: { label: 'Named entity', gloss: 'A lookup for a person, place, or organisation' },

  // Inconsistency slots
  date: { label: 'Date', gloss: 'The analyst flagged a date mismatch across sources' },
  place: { label: 'Place', gloss: 'The analyst flagged a place mismatch across sources' },
  number: { label: 'Number', gloss: 'The analyst flagged a number mismatch across sources' },
  actor: { label: 'Who', gloss: 'The analyst flagged a mismatch over who was involved' },
  other: { label: 'Other', gloss: 'The analyst flagged another kind of mismatch' },

  // Ranking
  embedding: {
    label: 'Meaning similarity',
    gloss: 'Pages were ordered by how close their meaning is to the article',
  },
  'char-ngram': {
    label: 'Letter-pattern similarity',
    gloss: 'Pages were ordered by shared letter patterns — a fallback when meaning ranking was unavailable',
  },
  embedding_cosine: {
    label: 'Meaning similarity',
    gloss: 'Pages were ordered by how close their meaning is to the article',
  },

  // Adapters
  guardian: { label: 'The Guardian', gloss: 'The Guardian Open Platform' },
  newsapi: { label: 'NewsAPI', gloss: 'NewsAPI.org — typically the last 30 days only' },
  gnews: { label: 'GNews', gloss: 'The GNews search API' },
  newsdata: { label: 'Newsdata', gloss: 'The Newsdata.io search API' },
  gdelt: { label: 'GDELT', gloss: 'The GDELT project document search' },
  google_factcheck: {
    label: 'Google Fact Check',
    gloss: 'Google Fact Check Explorer — prior reviews by other organisations',
  },
  wikipedia: { label: 'Wikipedia', gloss: 'Wikipedia / Wikidata lookups' },
  ingest: { label: 'Article fetch', gloss: 'The step that retrieves the page and extracts the article' },
}

const TITLE_MATCH_NONE: PlainEntry = {
  label: 'No title match',
  gloss: 'No title-level match was established — this says nothing about accuracy',
}

const MERGE_NONE: PlainEntry = {
  label: 'Stands alone',
  gloss: 'This outlet was not grouped with any other page',
}

const CONFIDENCE_NONE: PlainEntry = {
  label: 'None',
  gloss: 'No date range was established',
}

const CONFIDENCE_HIGH: PlainEntry = {
  label: 'High',
  gloss: 'We are reasonably sure about this date range',
}

/**
 * `none` and `high` are used by more than one enum. Callers that know the
 * field should use these instead of the shared `none` / content-type entries.
 */
export const CONTEXT_ENTRIES = {
  title_match_none: TITLE_MATCH_NONE,
  merge_none: MERGE_NONE,
  confidence_none: CONFIDENCE_NONE,
  confidence_high: CONFIDENCE_HIGH,
} as const

function humanize(value: string): string {
  return value.replaceAll('_', ' ')
}

export function plain(code: string | null | undefined): PlainEntry {
  if (!code) return { label: 'n/a', gloss: '' }
  return TABLE[code] ?? { label: humanize(code), gloss: '' }
}

export function plainLabel(code: string | null | undefined): string {
  return plain(code).label
}

export function plainGloss(code: string | null | undefined): string {
  return plain(code).gloss
}

export function titleMatchPlain(code: string | null | undefined): PlainEntry {
  if (code === 'none') return TITLE_MATCH_NONE
  if (code === 'exact') {
    return { label: 'Exact title', gloss: 'Identical after normalisation' }
  }
  return plain(code)
}

export function mergeReasonPlain(code: string | null | undefined): PlainEntry {
  if (code === 'none') return MERGE_NONE
  return plain(code)
}

export function dateConfidencePlain(code: string | null | undefined): PlainEntry {
  if (code === 'none') return CONFIDENCE_NONE
  if (code === 'high') return CONFIDENCE_HIGH
  return plain(code)
}

export function queryKindPlain(code: string | null | undefined): PlainEntry {
  if (code === 'claim') {
    return { label: 'This claim', gloss: 'A search built from one extracted claim' }
  }
  return plain(code)
}

export function fetchStatusPlain(code: string | null | undefined): PlainEntry {
  if (code === 'ok') return { label: 'Fetched', gloss: 'The page was retrieved' }
  if (code === 'empty') {
    return {
      label: 'No usable article text',
      gloss: 'We reached the page but could not extract an article',
    }
  }
  if (code === 'error') {
    return { label: "Couldn't fetch", gloss: 'The request failed — not a finding about the article' }
  }
  if (code === 'skipped') {
    return { label: 'Not fetched', gloss: 'There was nothing to fetch, or we did not try' }
  }
  return plain(code)
}

export function contentTypePlain(code: string | null | undefined): PlainEntry {
  if (code === 'mixed') return { label: 'Mixed content', gloss: 'More than one kind of content in the same input' }
  if (code === 'unknown') return { label: 'Unclassified', gloss: 'We did not assign a content type' }
  if (code === 'claim') return { label: 'Standalone claim', gloss: 'Treated as a single claim, not a full article' }
  return plain(code)
}

export function groundingPlain(code: string | null | undefined): PlainEntry {
  if (code === 'not_found') {
    return {
      label: 'Quote not in the article',
      gloss: 'The supporting quote does not appear in the article',
    }
  }
  return plain(code)
}

export function existencePlain(code: string | null | undefined): PlainEntry {
  if (code === 'not_found') {
    return {
      label: 'Searched, found nothing',
      gloss: 'We looked and no other outlet has this',
    }
  }
  return plain(code)
}

export function supportRateOmittedPlain(code: string | null | undefined): PlainEntry {
  if (code === 'out_of_range') return TABLE.support_rate_out_of_range
  if (code === 'no_claims') return TABLE.support_rate_no_claims
  return TABLE.support_rate_not_assessed
}

export function riskPlain(code: string | null | undefined): PlainEntry {
  if (code === 'unknown') {
    return { label: 'Unknown', gloss: 'No publication-risk band was assigned' }
  }
  return plain(code)
}

export function agreementPlain(code: string | null | undefined): PlainEntry {
  if (code === 'none') {
    return { label: 'Neither engine scored this', gloss: 'Neither scoring engine produced a stance' }
  }
  if (code === 'contested') {
    return {
      label: 'Engines disagree',
      gloss: 'The two scoring engines disagreed on the direction of the evidence',
    }
  }
  return plain(code)
}

/** Every enum key in the shared table, for the deliverable report. */
export function plainLanguageEntries(): { code: string; label: string; gloss: string }[] {
  return [
    ...Object.entries(TABLE).map(([code, entry]) => ({ code, ...entry })),
    { code: 'content_type.mixed', ...contentTypePlain('mixed') },
    { code: 'content_type.unknown', ...contentTypePlain('unknown') },
    { code: 'content_type.claim', ...contentTypePlain('claim') },
    { code: 'fetch_status.ok', ...fetchStatusPlain('ok') },
    { code: 'fetch_status.empty', ...fetchStatusPlain('empty') },
    { code: 'fetch_status.error', ...fetchStatusPlain('error') },
    { code: 'fetch_status.skipped', ...fetchStatusPlain('skipped') },
    { code: 'grounding.not_found', ...groundingPlain('not_found') },
    { code: 'existence.not_found', ...existencePlain('not_found') },
    { code: 'title_match.exact', ...titleMatchPlain('exact') },
    { code: 'title_match.none', ...titleMatchPlain('none') },
    { code: 'merge_reason.none', ...mergeReasonPlain('none') },
    { code: 'date_confidence.high', ...dateConfidencePlain('high') },
    { code: 'date_confidence.none', ...dateConfidencePlain('none') },
    { code: 'query_kind.claim', ...queryKindPlain('claim') },
    { code: 'publication_risk.unknown', ...riskPlain('unknown') },
    { code: 'engine_agreement.none', ...agreementPlain('none') },
  ]
}
