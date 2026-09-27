import { useState, type ReactNode } from 'react'
import { LayerDegradation, LayerMachinery, machineryPieceCount } from './layerProcess'
import type {
  Claim,
  ClaimCorroboration,
  CoverageReport,
  EditorialDecision,
  Entity,
  IndependentSource,
  PlannedQuery,
  RunEnvelope,
  SearchHit,
} from '../types/run'
import { DECISIONS, PIPELINE_LAYERS } from '../types/run'
import {
  agreementPlain,
  contentTypePlain,
  dateConfidencePlain,
  existencePlain,
  fetchStatusPlain,
  groundingPlain,
  mergeReasonPlain,
  plain,
  plainLabel,
  queryKindPlain,
  riskPlain,
  supportRateOmittedPlain,
  titleMatchPlain,
} from '../lib/plainLanguage'

export function layerTitle(layer: number) {
  return PIPELINE_LAYERS.find((row) => row.n === layer)?.title ?? `Layer ${layer}`
}

export function enginesForLayer(run: RunEnvelope, layer: number): string {
  switch (layer) {
    case 1:
      return run.engines_used.input || 'ingest'
    case 2: {
      const model = run.classification.preprocess_model || run.engines_used.preprocess
      const ner = run.classification.ner_engine || run.engines_used.ner
      return [model, ner].filter(Boolean).join(' + ') || 'heuristic'
    }
    case 3:
      return [
        run.retrieval?.planner_model || run.engines_used.verification_planner,
        run.retrieval?.ranking_engine_name || run.engines_used.embeddings,
      ]
        .filter(Boolean)
        .join(' · ') || 'retrieval tools'
    case 4:
      return [run.engines_used.nli, run.engines_used.evidence_llm].filter(Boolean).join(' + ') ||
        'NLI'
    case 5:
      return run.uncertainty.model || run.engines_used.uncertainty || 'rule-based'
    case 6:
      return 'journalist (no model)'
    case 7:
      return run.record.model || run.engines_used.documentation || 'template'
    default:
      return Object.values(run.engines_used).join(' · ')
  }
}

export type EditorialPanel = {
  active: boolean
  decision: EditorialDecision | null
  notes: string
  busy: boolean
  onDecision: (value: EditorialDecision) => void
  onNotes: (value: string) => void
  onConfirm: () => void
}

export function LayerOutput({
  layer,
  run,
  editorial,
}: {
  layer: number
  run: RunEnvelope
  processOpen?: boolean
  editorial?: EditorialPanel
}) {
  return (
    <div className="layer-card">
      <LayerDegradation run={run} layer={layer} />
      {layer === 1 && <InputOutput run={run} />}
      {layer === 2 && <PreprocessOutput run={run} />}
      {layer === 3 && <VerificationOutput run={run} />}
      {layer === 4 && <EvidenceOutput run={run} />}
      {layer === 5 && <UncertaintyOutput run={run} />}
      {layer === 6 && <EditorialOutput run={run} editorial={editorial} />}
      {layer === 7 && <DocumentationOutput run={run} />}
    </div>
  )
}

function InputOutput({ run }: { run: RunEnvelope }) {
  const input = run.input
  const publisher = input.publisher_domain || 'an unnamed publisher'
  const reason = plain(input.fetch_reason || input.fetch_status)
  const fetched = input.fetch_status === 'ok'
  const skipped = input.fetch_status === 'skipped' || input.fetch_reason === 'skipped_no_url'
  const hasPaste = Boolean(input.raw_text?.trim())
  const words = wordCount(input.raw_text)

  let answer: string
  if (fetched) {
    answer = `We fetched the article from ${publisher}.`
  } else if (skipped && !input.url) {
    answer = 'You pasted text with no link, so there was nothing to fetch.'
  } else if (hasPaste) {
    answer = `We couldn't reach the page — ${reason.label.toLowerCase()}. We're working from your pasted text.`
  } else {
    answer = `We couldn't reach the page — ${reason.label.toLowerCase()}.`
  }

  const tech: TechField[] = [
    {
      label: 'Resolved URL',
      value: input.canonical_url || input.url || 'none (pasted text only)',
    },
    {
      label: 'Canonical source',
      value: input.canonical_source ? plainLabel(input.canonical_source) : 'n/a',
      raw: input.canonical_source,
      gloss: input.canonical_source ? plain(input.canonical_source).gloss : undefined,
    },
    {
      label: 'Publisher id',
      value: input.publisher_id
        ? `${input.publisher_id}${input.publisher_is_platform ? ' (platform)' : ''}`
        : 'n/a',
    },
    {
      label: 'Fetch status',
      value: fetchStatusPlain(input.fetch_status).label,
      raw: input.fetch_status,
      gloss: fetchStatusPlain(input.fetch_status).gloss,
    },
    {
      label: 'Fetch reason',
      value: reason.label,
      raw: input.fetch_reason,
      gloss: reason.gloss,
    },
    {
      label: 'Fetch timestamp',
      value: input.fetch_timestamp || 'n/a',
    },
    {
      label: 'Extracted body',
      value: `${input.extracted_char_count ?? 0} characters`,
    },
  ]
  if (input.http_status != null) {
    tech.push({ label: 'HTTP status', value: String(input.http_status) })
  }
  if (input.content_type) {
    tech.push({ label: 'Content type', value: input.content_type })
  }
  if (input.fetch_error) {
    tech.push({ label: 'Fetch error', value: input.fetch_error })
  }
  if (input.retry_after) {
    tech.push({ label: 'Retry-After', value: input.retry_after })
  }

  return (
    <LayerTiers
      run={run}
      layer={1}
      extraCount={tech.length}
      answer={answer}
      evidence={
        <dl className="chat-dl evidence-dl">
          <Row label="Publisher" value={input.publisher_domain || 'n/a'} />
          <Row label="Headline we extracted" value={input.fetched_title || 'none extracted'} />
          <Row
            label="How much text we got"
            value={
              words === 1 ? '1 word' : `${words} words`
            }
          />
          <Row
            label="Your pasted text"
            value={
              input.text_merged
                ? 'Used — your paste was added in front of the fetched article'
                : hasPaste && skipped
                  ? 'Used — this is the only text we have'
                  : 'Not used'
            }
          />
        </dl>
      }
      machinery={<TechList fields={tech} />}
    />
  )
}

