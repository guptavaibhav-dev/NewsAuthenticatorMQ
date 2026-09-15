import { LayerProcess } from './layerProcess'
import type { ReactNode } from 'react'
import type {
  Claim,
  CoverageReport,
  Entity,
  IndependentSource,
  RunEnvelope,
} from '../types/run'
import { PIPELINE_LAYERS } from '../types/run'

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

export function LayerOutput({
  layer,
  run,
  processOpen = false,
}: {
  layer: number
  run: RunEnvelope
  processOpen?: boolean
}) {
  return (
    <>
      <LayerProcess run={run} layer={layer} defaultOpen={processOpen} />
      {layer === 1 && <InputOutput run={run} />}
      {layer === 2 && <PreprocessOutput run={run} />}
      {layer === 3 && <VerificationOutput run={run} />}
      {layer === 4 && <EvidenceOutput run={run} />}
      {layer === 5 && <UncertaintyOutput run={run} />}
      {layer === 6 && <EditorialOutput run={run} />}
      {layer === 7 && <DocumentationOutput run={run} />}
    </>
  )
}

function InputOutput({ run }: { run: RunEnvelope }) {
  const input = run.input
  const resolved = input.canonical_url || input.url || 'none (pasted text only)'
  return (
    <dl className="chat-dl">
      <Row label="Resolved URL" value={resolved} />
      <Row label="Canonical source" value={input.canonical_source || 'n/a'} />
      <Row label="Publisher domain" value={input.publisher_domain || 'n/a'} />
      <Row
        label="Publisher id"
        value={
          input.publisher_id
            ? `${input.publisher_id}${input.publisher_is_platform ? ' (platform)' : ''}`
            : 'n/a'
        }
      />
      <Row label="Fetch status" value={input.fetch_status} />
      <Row label="Fetch reason" value={input.fetch_reason || 'n/a'} />
      {input.http_status != null && (
        <Row label="HTTP status" value={String(input.http_status)} />
      )}
      {input.content_type && <Row label="Content type" value={input.content_type} />}
      <Row label="Fetch timestamp" value={input.fetch_timestamp || 'n/a'} />
      <Row label="Extracted headline" value={input.fetched_title || 'n/a'} />
      <Row
        label="Extracted body"
        value={`${input.extracted_char_count ?? 0} characters`}
      />
      <Row
        label="Pasted text merged"
        value={input.text_merged ? 'yes — pasted text prepended to the fetched body' : 'no'}
      />
      {input.fetch_error && <Row label="Fetch error" value={input.fetch_error} />}
      {input.retry_after && <Row label="Retry-After" value={input.retry_after} />}
    </dl>
  )
}

function ClaimRow({ claim }: { claim: Claim }) {
  const grounding = claim.grounding ?? 'not_found'
  const ungrounded = grounding === 'not_found'
  return (
    <li className={ungrounded ? 'claim-unverified' : undefined}>
      <code>{claim.id}</code> {claim.text}{' '}
      <span className="muted">({claim.kind})</span>
      {claim.agreement_note && <p className="claim-note muted">{claim.agreement_note}</p>}
      {claim.variant_texts && claim.variant_texts.length > 1 && (
        <p className="claim-note muted">
          Other pass worded it: “{claim.variant_texts.filter((t) => t !== claim.text)[0]}”
        </p>
      )}
      {ungrounded ? (
        <>
          {' '}
          <strong className="claim-flag">unverified — quote not found in article</strong>
          {claim.source_quote ? (
            <p className="claim-quote muted">
              Model supplied: “{claim.source_quote}” — this text does not appear in the
              article. Treat the claim as unsourced until you check it.
            </p>
          ) : (
            <p className="claim-quote muted">
              The model supplied no supporting quote. Treat the claim as unsourced until you
              check it.
            </p>
          )}
        </>
      ) : (
        <p className="claim-quote">
          “{claim.source_quote}”{' '}
          <span className="muted">
            {grounding === 'exact' ? 'verbatim' : 'matched after normalisation'}
            {claim.span_start != null ? ` · chars ${claim.span_start}–${claim.span_end}` : ''}
            {claim.claim_source ? ` · ${claim.claim_source}` : ''}
          </span>
        </p>
      )}
    </li>
  )
}

