import { LayerProcess } from './layerProcess'
import type { ReactNode } from 'react'
import type { Entity, RunEnvelope } from '../types/run'
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
        run.queries.planner_model || run.engines_used.verification_planner,
        run.engines_used.embeddings,
      ]
        .filter(Boolean)
        .join(' · ') || 'verification tools'
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
  const media = run.tool_results.find((row) => row.tool === 'media')
  const resolved = input.canonical_url || input.url || 'none (pasted text only)'
  return (
    <dl className="chat-dl">
      <Row label="Resolved URL" value={resolved} />
      <Row label="Publisher domain" value={input.publisher_domain || 'n/a'} />
      <Row label="Fetch status" value={input.fetch_status} />
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
      <Row
        label="Media-provenance hook"
        value={media ? `${media.status}: ${media.detail}` : 'skipped'}
      />
      {input.fetch_error && <Row label="Fetch error" value={input.fetch_error} />}
    </dl>
  )
}

function PreprocessOutput({ run }: { run: RunEnvelope }) {
  const cls = run.classification
  const grouped = groupEntities(cls.entities)
  return (
    <div className="chat-block">
      <p>
        <strong>Content type.</strong> {cls.content_type}
      </p>
      <p>
        <strong>Headline.</strong> {cls.headline || 'none extracted'}
      </p>
      <h4>Atomic claims</h4>
      {cls.claims.length === 0 ? (
        <p className="muted">No atomic claims were extracted.</p>
      ) : (
        <ol className="plain-list">
          {cls.claims.map((claim) => (
            <li key={claim.id}>
              <code>{claim.id}</code> {claim.text}{' '}
              <span className="muted">({claim.kind})</span>
            </li>
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
  const q = run.queries
  const tools = run.tool_results.filter((row) => row.tool !== 'media')
  const before = tools.reduce((sum, row) => sum + (row.hit_count || 0), 0)
  const after = run.evidence_items.length
  return (
    <div className="chat-block">
      <h4>Planned queries</h4>
      <dl className="chat-dl">
        <Row label="Quoted headline" value={q.quoted_headline || 'n/a'} />
        <Row label="Event boolean" value={q.event_boolean || 'n/a'} />
        <Row label="Fact-check query" value={q.factcheck_query || 'n/a'} />
        <Row
          label="Entity queries"
          value={(q.entity_queries || []).join(', ') || 'n/a'}
        />
        <Row
          label="Date range"
          value={
            q.date_from || q.date_to ? `${q.date_from || '?'} → ${q.date_to || '?'}` : 'n/a'
          }
        />
        <Row
          label="Planner"
          value={`${q.planner_mode}${q.planner_model ? ` · ${q.planner_model}` : ''}`}
        />
      </dl>
      <p>
        <strong>Hit counts.</strong> {before} before dedupe · {after} ranked items kept.
      </p>
      <p>
        <strong>Existence class.</strong> {labelize(run.corroboration.existence.existence_class)}
        {run.corroboration.existence.notes ? ` — ${run.corroboration.existence.notes}` : ''}
      </p>
    </div>
  )
}

function EvidenceOutput({ run }: { run: RunEnvelope }) {
  const outlets = uniqueOutlets(run)
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
      <h4>Support vs contradict (publisher families)</h4>
      {run.corroboration.claims.length === 0 ? (
        <p className="muted">No fused claim scores yet.</p>
      ) : (
        <ul className="plain-list">
          {run.corroboration.claims.map((row) => (
            <li key={row.claim_id}>
              <code>{row.claim_id}</code> families support {row.independent_support_outlets ?? 0} /
              contradict {row.independent_contradict_outlets ?? 0}; NLI support {row.nli_support} /
              contradict {row.nli_contradict}; LLM support {row.llm_support} / contradict{' '}
              {row.llm_contradict}; agreement {row.agreement}; state {labelize(row.state)}
            </li>
          ))}
        </ul>
      )}
      <p>
        <strong>Independent families.</strong> {run.corroboration.independent_source_count}
      </p>
      <p>
        <strong>Overall corroboration.</strong> {labelize(run.corroboration.overall_state)}
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

function uniqueOutlets(run: RunEnvelope) {
  return [...new Map(run.evidence_items.map((item) => [item.source_id, item])).values()]
}

function labelize(value: string) {
  return value.replaceAll('_', ' ')
}