function PreprocessOutput({ run }: { run: RunEnvelope }) {
  const cls = run.classification
  const grouped = groupEntities(cls.entities)
  const ungrounded =
    cls.ungrounded_claim_count ??
    cls.claims.filter((claim) => (claim.grounding ?? 'not_found') === 'not_found').length
  const crossChecked = Boolean(cls.pass_b_model)
  const totalClaims = cls.total_claims ?? cls.claims.length
  const agreementRate = cls.claim_agreement_rate ?? 0
  const sameModel = cls.passes_independent === false && crossChecked

  const countPhrase =
    totalClaims === 0
      ? 'We did not find any checkable claims in this article.'
      : totalClaims === 1
        ? 'We found 1 checkable claim in this article.'
        : `We found ${totalClaims} checkable claims in this article.`
  const ungroundedLine =
    ungrounded > 0
      ? `${ungrounded} of them couldn't be traced back to the text — treat those carefully.`
      : null

  const techFields: TechField[] = [
    {
      label: 'Content type',
      value: contentTypePlain(cls.content_type).label,
      raw: cls.content_type,
      gloss: contentTypePlain(cls.content_type).gloss,
    },
    { label: 'Headline', value: cls.headline || 'none extracted' },
    {
      label: 'Agreement rate',
      value: crossChecked
        ? `${Math.round(agreementRate * 100)}% found by both passes (${cls.claims.filter((c) => (c.agreement ?? 'both') === 'both').length} of ${totalClaims})`
        : 'Single pass — no agreement rate',
    },
    { label: 'Pass A model', value: cls.pass_a_model ?? cls.preprocess_model ?? 'n/a' },
    { label: 'Pass B model', value: cls.pass_b_model ?? 'n/a' },
    {
      label: 'Passes independent',
      value: cls.passes_independent ? 'yes' : 'no',
    },
    {
      label: 'Date window',
      value:
        cls.date_window.start || cls.date_window.end
          ? `${cls.date_window.start || '?'} → ${cls.date_window.end || '?'}`
          : 'none',
    },
    {
      label: 'Date-window confidence',
      value: dateConfidencePlain(cls.date_window.confidence).label,
      raw: cls.date_window.confidence,
      gloss: dateConfidencePlain(cls.date_window.confidence).gloss,
    },
  ]

  return (
    <LayerTiers
      run={run}
      layer={2}
      extraCount={
        techFields.length +
        Object.keys(grouped).length +
        cls.disagreements.length +
        cls.claims.length
      }
      answer={
        <>
          {countPhrase}
          {ungroundedLine ? ` ${ungroundedLine}` : ''}
          {sameModel && (
            <span className="tier-answer-sub">
              {' '}
              Both passes ran on the same model, so this is not an independent cross-check.
            </span>
          )}
          {!crossChecked && totalClaims > 0 && (
            <span className="tier-answer-sub">
              {' '}
              Claims were extracted in a single pass, so they were not cross-checked.
            </span>
          )}
        </>
      }
      evidence={
        cls.claims.length === 0 ? (
          <p>No checkable claims were extracted from this text.</p>
        ) : (
          <ol className="desk-claims">
            {cls.claims.map((claim) => (
              <ClaimCard key={claim.id} claim={claim} crossChecked={crossChecked} />
            ))}
          </ol>
        )
      }
      machinery={
        <>
          <TechList fields={techFields} />
          <h5>Entities by type</h5>
          {cls.entities.length === 0 ? (
            <p>No entities extracted.</p>
          ) : (
            <dl className="chat-dl">
              {Object.entries(grouped).map(([type, names]) => (
                <Row
                  key={type}
                  label={plainLabel(type)}
                  value={names.join(', ')}
                  raw={type}
                  gloss={plain(type).gloss}
                />
              ))}
            </dl>
          )}
          <h5>NER / LLM disagreements</h5>
          {cls.disagreements.length === 0 ? (
            <p>None recorded.</p>
          ) : (
            <ul className="plain-list">
              {cls.disagreements.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          )}
          <h5>Claim offsets and attribution</h5>
          {cls.claims.length === 0 ? (
            <p>No claims.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {cls.claims.map((claim) => {
                const grounding = groundingPlain(claim.grounding ?? 'not_found')
                return (
                  <li key={claim.id}>
                    <code>{claim.id}</code> {grounding.label}
                    {claim.span_start != null ? ` · chars ${claim.span_start}–${claim.span_end}` : ''}
                    {claim.claim_source ? ` · ${plainLabel(claim.claim_source)}` : ''}
                    {claim.agreement_note ? ` — ${claim.agreement_note}` : ''}
                    {claim.variant_texts && claim.variant_texts.length > 1 && (
                      <p className="gloss">
                        Other pass worded it: “
                        {claim.variant_texts.filter((t) => t !== claim.text)[0]}”
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      }
    />
  )
}

function ClaimCard({ claim, crossChecked }: { claim: Claim; crossChecked: boolean }) {
  const grounding = claim.grounding ?? 'not_found'
  const ungrounded = grounding === 'not_found'
  const kind = plain(claim.kind)
  const agreement = claim.agreement ?? 'both'
  return (
    <li className={`desk-claim${ungrounded ? ' claim-unverified' : ''}`}>
      <span className="desk-claim-id">{claim.id.toUpperCase()}</span>
      <div>
        <p className="claim-text">
          <mark>{claim.text}</mark>
        </p>
        <p className="claim-meta">
          <Badge code={claim.kind} label={kind.label} gloss={kind.gloss} />
          {crossChecked && (
            <Badge
              code={agreement}
              label={plainLabel(agreement)}
              gloss={plain(agreement).gloss}
            />
          )}
        </p>
        {ungrounded ? (
          <p className="claim-inline-warn">
            This quote could not be traced back to the article. Treat the claim carefully until you
            check it.
            {claim.source_quote ? ` The model supplied: “${claim.source_quote}”.` : ''}
          </p>
        ) : (
          <p className="claim-quote">“{claim.source_quote}”</p>
        )}
      </div>
      <div
        className="desk-worth"
        title={claim.checkworthy ? 'Check-worthy' : 'Lower priority'}
      >
        <div className="desk-worth-bar" aria-hidden>
          <i className="on" />
          <i className={claim.checkworthy ? 'on' : undefined} />
          <i className={claim.checkworthy ? 'on' : undefined} />
        </div>
      </div>
    </li>
  )
}

function VerificationOutput({ run }: { run: RunEnvelope }) {
  const retrieval = run.retrieval
  if (!retrieval) {
    return (
      <LayerTiers
        run={run}
        layer={3}
        extraCount={0}
        answer="Retrieval has not produced a result yet."
        evidence={<p>Nothing to show until this layer has run.</p>}
        machinery={null}
      />
    )
  }

  const coverage = retrieval.coverage
  const independent = retrieval.independent_source_count
  const pages = retrieval.document_count
  const republished = Math.max(0, pages - independent)
  const existence = retrieval.existence_class
  const limits = couldNotLookItems(coverage)

  let answer: string
  if (existence === 'out_of_range' || coverage.existence_search === 'not_planned') {
    const why =
      existence === 'out_of_range'
        ? existencePlain(existence).gloss
        : plain('not_planned').gloss
    answer = `We couldn't check properly: ${why.charAt(0).toLowerCase()}${why.slice(1)}.`
  } else if (independent === 0 && ['exact_url', 'title_match', 'near_duplicate', 'syndicated'].includes(existence)) {
    answer = 'We found this article elsewhere, but no independent newsrooms were grouped.'
  } else if (independent === 0) {
    answer = 'No other outlet has this story.'
  } else if (independent === 1) {
    answer = '1 independent newsroom has covered this.'
  } else {
    answer = `${independent} independent newsrooms have covered this.`
  }

  const syndicationLine =
    pages !== independent
      ? `We found ${pages} page${pages === 1 ? '' : 's'}, but ${republished} ${
          republished === 1 ? 'was' : 'were'
        } the same report republished.`
      : null

  const techFields: TechField[] = [
    {
      label: 'Existence class',
      value: existencePlain(existence).label,
      raw: existence,
      gloss: existencePlain(existence).gloss,
    },
    {
      label: 'Title-match strength',
      value: titleMatchPlain(retrieval.title_match_strength).label,
      raw: retrieval.title_match_strength,
      gloss: titleMatchPlain(retrieval.title_match_strength).gloss,
    },
    {
      label: 'Ladder outcome',
      value: plainLabel(coverage.existence_search),
      raw: coverage.existence_search,
      gloss: plain(coverage.existence_search).gloss,
    },
    {
      label: 'Rungs planned',
      value: String(coverage.existence_rungs_planned),
    },
    {
      label: 'Keyword rung skipped',
      value: coverage.existence_keyword_rung_skipped ? 'yes' : 'no',
    },
    {
      label: 'Pages retrieved',
      value: `${pages} page${pages === 1 ? '' : 's'} (syndication inflates this)`,
    },
    {
      label: 'Independent sources',
      value: `${independent} independent newsroom${independent === 1 ? '' : 's'}`,
    },
    {
      label: 'Ranking method',
      value: retrieval.ranking_method ? plainLabel(retrieval.ranking_method) : 'unranked',
      raw: retrieval.ranking_method || undefined,
      gloss: retrieval.ranking_method ? plain(retrieval.ranking_method).gloss : undefined,
    },
    {
      label: 'Claims searched',
      value:
        coverage.claims_searched.length === 0
          ? 'none'
          : coverage.claims_searched.join(', '),
    },
    {
      label: 'Claims skipped',
      value:
        coverage.claims_skipped.length === 0
          ? 'none'
          : coverage.claims_skipped.join(', '),
    },
  ]

  return (
    <LayerTiers
      run={run}
      layer={3}
      extraCount={
        techFields.length +
        coverage.capability_notes.length +
        coverage.adapters.length +
        retrieval.documents.length +
        retrieval.independent_sources.length +
        retrieval.planned_queries.length
      }
      answer={
        <>
          {answer}
          {syndicationLine && <p className="tier-answer-sub">{syndicationLine}</p>}
        </>
      }
      evidence={
        <>
          <h4>Independent sources</h4>
          {retrieval.independent_sources.length === 0 ? (
            <p>No independent sources were grouped — there are no retrieved pages to collapse.</p>
          ) : (
            <ul className="plain-list source-list">
              {retrieval.independent_sources.map((source) => (
                <li key={source.source_id}>
                  <JournalistSourceRow source={source} documents={retrieval.documents} />
                </li>
              ))}
            </ul>
          )}

          <h4>Did we find this exact article elsewhere?</h4>
          <p>{existenceElsewhere(existence)}</p>

          {retrieval.factchecks.length > 0 && (
            <>
              <h4>Prior fact-checks</h4>
              <ul className="plain-list">
                {retrieval.factchecks.map((record) => (
                  <li key={record.review_url}>
                    <strong>{record.reviewer_name || 'An unnamed reviewer'}</strong> rated this “
                    {record.rating_text}”. That is {record.reviewer_name || 'their'} assessment, not
                    ours.{' '}
                    <span className="muted">“{record.reviewed_claim_text}”</span>{' '}
                    {record.review_url && (
                      <a href={record.review_url} target="_blank" rel="noreferrer">
                        review
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {limits.length > 0 && (
            <>
              <h4>Where we couldn&apos;t look</h4>
              <ul className="plain-list limit-list">
                {limits.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </>
      }
      machinery={
        <>
          <TechList fields={techFields} />
          <h5>Capability notes</h5>
          {coverage.capability_notes.length === 0 ? (
            <p>No capability checks were skipped for missing metadata.</p>
          ) : (
            <ul className="plain-list">
              {coverage.capability_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          <h5>Per-adapter rows</h5>
          {coverage.adapters.length === 0 ? (
            <p>No adapter reports.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {coverage.adapters.map((report) => (
                <li key={report.adapter} title={report.status}>
                  {plainLabel(report.adapter)} — {plainLabel(report.status)}
                  {report.reason ? ` — ${report.reason}` : ''}
                  {report.checks_skipped.length
                    ? ` (skipped checks: ${report.checks_skipped.join(', ')})`
                    : ''}
                  {` · ${report.hits_returned} hit${report.hits_returned === 1 ? '' : 's'}, ${report.queries_run} quer${report.queries_run === 1 ? 'y' : 'ies'}`}
                  {report.http_status != null ? ` · HTTP ${report.http_status}` : ''}
                </li>
              ))}
            </ul>
          )}
          <h5>Merge evidence</h5>
          {retrieval.independent_sources.length === 0 ? (
            <p>No independent-source groups.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {retrieval.independent_sources.map((source) => (
                <li key={source.source_id}>
                  <code>{source.source_id}</code> {mergeReasonPlain(source.merge_reason).label}
                  {` (${source.merge_reason})`} — {source.merge_evidence}
                </li>
              ))}
            </ul>
          )}
          <h5>Planned queries</h5>
          {retrieval.planned_queries.length === 0 ? (
            <p>No frozen queries were recorded.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {retrieval.planned_queries.map((query) => (
                <PlannedQueryRow key={query.query_id} query={query} />
              ))}
            </ul>
          )}
          <h5>Retrieved documents</h5>
          {retrieval.documents.length === 0 ? (
            <p>No documents after retrieval.</p>
          ) : (
            <ul className="plain-list">
              {retrieval.documents.map((hit) => (
                <li key={hit.canonical_url || hit.url}>
                  <a href={hit.url} target="_blank" rel="noreferrer">
                    {hit.title || hit.url}
                  </a>{' '}
                  <span>
                    {hit.publisher_domain}
                    {hit.wire_credit ? ` · wire: ${hit.wire_credit}` : ''}
                    {hit.relevance_score != null
                      ? ` · ${hit.relevance_score.toFixed(2)} (${
                          retrieval.ranking_method
                            ? plainLabel(retrieval.ranking_method)
                            : 'unranked'
                        })`
                      : retrieval.ranking_method
                        ? ` · unranked (${plainLabel(retrieval.ranking_method)})`
                        : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      }
    />
  )
}

function PlannedQueryRow({ query }: { query: PlannedQuery }) {
  const kind = queryKindPlain(query.kind)
  return (
    <li title={query.kind}>
      <code>{query.query_id}</code> {kind.label}
      {query.claim_id ? ` · ${query.claim_id}` : ''}
      {` · ${query.template_id} · attempt ${query.attempt}`}
      {(query.date_from || query.date_to) &&
        ` · ${query.date_from || '?'} → ${query.date_to || '?'}`}
      <p className="gloss">{query.query_text}</p>
    </li>
  )
}

function JournalistSourceRow({
  source,
  documents,
}: {
  source: IndependentSource
  documents: SearchHit[]
}) {
  const name = source.publisher_ids[0] || hostOf(source.representative_url)
  const extras = Math.max(0, source.member_urls.length - 1)
  const members = documents.filter(
    (hit) =>
      source.member_urls.includes(hit.url) || source.member_urls.includes(hit.canonical_url),
  )
  const wire = members.find((hit) => hit.wire_credit)?.wire_credit
  let collapse: string | null = null
  if (source.merge_reason !== 'none' && extras > 0) {
    const others = `${extras} other paper${extras === 1 ? '' : 's'}`
    if (source.merge_reason === 'same_wire') {
      collapse = `Also ran by ${others} — same ${wire || 'wire'} report.`
    } else if (source.merge_reason === 'same_owner') {
      collapse = `Also listed under ${others} — same owner.`
    } else if (source.merge_reason === 'reprint') {
      collapse = `Also reprinted by ${others}.`
    }
  }
  const monogram = (name.replace(/^www\./, '')[0] || '?').toUpperCase()
  return (
    <div className="desk-src">
      <span className="desk-src-mono" aria-hidden>
        {monogram}
      </span>
      <div>
        <a className="desk-src-name" href={source.representative_url} target="_blank" rel="noreferrer">
          {name}
        </a>
        {source.publisher_ids.length > 1 && (
          <span className="muted"> ({source.publisher_ids.slice(1).join(', ')})</span>
        )}
        {collapse && <p className="claim-note">{collapse}</p>}
      </div>
    </div>
  )
}

function existenceElsewhere(klass: string) {
  switch (klass) {
    case 'exact_url':
      return 'Yes — we found the same article by its web address.'
    case 'title_match':
      return 'A page with the same title appeared elsewhere.'
    case 'near_duplicate':
      return 'Another page is nearly the same article.'
    case 'syndicated':
      return 'The same report was republished under other names.'
    case 'not_found':
      return 'We searched and did not find this article on another outlet.'
    case 'out_of_range':
      return "We could not search for this article on other outlets."
    default:
      return existencePlain(klass).label
  }
}

function couldNotLookItems(coverage: CoverageReport): string[] {
  const items: string[] = []
  for (const report of coverage.adapters) {
    const name = plainLabel(report.adapter)
    if (report.status === 'skipped_out_of_range') {
      items.push(
        report.reason
          ? `${name}: ${report.reason}`
          : `${name} could not cover this article's date or language.`,
      )
    } else if (report.status === 'skipped_no_key') {
      items.push(`${name} isn't configured, so we didn't search it.`)
    } else if (report.status === 'error') {
      items.push(
        report.reason
          ? `${name} failed (${report.reason}), so we couldn't search it.`
          : `${name} failed, so we couldn't search it.`,
      )
    }
  }
  if (coverage.claims_skipped.length > 0) {
    const n = coverage.claims_skipped.length
    items.push(`We didn't search ${n} of your claim${n === 1 ? '' : 's'}.`)
  }
  if (coverage.article_language == null || !coverage.language_checks_applied) {
    items.push("Language checks weren't applied.")
  }
  if (coverage.existence_keyword_rung_skipped) {
    items.push(
      "The broadest keyword search wasn't built — the headline had no distinctive words.",
    )
  }
  return items
}

function EvidenceOutput({ run }: { run: RunEnvelope }) {
  const outlets = evidenceColumns(run)
  const canDetectContradiction = run.corroboration.nli_can_detect_contradiction !== false
  const joinMisses = run.corroboration.group_join_misses ?? 0
  const claims = run.classification.claims
  const rows = run.corroboration.claims
  const [openId, setOpenId] = useState<string | null>(null)
  const gemini = run.gemini_analysis ?? []

  const contested = rows.filter((row) =>
    ['contested_reporting', 'contested'].includes(row.state),
  )
  const contradicted = rows.filter(
    (row) => (row.independent_contradict_outlets ?? 0) > 0 && canDetectContradiction,
  )
  const total = claims.length
  const support = supportRateCopy(run, total)

  let second = ''
  if (contradicted.length > 0) {
    second =
      contradicted.length === 1
        ? 'One claim is contradicted by another newsroom.'
        : `${contradicted.length} claims are contradicted by another newsroom.`
  } else if (contested.length > 0) {
    second =
      contested.length === 1
        ? 'One claim is contested — newsrooms or engines disagree.'
        : `${contested.length} claims are contested — newsrooms or engines disagree.`
  }

  const caveats: string[] = []
  if (run.corroboration.pairs_scored && !canDetectContradiction) {
    caveats.push(
      "Our contradiction detector was unavailable, so we can't say whether anything contradicts these claims.",
    )
  }
  if (joinMisses > 0) {
    caveats.push('The independent-source count may be too high.')
  }
  if ((run.corroboration.llm_dropped_id_count ?? 0) > 0) {
    caveats.push('The AI analyst referenced sources that don\'t exist; those were discarded.')
  }
  if (run.corroboration.evidence_llm_temperature_pinned === false) {
    caveats.push('This analysis may vary slightly between runs.')
  }

  const techFields: TechField[] = [
    {
      label: 'Independent-reporting support',
      value: support.techValue,
    },
    {
      label: 'Overall corroboration',
      value: corroborationStateCopy(run.corroboration.overall_state, {
        existenceClass: run.corroboration.existence_class ?? run.retrieval?.existence_class,
        unscoredReason: run.corroboration.unscored_reason,
        pairsScored: run.corroboration.pairs_scored,
      }),
      raw: run.corroboration.overall_state,
    },
    {
      label: 'Independent sources',
      value: `${run.corroboration.independent_source_count} independent newsroom${
        run.corroboration.independent_source_count === 1 ? '' : 's'
      }${
        run.retrieval
          ? ` after collapsing ${run.retrieval.document_count} page${
              run.retrieval.document_count === 1 ? '' : 's'
            }`
          : ''
      }${joinMisses > 0 ? ` (upper bound; ${joinMisses} join miss${joinMisses === 1 ? '' : 'es'})` : ''}`,
    },
    {
      label: 'NLI engine',
      value: run.corroboration.nli_engine || run.engines_used.nli || 'n/a',
    },
    {
      label: 'Evidence LLM',
      value: run.corroboration.evidence_llm_model || run.engines_used.evidence_llm || 'n/a',
    },
    {
      label: 'LLM temperature',
      value:
        run.corroboration.evidence_llm_temperature == null
          ? 'n/a'
          : String(run.corroboration.evidence_llm_temperature),
    },
    {
      label: 'Temperature pinned',
      value:
        run.corroboration.evidence_llm_temperature_pinned == null
          ? 'n/a'
          : run.corroboration.evidence_llm_temperature_pinned
            ? 'yes'
            : 'no',
    },
  ]

  const slotCount = gemini.reduce((sum, row) => sum + row.inconsistencies.length, 0)

  return (
    <LayerTiers
      run={run}
      layer={4}
      extraCount={techFields.length + rows.length + outlets.length + slotCount + 1}
      answer={
        <>
          {support.sentence}
          <p className="tier-answer-sub">{support.gloss}</p>
          {second && <p className="tier-answer-sub">{second}</p>}
        </>
      }
      evidence={
        <>
          {rows.length === 0 ? (
            <p>No fused claim scores yet.</p>
          ) : (
            <ul className="evidence-list">
              {rows.map((row) => {
                const claim = claims.find((item) => item.id === row.claim_id)
                const open = openId === row.claim_id
                return (
                  <li key={row.claim_id}>
                    <button
                      type="button"
                      className={`evidence-row${open ? ' is-open' : ''}`}
                      onClick={() => setOpenId(open ? null : row.claim_id)}
                      aria-expanded={open}
                    >
                      <span className="evidence-row-text">
                        {truncate(claim?.text || row.claim_id, 140)}
                      </span>
                      <Badge
                        code={row.state}
                        label={plainLabel(row.state)}
                        gloss={plain(row.state).gloss}
                      />
                      <span className="evidence-row-count">
                        {claimCountSentence(row, canDetectContradiction, run)}
                      </span>
                    </button>
                    {open && (
                      <div className="evidence-row-body">
                        <ClaimEvidencePairs
                          run={run}
                          claimId={row.claim_id}
                          outlets={outlets}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {caveats.map((line) => (
            <p key={line} className="caveat-line">
              {line}
            </p>
          ))}
        </>
      }
      machinery={
        <>
          <TechList fields={techFields} />
          <h5>Claim–evidence matrix</h5>
          {outlets.length === 0 || claims.length === 0 ? (
            <p>No claim×source pairs to score.</p>
          ) : (
            <div className="matrix-wrap">
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Claim</th>
                    {outlets.map((item) => (
                      <th key={item.source_id} title={item.title}>
                        {item.outlet}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {claims.map((claim) => (
                    <tr key={claim.id}>
                      <th scope="row">{claim.id}</th>
                      {outlets.map((item) => {
                        const pair = run.analysis.find(
                          (row) =>
                            row.claim_id === claim.id && row.source_id === item.source_id,
                        )
                        const klass = pair?.nli_label ?? 'neutral'
                        const nli = plain(klass)
                        const stance = pair?.gemini_stance
                          ? plain(pair.gemini_stance)
                          : null
                        const probs = pair?.nli_probs
                          ? Object.entries(pair.nli_probs)
                              .map(([key, value]) => `${plainLabel(key)} ${Math.round(value * 100)}%`)
                              .join(' · ')
                          : ''
                        return (
                          <td key={item.source_id} className={klass} title={`${klass}${probs ? ` — ${probs}` : ''}`}>
                            {nli.label}
                            {pair ? ` ${Math.round(pair.nli_score * 100)}%` : ''}
                            {stance ? ` · ${stance.label}` : ''}
                            {probs ? <span className="gloss">{probs}</span> : null}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h5>Engine agreement and NLI vs LLM</h5>
          {rows.length === 0 ? (
            <p>No fused claim scores.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {rows.map((row) => {
                const agree = agreementPlain(row.agreement)
                return (
                  <li key={row.claim_id} title={row.agreement}>
                    <code>{row.claim_id}</code> {agree.label} — NLI support {row.nli_support} /
                    contradict{' '}
                    {contradictCount(row.nli_contradict, canDetectContradiction)}; LLM support{' '}
                    {row.llm_support} / contradict {row.llm_contradict}; independent support{' '}
                    {row.independent_support_outlets ?? 0} / contradict{' '}
                    {contradictCount(row.independent_contradict_outlets, canDetectContradiction)};
                    state {plainLabel(row.state)} ({row.state})
                  </li>
                )
              })}
            </ul>
          )}
          <h5>Engine B slot inconsistencies</h5>
          {gemini.length === 0 || gemini.every((row) => row.inconsistencies.length === 0) ? (
            <p>None recorded.</p>
          ) : (
            <ul className="plain-list machinery-list">
              {gemini.flatMap((row) =>
                row.inconsistencies.map((inc, index) => (
                  <li key={`${row.claim_id}-${inc.slot}-${index}`}>
                    <code>{row.claim_id}</code> {plainLabel(inc.slot)} — {inc.summary}
                    {inc.source_ids.length ? ` (${inc.source_ids.join(', ')})` : ''}
                  </li>
                )),
              )}
            </ul>
          )}
          {gemini.some((row) => row.missing_slots.length > 0) && (
            <>
              <h5>Engine B missing slots</h5>
              <ul className="plain-list machinery-list">
                {gemini
                  .filter((row) => row.missing_slots.length > 0)
                  .map((row) => (
                    <li key={`${row.claim_id}-missing`}>
                      <code>{row.claim_id}</code> {row.missing_slots.join(', ')}
                    </li>
                  ))}
              </ul>
            </>
          )}
        </>
      }
    />
  )
}

function ClaimEvidencePairs({
  run,
  claimId,
  outlets,
}: {
  run: RunEnvelope
  claimId: string
  outlets: ReturnType<typeof evidenceColumns>
}) {
  const pairs = outlets.map((item) => {
    const pair = run.analysis.find(
      (row) => row.claim_id === claimId && row.source_id === item.source_id,
    )
    return { item, pair }
  })
  if (pairs.every((row) => !row.pair)) {
    return <p>No scored pages for this claim.</p>
  }
  return (
    <ul className="plain-list">
      {pairs.map(({ item, pair }) => {
        const nli = plain(pair?.nli_label ?? 'neutral')
        const stance = pair?.gemini_stance ? plain(pair.gemini_stance) : null
        return (
          <li key={item.source_id}>
            <a href={item.url} target="_blank" rel="noreferrer">
              {item.outlet}
            </a>
            {' — '}
            {nli.label}
            {stance ? ` · analyst: ${stance.label}` : ''}
          </li>
        )
      })}
    </ul>
  )
}

function claimCountSentence(
  row: ClaimCorroboration,
  canDetect: boolean,
  run: RunEnvelope,
) {
  if (row.state === 'not_assessed') {
    return corroborationStateCopy(row.state, {
      existenceClass: row.existence_class ?? run.corroboration.existence_class,
      unscoredReason: run.corroboration.unscored_reason,
      pairsScored: run.corroboration.pairs_scored,
    })
  }
  const support = row.independent_support_outlets ?? 0
  const contradict = row.independent_contradict_outlets
  const supportPhrase =
    support === 1 ? '1 newsroom supports' : `${support} newsrooms support`
  if (!canDetect) {
    return `${supportPhrase}; contradiction detection was unavailable`
  }
  const n = contradict ?? 0
  const contradictPhrase = n === 1 ? '1 contradicts' : `${n} contradict`
  return `${supportPhrase}, ${contradictPhrase}`
}

function UncertaintyOutput({ run }: { run: RunEnvelope }) {
  const u = run.uncertainty
  const rec = u.recommended_decision
  const unsure = [...u.unknowns, ...u.weak_evidence]
  const recPlain = rec ? plain(rec) : null
  const support = supportRateCopy(run, run.classification.claims.length)
  const joinMisses = run.corroboration.group_join_misses ?? 0

  const techFields: TechField[] = [
    {
      label: 'Recommended label (raw)',
      value: rec ?? 'none',
    },
    {
      label: 'Publication risk (raw)',
      value: u.publication_risk,
    },
    {
      label: 'Source-independence note',
      value: u.source_independence_note || 'n/a',
    },
    {
      label: 'Uncertainty model',
      value: u.model || run.engines_used.uncertainty || 'n/a',
    },
  ]

  return (
    <LayerTiers
      run={run}
      layer={5}
      extraCount={techFields.length}
      answer={
        <div className="decision-callout">
          <p className="decision-label" title={rec ?? undefined}>
            {recPlain ? recPlain.label : 'No recommendation'}
          </p>
          <p className="decision-caveat">This is decision support, not a verdict. You decide.</p>
        </div>
      }
      evidence={
        <>
          <p>
            <strong>Independent-reporting support.</strong> {support.sentence}
            <span className="gloss">{support.gloss}</span>
          </p>
          {joinMisses > 0 && <p>The independent-source count may be too high.</p>}
          <p>
            <strong>Publication risk.</strong>{' '}
            <span title={u.publication_risk}>{riskPlain(u.publication_risk).label}</span>
            <span className="gloss">{riskPlain(u.publication_risk).gloss}</span>
          </p>
          <p>{u.rationale || 'No narrative uncertainty statement was produced.'}</p>
          <h4>What we&apos;re unsure about</h4>
          {unsure.length === 0 ? (
            <p>Nothing extra was flagged.</p>
          ) : (
            <ul className="plain-list">
              {unsure.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          )}
        </>
      }
      machinery={<TechList fields={techFields} />}
    />
  )
}

function EditorialOutput({
  run,
  editorial,
}: {
  run: RunEnvelope
  editorial?: EditorialPanel
}) {
  const rec = run.uncertainty.recommended_decision
  const recorded = run.human_decision.decision
  const recPlain = rec ? plain(rec) : null
  const recordedPlain = recorded ? plain(recorded) : null
  const locked = !editorial?.active || Boolean(recorded)
  const selected = editorial?.active ? editorial.decision : recorded

  const techFields: TechField[] = recorded
    ? [
        {
          label: 'Journalist decision',
          value: recordedPlain?.label ?? recorded,
          raw: recorded,
          gloss: recordedPlain?.gloss,
        },
        {
          label: 'Recorded at (UTC)',
          value: run.human_decision.decided_at || 'n/a',
        },
        {
          label: 'Notes',
          value: run.human_decision.notes || 'none',
        },
        {
          label: 'System suggestion (raw)',
          value: rec ?? 'none',
        },
      ]
    : [
        {
          label: 'Journalist decision',
          value: 'No decision recorded yet',
        },
        {
          label: 'System suggestion (raw)',
          value: rec ?? 'none',
        },
      ]

  return (
    <LayerTiers
      run={run}
      layer={6}
      extraCount={techFields.length}
      answer={
        <div className="desk-decision">
          <p className="system-suggestion">
            The system suggests <strong title={rec ?? undefined}>{recPlain?.label ?? 'no label'}</strong>
            . This is a suggestion — you decide.
          </p>
          {editorial && (
            <div className="desk-options">
              {DECISIONS.map((option) => {
                const item = plain(option)
                return (
                  <button
                    key={option}
                    type="button"
                    className={`desk-option${selected === option ? ' is-selected' : ''}`}
                    disabled={locked || editorial.busy}
                    title={item.gloss}
                    onClick={() => editorial.onDecision(option)}
                  >
                    <b>{item.label}</b>
                    <span>{item.gloss}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      }
      evidence={
        editorial ? (
          <>
            <label className="field-label" htmlFor="chat-decision-notes">
              Editorial notes
            </label>
            <textarea
              id="chat-decision-notes"
              className="content-input"
              rows={3}
              value={editorial.active ? editorial.notes : run.human_decision.notes}
              disabled={locked || editorial.busy}
              onChange={(e) => editorial.onNotes(e.target.value)}
            />
            {editorial.active && (
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={!editorial.decision || editorial.busy}
                  onClick={editorial.onConfirm}
                >
                  Confirm editorial decision
                </button>
              </div>
            )}
          </>
        ) : (
          <p className="muted">Choose an outcome when this layer is active.</p>
        )
      }
      machinery={
        <>
          {recorded && (
            <div className="journalist-record">
              <p>
                <strong>Your recorded decision.</strong> {recordedPlain?.label} at{' '}
                {run.human_decision.decided_at || 'an unknown time'}
                {run.human_decision.notes ? ` — ${run.human_decision.notes}` : ''}
              </p>
              <p className="gloss">This is the journalist’s choice, not the system suggestion.</p>
            </div>
          )}
          <TechList fields={techFields} />
        </>
      }
    />
  )
}

function DocumentationOutput({ run }: { run: RunEnvelope }) {
  const rec = run.record
  const when = recordDate(run)
  const citations = rec.citations ?? []
  const engines = Object.entries(run.engines_used)
  const degradations = documentationDegradations(run)

  const blocks: { heading: string; body: string }[] = [
    { heading: 'Claims', body: rec.claim_summary },
    { heading: 'Sources', body: rec.source_assessment },
    { heading: 'Evidence', body: rec.evidence_summary },
    { heading: 'Cross-source', body: rec.cross_source_notes },
    { heading: 'Uncertainty', body: rec.uncertainty_statement },
    { heading: 'Recommendation', body: rec.editorial_recommendation },
  ]

  return (
    <LayerTiers
      run={run}
      layer={7}
      extraCount={citations.length + engines.length + degradations.length + 2}
      answer={
        when
          ? `Verification record — ${when}. This is what we checked and what we found.`
          : 'Verification record. This is what we checked and what we found.'
      }
      evidence={
        <article className="record">
          {blocks.map((block) => (
            <p key={block.heading}>
              <strong>{block.heading}.</strong> {block.body}
            </p>
          ))}
          <p className="stub-note">{rec.caveat}</p>
        </article>
      }
      machinery={
        <>
          <h5>Citations</h5>
          {citations.length === 0 ? (
            <p>No citations were recorded.</p>
          ) : (
            <ul className="plain-list">
              {citations.map((href) => (
                <li key={href}>
                  {looksLikeUrl(href) ? (
                    <a href={href} target="_blank" rel="noreferrer">
                      {href}
                    </a>
                  ) : (
                    href
                  )}
                </li>
              ))}
            </ul>
          )}
          <h5>Models and engines</h5>
          {engines.length === 0 ? (
            <p>None recorded. Record model: {rec.model || 'n/a'}.</p>
          ) : (
            <dl className="chat-dl">
              {engines.map(([key, value]) => (
                <Row key={key} label={key} value={value} />
              ))}
              <Row label="Record model" value={rec.model || 'n/a'} />
            </dl>
          )}
          <h5>Degradation notes</h5>
          {degradations.length === 0 ? (
            <p>No extra limitations were attached to this record.</p>
          ) : (
            <ul className="plain-list">
              {degradations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          )}
        </>
      }
    />
  )
}

function documentationDegradations(run: RunEnvelope): string[] {
  const rows: string[] = []
  if (run.input.fetch_status && run.input.fetch_status !== 'ok') {
    rows.push(
      `Fetch: ${fetchStatusPlain(run.input.fetch_status).label}${
        run.input.fetch_reason ? ` (${plainLabel(run.input.fetch_reason)})` : ''
      }.`,
    )
  }
  if (run.corroboration.nli_can_detect_contradiction === false && run.corroboration.pairs_scored) {
    rows.push('Contradiction detector was unavailable (lexical fallback).')
  }
  if (run.corroboration.evidence_llm_temperature_pinned === false) {
    rows.push('Evidence analyst temperature was not pinned.')
  }
  if ((run.corroboration.group_join_misses ?? 0) > 0) {
    rows.push(`${run.corroboration.group_join_misses} independent-source join miss(es).`)
  }
  if ((run.corroboration.llm_dropped_id_count ?? 0) > 0) {
    rows.push(`${run.corroboration.llm_dropped_id_count} invented source id(s) dropped.`)
  }
  const skipped = run.retrieval?.coverage.adapters.filter((row) =>
    row.status.startsWith('skipped'),
  )
  if (skipped?.length) {
    rows.push(
      `Adapters not run: ${skipped.map((row) => plainLabel(row.adapter)).join(', ')}.`,
    )
  }
  return rows
}

function LayerTiers({
  run,
  layer,
  answer,
  evidence,
  machinery,
  extraCount,
}: {
  run: RunEnvelope
  layer: number
  answer: ReactNode
  evidence: ReactNode
  machinery: ReactNode
  extraCount: number
}) {
  const processCount = machineryPieceCount(run, layer)
  const count = processCount + extraCount
  return (
    <>
      <div className="tier-answer">{answer}</div>
      <div className="tier-evidence">{evidence}</div>
      <details className="tech-fold">
        <summary>
          Technical detail ({count} {count === 1 ? 'field' : 'fields'})
        </summary>
        <div className="tier-machinery">
          <LayerMachinery run={run} layer={layer} />
          {machinery}
        </div>
      </details>
    </>
  )
}

type TechField = {
  label: string
  value: string
  raw?: string | null
  gloss?: string
}

function TechList({ fields }: { fields: TechField[] }) {
  if (fields.length === 0) return null
  return (
    <dl className="chat-dl">
      {fields.map((field) => (
        <Row
          key={field.label}
          label={field.label}
          value={field.value}
          raw={field.raw}
          gloss={field.gloss}
        />
      ))}
    </dl>
  )
}

function Badge({ code, label, gloss }: { code: string; label: string; gloss: string }) {
  return (
    <span className="plain-badge" title={`${code}${gloss ? ` — ${gloss}` : ''}`}>
      {label}
    </span>
  )
}

function Row({
  label,
  value,
  raw,
  gloss,
}: {
  label: string
  value: string
  raw?: string | null
  gloss?: string
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd title={raw || undefined}>
        {value}
        {gloss ? <span className="gloss">{gloss}</span> : null}
      </dd>
    </div>
  )
}

function groupEntities(entities: Entity[]): Record<string, string[]> {
  const grouped: Record<string, string[]> = {}
  for (const entity of entities) {
    const list = grouped[entity.type] || (grouped[entity.type] = [])
    if (!list.includes(entity.text)) list.push(entity.text)
  }
  return grouped
}

function evidenceColumns(run: RunEnvelope) {
  const documents = run.retrieval?.documents ?? []
  return documents.map((hit, index) => ({
    source_id: `s${index + 1}`,
    outlet: hit.publisher_domain || hit.publisher_id,
    title: hit.title,
    url: hit.url,
  }))
}

function contradictCount(value: number | undefined, canDetect: boolean): string {
  if (!canDetect) return 'unavailable'
  return String(value ?? 0)
}

function wordCount(text: string | null | undefined) {
  const trimmed = text?.trim()
  if (!trimmed) return 0
  return trimmed.split(/\s+/).length
}

function truncate(text: string, max: number) {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1).trimEnd()}…`
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function looksLikeUrl(value: string) {
  return /^https?:\/\//i.test(value)
}

function recordDate(run: RunEnvelope) {
  const raw =
    run.completed_at || run.created_at || run.human_decision.decided_at || run.input.fetch_timestamp
  if (!raw) return null
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

const SUPPORT_RATE_GLOSS = 'This is not an authenticity score.'

function supportRateCopy(run: RunEnvelope, claimCount: number) {
  const rate = run.corroboration.support_rate
  const pct = rate?.support_pct_of_scored
  if (rate && pct != null) {
    const verb = rate.backed_claim_count === 1 ? 'is' : 'are'
    const unassessed =
      rate.unassessed_claim_count > 0
        ? ` ${rate.unassessed_claim_count} claim${
            rate.unassessed_claim_count === 1 ? ' was' : 's were'
          } not scored.`
        : ''
    const sentence = `${rate.backed_claim_count} of ${rate.scored_claim_count} scored claims ${verb} backed by independent reporting (${pct}%).${unassessed}`
    return {
      sentence,
      gloss: SUPPORT_RATE_GLOSS,
      techValue: `${rate.backed_claim_count} of ${rate.scored_claim_count} scored (${pct}%); ${rate.unassessed_claim_count} unassessed, ${rate.contested_claim_count} contested`,
    }
  }

  const why = rate?.omitted_because
  const omitted = supportRateOmittedPlain(why)
  const existence = run.corroboration.existence_class ?? run.retrieval?.existence_class
  let sentence = omitted.label
  if (why === 'no_claims' || claimCount === 0) {
    sentence = 'There were no claims to score.'
  } else if (why === 'out_of_range' || existence === 'out_of_range') {
    sentence = `We could not assess these ${claimCount} claim${claimCount === 1 ? '' : 's'} — we couldn't check other outlets.`
  } else if (run.corroboration.unscored_reason === 'documents_filtered') {
    sentence = `We could not assess these ${claimCount} claim${claimCount === 1 ? '' : 's'} — pages were retrieved but none had text we could score.`
  } else {
    sentence = `We did not assess whether these ${claimCount} claim${
      claimCount === 1 ? '' : 's'
    } are backed by independent reporting.`
  }
  return {
    sentence,
    gloss: SUPPORT_RATE_GLOSS,
    techValue: `${omitted.label} (${why ?? 'not_assessed'})`,
  }
}

export function corroborationStateCopy(
  state: string,
  opts?: {
    existenceClass?: string | null
    unscoredReason?: string | null
    pairsScored?: boolean
  },
) {
  const existence = opts?.existenceClass
  const reason = opts?.unscoredReason
  const treatedAsNotAssessed =
    state === 'not_assessed' || (state === 'no_corroboration_found' && opts?.pairsScored === false)
  if (treatedAsNotAssessed) {
    if (existence === 'out_of_range') {
      return "Not assessed — we couldn't check other outlets for this claim"
    }
    if (existence === 'not_found') {
      return 'Not assessed — we searched and found no pages to score'
    }
    if (reason === 'no_claims') {
      return 'Not assessed — there were no claims to score'
    }
    if (reason === 'documents_filtered') {
      return 'Not assessed — pages were retrieved but none could be scored'
    }
    if (reason === 'no_documents') {
      return 'Not assessed — we searched and found no pages to score'
    }
    return 'Not assessed — no evidence was scored for this claim'
  }
  if (state === 'no_corroboration_found') {
    return 'Looked, found no support — pages were scored and none supported the claim'
  }
  return plain(state).label
}