function ClaimGroup({
  title,
  blurb,
  claims,
}: {
  title: string
  blurb: string
  claims: Claim[]
}) {
  return (
    <section className="claim-group">
      <h5>
        {title} <span className="muted">({claims.length})</span>
      </h5>
      {claims.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <>
          <p className="muted">{blurb}</p>
          <ol className="plain-list">
            {claims.map((claim) => (
              <ClaimRow key={claim.id} claim={claim} />
            ))}
          </ol>
        </>
      )}
    </section>
  )
}

function PreprocessOutput({ run }: { run: RunEnvelope }) {
  const cls = run.classification
  const grouped = groupEntities(cls.entities)
  const ungrounded =
    cls.ungrounded_claim_count ??
    cls.claims.filter((claim) => (claim.grounding ?? 'not_found') === 'not_found').length
  const crossChecked = Boolean(cls.pass_b_model)
  const byAgreement = {
    both: cls.claims.filter((claim) => (claim.agreement ?? 'both') === 'both'),
    pass_a_only: cls.claims.filter((claim) => claim.agreement === 'pass_a_only'),
    pass_b_only: cls.claims.filter((claim) => claim.agreement === 'pass_b_only'),
  }
  const totalClaims = cls.total_claims ?? cls.claims.length
  const agreementRate = cls.claim_agreement_rate ?? 0
  return (
    <div className="chat-block">
      <p>
        <strong>Content type.</strong> {cls.content_type}
      </p>
      <p>
        <strong>Headline.</strong> {cls.headline || 'none extracted'}
      </p>
      <h4>Atomic claims</h4>
      <p>
        <strong>Claims extracted.</strong> {totalClaims}
        {crossChecked ? (
          <>
            {' '}· {Math.round(agreementRate * 100)}% found by both passes (
            {byAgreement.both.length} of {totalClaims})
          </>
        ) : null}
      </p>
      {crossChecked ? (
        <p className="muted">
          Extracted twice, independently, by {cls.pass_a_model} and {cls.pass_b_model}, then
          matched on where each claim sits in the article. Agreement means the two extractors
          picked the same passage — it is not a verdict on whether the claim is true.
          {cls.passes_independent === false && (
            <>
              {' '}
              <strong>
                Both passes ran on the same model, so this is not an independent cross-check.
              </strong>
            </>
          )}
        </p>
      ) : (
        <p className="muted">
          Extracted in a single pass ({cls.pass_a_model ?? cls.preprocess_model}); claims were
          not cross-checked against a second pass.
        </p>
      )}
      {ungrounded > 0 && (
        <p className="claim-warning">
          {ungrounded} of {cls.claims.length} claim{cls.claims.length === 1 ? '' : 's'} quote
          text that is not in the article. They are kept below and marked unverified. This
          reflects extraction quality, not the truth of the article.
        </p>
      )}
      {cls.claims.length === 0 ? (
        <p className="muted">No atomic claims were extracted.</p>
      ) : crossChecked ? (
        <>
          <ClaimGroup
            title="Agreed by both passes"
            blurb="Both extraction passes picked out the same passage. They agreed on what the article says — that is not a judgement that the claim is true."
            claims={byAgreement.both}
          />
          <ClaimGroup
            title={`Pass A only (${cls.pass_a_model})`}
            blurb="Only the first pass extracted these. Lower extraction confidence, not wrong — check them yourself."
            claims={byAgreement.pass_a_only}
          />
          <ClaimGroup
            title={`Pass B only (${cls.pass_b_model})`}
            blurb="Only the cross-check pass extracted these. Lower extraction confidence, not wrong — check them yourself."
            claims={byAgreement.pass_b_only}
          />
        </>
      ) : (
        <ol className="plain-list">
          {cls.claims.map((claim) => (
            <ClaimRow key={claim.id} claim={claim} />
          ))}
        </ol>
      )}
      <h4>Entities</h4>
      {cls.entities.length === 0 ? (
        <p className="muted">No entities extracted.</p>
      ) : (
        <dl className="chat-dl">
          {Object.entries(grouped).map(([type, names]) => (
            <Row key={type} label={type} value={names.join(', ')} />
          ))}
        </dl>
      )}
      <p>
        <strong>Date window.</strong>{' '}
        {cls.date_window.start || cls.date_window.end
          ? `${cls.date_window.start || '?'} → ${cls.date_window.end || '?'} (${cls.date_window.confidence})`
          : `none (${cls.date_window.confidence})`}
      </p>
      <h4>NER / LLM disagreements</h4>
      {cls.disagreements.length === 0 ? (
        <p className="muted">None recorded.</p>
      ) : (
        <ul className="plain-list">
          {cls.disagreements.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function VerificationOutput({ run }: { run: RunEnvelope }) {
  const retrieval = run.retrieval
  if (!retrieval) {
    return (
      <p className="muted">Layer 3 has not produced a retrieval payload yet.</p>
    )
  }
  const coverage = retrieval.coverage
  return (
    <div className="chat-block">
      <div className="count-pair">
        <div>
          <p className="count-kicker">Pages retrieved</p>
          <p className="count-figure">{retrieval.document_count}</p>
          <p className="muted">Distinct documents. Syndication inflates this.</p>
        </div>
        <div className="count-primary">
          <p className="count-kicker">Independent sources</p>
          <p className="count-figure">{retrieval.independent_source_count}</p>
          <p className="muted">Genuinely separate newsrooms. This is the number that bears on corroboration.</p>
        </div>
      </div>
      <p>
        Page count is not corroboration. Twenty papers carrying one wire report are twenty
        documents and one source.
      </p>

      <h4>Existence</h4>
      <p>{existenceStatement(retrieval.existence_class)}</p>
      <p className="muted">
        Title match strength: {retrieval.title_match_strength}.{' '}
        {ladderStatement(coverage)}
      </p>

      <h4>Independent sources</h4>
      {retrieval.independent_sources.length === 0 ? (
        <p className="muted">None grouped — there are no retrieved documents to collapse.</p>
      ) : (
        <ul className="plain-list source-list">
          {retrieval.independent_sources.map((source) => (
            <li key={source.source_id}>
              <SourceRow source={source} />
            </li>
          ))}
        </ul>
      )}

      <h4>Coverage</h4>
      <CoverageBlock coverage={coverage} />

      {retrieval.factchecks.length > 0 && (
        <>
          <h4>Prior fact-checks</h4>
          <ul className="plain-list">
            {retrieval.factchecks.map((record) => (
              <li key={record.review_url}>
                <strong>{record.reviewer_name || 'An unnamed reviewer'}</strong> rated this
                claim “{record.rating_text}”. That is {record.reviewer_name || 'their'} rating,
                not NewsAuth’s.{' '}
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

      <h4>Retrieved documents</h4>
      {retrieval.documents.length === 0 ? (
        <p className="muted">No documents after retrieval.</p>
      ) : (
        <ul className="plain-list">
          {retrieval.documents.map((hit) => (
            <li key={hit.canonical_url || hit.url}>
              <a href={hit.url} target="_blank" rel="noreferrer">
                {hit.title || hit.url}
              </a>{' '}
              <span className="muted">
                {hit.publisher_domain}
                {hit.wire_credit ? ` · wire: ${hit.wire_credit}` : ''}
                {hit.relevance_score != null
                  ? ` · ${hit.relevance_score.toFixed(2)} (${retrieval.ranking_method || 'unranked'})`
                  : retrieval.ranking_method
                    ? ` · unranked (${retrieval.ranking_method})`
                    : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SourceRow({ source }: { source: IndependentSource }) {
  const outlets = source.publisher_ids.join(', ') || source.representative_url
  const reason =
    source.merge_reason === 'none'
      ? 'stands alone'
      : source.merge_reason.replaceAll('_', ' ')
  return (
    <>
      <a href={source.representative_url} target="_blank" rel="noreferrer">
        {outlets}
      </a>{' '}
      <span className="muted">
        {source.member_urls.length} page{source.member_urls.length === 1 ? '' : 's'} · {reason}
      </span>
      <p className="claim-note">{source.merge_evidence}</p>
    </>
  )
}

function CoverageBlock({ coverage }: { coverage: CoverageReport }) {
  return (
    <>
      <p>{ladderStatement(coverage)}</p>
      {coverage.existence_keyword_rung_skipped && (
        <p>
          The broadest (keyword) existence query was not built — the headline had no
          distinctive non-stopword words. The search stopped one step short of usual.
        </p>
      )}
      {coverage.article_language == null && (
        <p>Language checks not applied — the article’s language is unknown.</p>
      )}
      {coverage.capability_notes.length > 0 ? (
        <ul className="plain-list">
          {coverage.capability_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No capability checks were skipped for missing metadata.</p>
      )}
      {coverage.adapters.length > 0 && (
        <ul className="plain-list">
          {coverage.adapters.map((report) => (
            <li key={report.adapter}>
              <code>{report.adapter}</code> {report.status}
              {report.reason ? ` — ${report.reason}` : ''}
              {report.checks_skipped.length
                ? ` (skipped checks: ${report.checks_skipped.join(', ')})`
                : ''}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function existenceStatement(klass: string) {
  switch (klass) {
    case 'not_found':
      return 'No coverage found — this is an open question.'
    case 'out_of_range':
      return 'Never looked — no configured adapter could search this article.'
    case 'exact_url':
      return 'The same article was found by canonical URL.'
    case 'title_match':
      return 'A retrieved page carries the same title.'
    case 'near_duplicate':
      return 'A retrieved page is a near-duplicate of the submitted article.'
    case 'syndicated':
      return 'The same report was republished under other mastheads. One story, several pages.'
    default:
      return labelize(klass)
  }
}

function ladderStatement(coverage: CoverageReport) {
  if (coverage.existence_search === 'not_planned') {
    return `Existence search was never planned (${coverage.existence_rungs_planned} rungs). We did not look.`
  }
  if (coverage.existence_search === 'exhausted') {
    return `Existence search ran ${coverage.existence_rungs_planned} rung(s) and found nothing.`
  }
  return `Existence search matched (${coverage.existence_rungs_planned} rung(s) planned).`
}

function EvidenceOutput({ run }: { run: RunEnvelope }) {
  const outlets = evidenceColumns(run)
  const canDetectContradiction = run.corroboration.nli_can_detect_contradiction !== false
  const joinMisses = run.corroboration.group_join_misses ?? 0
  return (
    <div className="chat-block">
      <Fold title="Claim–evidence matrix">
        {outlets.length === 0 || run.classification.claims.length === 0 ? (
          <p className="muted">No claim×source pairs to score.</p>
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
                {run.classification.claims.map((claim) => (
                  <tr key={claim.id}>
                    <th scope="row">{claim.id}</th>
                    {outlets.map((item) => {
                      const pair = run.analysis.find(
                        (row) =>
                          row.claim_id === claim.id && row.source_id === item.source_id,
                      )
                      const klass = pair?.nli_label ?? 'neutral'
                      return (
                        <td key={item.source_id} className={klass}>
                          {klass}
                          {pair ? ` ${Math.round(pair.nli_score * 100)}%` : ''}
                          {pair?.gemini_stance ? ` · LLM ${pair.gemini_stance}` : ''}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Fold>
      {run.corroboration.pairs_scored && !canDetectContradiction && (
        <p className="muted">
          Contradiction detection was unavailable (lexical NLI fallback). Counts
          below do not mean no contradiction was found.
        </p>
      )}
      {joinMisses > 0 && (
        <p className="muted">
          {joinMisses} document{joinMisses === 1 ? '' : 's'} did not join an
          IndependentSource group. Independent-source counts are an upper bound.
        </p>
      )}
      {(run.corroboration.llm_dropped_id_count ?? 0) > 0 && (
        <p className="muted">
          Engine B cited {run.corroboration.llm_dropped_id_count} source id
          {(run.corroboration.llm_dropped_id_count ?? 0) === 1 ? '' : 's'} that
          were not in the evidence list. Those were dropped and did not count as
          stance.
        </p>
      )}
      {run.corroboration.evidence_llm_temperature_pinned === false && (
        <p className="muted">
          Engine B sampling was not pinned
          {run.corroboration.evidence_llm_model
            ? ` (${run.corroboration.evidence_llm_model})`
            : ''}
          . Fusion input may differ across runs.
        </p>
      )}
      <h4>Support vs contradict (independent sources)</h4>
      {run.corroboration.claims.length === 0 ? (
        <p className="muted">No fused claim scores yet.</p>
      ) : (
        <ul className="plain-list">
          {run.corroboration.claims.map((row) => (
            <li key={row.claim_id}>
              <code>{row.claim_id}</code>{' '}
              {row.state === 'not_assessed' ? (
                corroborationStateCopy(row.state, {
                  existenceClass: row.existence_class ?? run.corroboration.existence_class,
                  unscoredReason: run.corroboration.unscored_reason,
                  pairsScored: run.corroboration.pairs_scored,
                })
              ) : (
                <>
                  sources support {row.independent_support_outlets ?? 0} / contradict{' '}
                  {contradictCount(row.independent_contradict_outlets, canDetectContradiction)}
                  ; NLI support {row.nli_support} / contradict{' '}
                  {contradictCount(row.nli_contradict, canDetectContradiction)}; LLM support{' '}
                  {row.llm_support} / contradict {row.llm_contradict}; agreement{' '}
                  {row.agreement}; state {labelize(row.state)}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p>
        <strong>Independent sources.</strong> {run.corroboration.independent_source_count}
        {joinMisses > 0 && (
          <span className="muted"> (upper bound; {joinMisses} join miss{joinMisses === 1 ? '' : 'es'})</span>
        )}
        {run.retrieval != null && (
          <span className="muted">
            {' '}
            — after collapsing {run.retrieval.document_count} page
            {run.retrieval.document_count === 1 ? '' : 's'}. Page count is not corroboration.
          </span>
        )}
      </p>
      <p>
        <strong>Overall corroboration.</strong>{' '}
        {corroborationStateCopy(run.corroboration.overall_state, {
          existenceClass: run.corroboration.existence_class ?? run.retrieval?.existence_class,
          unscoredReason: run.corroboration.unscored_reason,
          pairsScored: run.corroboration.pairs_scored,
        })}
      </p>
    </div>
  )
}

function UncertaintyOutput({ run }: { run: RunEnvelope }) {
  const u = run.uncertainty
  return (
    <div className="chat-block">
      <p>{u.rationale || 'No narrative uncertainty statement was produced.'}</p>
      <h4>Unknowns</h4>
      {u.unknowns.length === 0 ? (
        <p className="muted">None recorded.</p>
      ) : (
        <ul className="plain-list">
          {u.unknowns.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
      <h4>Weak-evidence flags</h4>
      {u.weak_evidence.length === 0 ? (
        <p className="muted">None recorded.</p>
      ) : (
        <ul className="plain-list">
          {u.weak_evidence.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
      {u.source_independence_note && <p className="muted">{u.source_independence_note}</p>}
      <p>
        <strong>Publication risk.</strong> {u.publication_risk}
      </p>
      <p>
        <strong>Recommended label.</strong> {u.recommended_decision ?? 'none'}{' '}
        <span className="muted">(recommendation only — not a verdict)</span>
      </p>
    </div>
  )
}

function EditorialOutput({ run }: { run: RunEnvelope }) {
  const rec = run.uncertainty.recommended_decision
  const recorded = run.human_decision.decision
  return (
    <div className="chat-block">
      <p>
        <strong>System recommendation (read-only).</strong> {rec ?? 'none'}. This is not a
        verdict and is not auto-committed.
      </p>
      {recorded && (
        <p>
          <strong>Journalist record.</strong> {recorded.replaceAll('_', ' ')}
          {run.human_decision.decided_at ? ` at ${run.human_decision.decided_at}` : ''}
          {run.human_decision.notes ? ` — ${run.human_decision.notes}` : ''}
        </p>
      )}
    </div>
  )
}

function DocumentationOutput({ run }: { run: RunEnvelope }) {
  const rec = run.record
  return (
    <Fold title="Verification record">
      <article className="record">
        <p>
          <strong>Claims.</strong> {rec.claim_summary}
        </p>
        <p>
          <strong>Sources.</strong> {rec.source_assessment}
        </p>
        <p>
          <strong>Evidence.</strong> {rec.evidence_summary}
        </p>
        <p>
          <strong>Cross-source.</strong> {rec.cross_source_notes}
        </p>
        <p>
          <strong>Uncertainty.</strong> {rec.uncertainty_statement}
        </p>
        <p>
          <strong>Recommendation.</strong> {rec.editorial_recommendation}
        </p>
        <p className="stub-note">{rec.caveat}</p>
      </article>
    </Fold>
  )
}

function Fold({
  title,
  children,
  open = true,
}: {
  title: string
  children: ReactNode
  open?: boolean
}) {
  return (
    <details className="chat-fold" open={open}>
      <summary>{title}</summary>
      <div className="chat-fold-body">{children}</div>
    </details>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
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

function labelize(value: string) {
  return value.replaceAll('_', ' ')
}

function contradictCount(value: number | undefined, canDetect: boolean): string {
  if (!canDetect) return 'unavailable'
  return String(value ?? 0)
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
    let why = 'no evidence was available to score'
    if (existence === 'out_of_range') why = 'sources could not cover this article'
    else if (existence === 'not_found') why = 'no coverage found'
    else if (reason === 'no_claims') why = 'there were no claims to score'
    else if (reason === 'documents_filtered') why = 'documents were retrieved but none could be scored'
    else if (reason === 'no_documents') why = 'no coverage found'
    return `Not assessed — no evidence was scored for this claim (${why})`
  }
  if (state === 'no_corroboration_found') {
    return 'No corroboration found — pairs were scored and none supported the claim'
  }
  return labelize(state)
}
