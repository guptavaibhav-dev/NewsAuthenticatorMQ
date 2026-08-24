import { useEffect, useMemo, useState } from 'react'
import { fetchHealth, fetchRun, startRun, submitDecision, subscribeRun } from './lib/api'
import SystemHealth from './SystemHealth'
import type {
  EditorialDecision,
  Health,
  RunEnvelope,
  TraceEvent,
} from './types/run'
import { DECISIONS, LAYERS } from './types/run'

type Status = 'idle' | 'running' | 'done' | 'error'
type Tab = 'authenticate' | 'system'

export default function App() {
  const [tab, setTab] = useState<Tab>('authenticate')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [trace, setTrace] = useState<TraceEvent[]>([])
  const [run, setRun] = useState<RunEnvelope | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthLoading, setHealthLoading] = useState(false)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [decision, setDecision] = useState<EditorialDecision | null>(null)
  const [notes, setNotes] = useState('')
  const [decisionSaved, setDecisionSaved] = useState(false)

  async function loadHealth(probe: boolean) {
    setHealthLoading(true)
    setHealthError(null)
    const next = await fetchHealth(probe)
    if (!next) {
      setHealthError('Could not reach the API. Start it with npm run api.')
    } else {
      setHealth(next)
    }
    setHealthLoading(false)
  }

  useEffect(() => {
    void loadHealth(false)
  }, [])

  useEffect(() => {
    if (tab === 'system') {
      void loadHealth(true)
    }
  }, [tab])

  const canRun = Boolean(text.trim() || url.trim())

  async function handleRun() {
    if (!canRun) return
    setStatus('running')
    setTrace([])
    setRun(null)
    setError(null)
    setDecision(null)
    setNotes('')
    setDecisionSaved(false)
    try {
      const runId = await startRun(text, url)
      const stop = subscribeRun(
        runId,
        (event) => setTrace((prev) => [...prev, event]),
        () => {
          void fetchRun(runId)
            .then((envelope) => {
              setRun(envelope)
              setTrace(envelope.trace)
              setStatus(envelope.status === 'error' ? 'error' : 'done')
              if (envelope.status === 'error') {
                setError(envelope.error || 'Pipeline error')
              }
            })
            .catch((err: Error) => {
              setError(err.message)
              setStatus('error')
            })
        },
      )
      return () => stop()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start run')
      setStatus('error')
    }
  }

  async function handleDecision() {
    if (!run || !decision) return
    const updated = await submitDecision(run.run_id, decision, notes)
    setRun(updated)
    setDecisionSaved(true)
  }

  function handleClear() {
    setText('')
    setUrl('')
    setTrace([])
    setRun(null)
    setError(null)
    setStatus('idle')
    setDecision(null)
    setNotes('')
    setDecisionSaved(false)
  }

  const layerState = useMemo(() => layerStatuses(trace, status), [trace, status])

  return (
    <div className="app">
      <header className="header">
        <p className="brand">NewsAuth</p>
        <p className="tagline">
          A journalist-centred framework for authenticating news content
        </p>
        <nav className="tabs" aria-label="Main">
          <button
            type="button"
            className={tab === 'authenticate' ? 'tab on' : 'tab'}
            onClick={() => setTab('authenticate')}
          >
            Authenticate
          </button>
          <button
            type="button"
            className={tab === 'system' ? 'tab on' : 'tab'}
            onClick={() => setTab('system')}
          >
            System
          </button>
        </nav>
      </header>

      <main className="main">
        {tab === 'system' ? (
          <SystemHealth
            health={health}
            loading={healthLoading}
            error={healthError}
            onRefresh={() => void loadHealth(true)}
          />
        ) : (
          <>
        <section className="panel input-panel" aria-labelledby="input-heading">
          <h1 id="input-heading">Authenticate</h1>
          <p className="lede">
            Paste a claim or article, or provide a public URL. Each layer uses a
            different engine. The system collects evidence; it does not decide
            authenticity.
          </p>

          <label className="field-label" htmlFor="news-url">
            Article URL
          </label>
          <input
            id="news-url"
            className="content-input url-input"
            type="url"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />

          <label className="field-label" htmlFor="news-content">
            News content
          </label>
          <textarea
            id="news-content"
            className="content-input"
            placeholder="Paste a headline, claim, or article text…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
          />

          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => void handleRun()}
              disabled={!canRun || status === 'running'}
            >
              {status === 'running' ? 'Running pipeline…' : 'Run verification'}
            </button>
            <button
              type="button"
              className="ghost"
              onClick={handleClear}
              disabled={status === 'running'}
            >
              Clear
            </button>
          </div>
        </section>

        <section className="inspector" aria-labelledby="inspector-heading">
          <h2 id="inspector-heading">Verification inspector</h2>
          <p className="caveat">
            Decision support only. Outputs are signals, not a true/false verdict.
            Final editorial judgement stays with the journalist.
          </p>

          {status === 'idle' && (
            <p className="muted">
              No run yet. Submit text or a URL to watch each process examine a
              specific parameter of the input.
            </p>
          )}

          {status !== 'idle' && (
            <ol className="stepper" aria-label="Framework layers">
              {LAYERS.map((layer) => (
                <li key={layer.id} className={layerState[layer.id] || 'idle'}>
                  <span className="step-name">{layer.label}</span>
                  <span className="step-state">{layerState[layer.id] || 'idle'}</span>
                </li>
              ))}
            </ol>
          )}

          {status === 'running' && (
            <p className="muted pulse">Examining content through the layered pipeline…</p>
          )}
          {error && <p className="error">{error}</p>}

          {trace.length > 0 && (
            <div className="timeline-wrap">
              <h3>Process log</h3>
              <ol className="timeline">
                {trace.map((event, index) => (
                  <li key={`${event.ts}-${index}`} className={`evt ${event.status}`}>
                    <span className="evt-layer">{event.layer}</span>
                    <span className="evt-process">{event.process}</span>
                    <span className="evt-param">parameter: {event.parameter}</span>
                    {event.tool && <span className="evt-tool">tool: {event.tool}</span>}
                    {event.detail && <span className="evt-detail">{event.detail}</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {run && (status === 'done' || status === 'error') && <RunResults run={run} />}

          {run && (status === 'done' || status === 'error') && (
            <section className="decision" aria-labelledby="decision-heading">
              <h3 id="decision-heading">Human editorial decision</h3>
              <p className="muted">
                System recommendation:{' '}
                <strong>{run.uncertainty.recommended_decision ?? 'none'}</strong>
                . Choose the newsroom outcome. This is not auto-committed.
              </p>
              <div className="decision-grid">
                {DECISIONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={decision === option ? 'primary' : 'ghost'}
                    onClick={() => {
                      setDecision(option)
                      setDecisionSaved(false)
                    }}
                  >
                    {option.replaceAll('_', ' ')}
                  </button>
                ))}
              </div>
              <label className="field-label" htmlFor="decision-notes">
                Editorial notes
              </label>
              <textarea
                id="decision-notes"
                className="content-input"
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={!decision}
                  onClick={() => void handleDecision()}
                >
                  Save editorial decision
                </button>
              </div>
              {decisionSaved && run.human_decision.decision && (
                <p className="muted">
                  Recorded {run.human_decision.decision.replaceAll('_', ' ')} at{' '}
                  {run.human_decision.decided_at}.
                </p>
              )}
            </section>
          )}
            </section>
          </>
        )}
      </main>

      <footer className="footer">
        <p>Thesis prototype · COMP4092 · Macquarie University</p>
      </footer>
    </div>
  )
}

function RunResults({ run }: { run: RunEnvelope }) {
  const outlets = [...new Map(run.evidence_items.map((item) => [item.source_id, item])).values()]

  return (
    <div className="results-stack">
      <dl className="result-grid">
        <div>
          <dt>Existence</dt>
          <dd>{labelize(run.corroboration.existence.existence_class)}</dd>
        </div>
        <div>
          <dt>Corroboration</dt>
          <dd>{labelize(run.corroboration.overall_state)}</dd>
        </div>
        <div>
          <dt>Independent families</dt>
          <dd>{run.corroboration.independent_source_count}</dd>
        </div>
        <div>
          <dt>Publication risk</dt>
          <dd>{run.uncertainty.publication_risk}</dd>
        </div>
      </dl>

      <p className="engines">
        Engines:{' '}
        {Object.entries(run.engines_used)
          .map(([layer, model]) => `${layer}: ${model}`)
          .join(' · ')}
      </p>

      {run.classification.headline && (
        <p>
          <strong>Headline.</strong> {run.classification.headline}
        </p>
      )}
      {run.input.url && (
        <p className="muted">
          URL fetch: {run.input.fetch_status}
          {run.input.fetch_error ? ` — ${run.input.fetch_error}` : ''}
          {run.input.publisher_domain ? ` · ${run.input.publisher_domain}` : ''}
        </p>
      )}

      <h3>Claims</h3>
      <ul className="plain-list">
        {run.classification.claims.map((claim) => (
          <li key={claim.id}>
            <code>{claim.id}</code> {claim.text}{' '}
            <span className="muted">({claim.kind})</span>
          </li>
        ))}
      </ul>

      {run.classification.disagreements.length > 0 && (
        <>
          <h3>NER / LLM disagreements</h3>
          <ul className="plain-list">
            {run.classification.disagreements.map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
        </>
      )}

      {outlets.length > 0 && run.classification.claims.length > 0 && (
        <>
          <h3>Claim–evidence matrix</h3>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th>Claim</th>
                  {outlets.map((item) => (
                    <th key={item.source_id} title={item.title}>
                      <a href={item.url} target="_blank" rel="noreferrer">
                        {item.outlet}
                      </a>
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
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h3>Retrieved evidence</h3>
      {outlets.length === 0 ? (
        <p className="muted">
          No portal hits. That is recorded as missing corroboration, not as proof
          the content is false.
        </p>
      ) : (
        <ul className="plain-list">
          {outlets.map((item) => (
            <li key={item.source_id}>
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.title || item.url}
              </a>{' '}
              <span className="muted">
                {item.outlet} · {item.tool} · {item.source_band}
              </span>
            </li>
          ))}
        </ul>
      )}

      {run.corroboration.fact_checks.length > 0 && (
        <>
          <h3>Prior fact-checks</h3>
          <ul className="plain-list">
            {run.corroboration.fact_checks.map((fc, i) => (
              <li key={fc.url || String(i)}>
                {fc.publisher}: {fc.textual_rating} — {fc.claim_text}{' '}
                {fc.url && (
                  <a href={fc.url} target="_blank" rel="noreferrer">
                    source
                  </a>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {run.wiki_hits.length > 0 && (
        <>
          <h3>Entity grounding</h3>
          <ul className="plain-list">
            {run.wiki_hits.map((hit) => (
              <li key={hit.query}>
                {hit.query}: {hit.found ? hit.title : 'no page'}{' '}
                {hit.url && (
                  <a href={hit.url} target="_blank" rel="noreferrer">
                    open
                  </a>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Uncertainty</h3>
      <p>{run.uncertainty.rationale}</p>
      {run.uncertainty.unknowns.length > 0 && (
        <ul className="plain-list">
          {run.uncertainty.unknowns.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
      {run.uncertainty.weak_evidence.length > 0 && (
        <ul className="plain-list">
          {run.uncertainty.weak_evidence.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
      <p className="muted">{run.uncertainty.source_independence_note}</p>

      <h3>Verification record</h3>
      <article className="record">
        <p>
          <strong>Claims.</strong> {run.record.claim_summary}
        </p>
        <p>
          <strong>Sources.</strong> {run.record.source_assessment}
        </p>
        <p>
          <strong>Evidence.</strong> {run.record.evidence_summary}
        </p>
        <p>
          <strong>Cross-source.</strong> {run.record.cross_source_notes}
        </p>
        <p>
          <strong>Uncertainty.</strong> {run.record.uncertainty_statement}
        </p>
        <p>
          <strong>Recommendation.</strong> {run.record.editorial_recommendation}
        </p>
        <p className="stub-note">{run.record.caveat}</p>
      </article>
    </div>
  )
}

function layerStatuses(trace: TraceEvent[], status: Status): Record<string, string> {
  const map: Record<string, string> = {}
  const hadError = new Set<string>()
  const recovered = new Set<string>()
  for (const event of trace) {
    if (event.layer === 'pipeline') continue
    if (event.status === 'error') hadError.add(event.layer)
    if (event.status === 'ok' || event.status === 'empty' || event.status === 'skipped') {
      if (hadError.has(event.layer)) recovered.add(event.layer)
    }
    if (event.status === 'running') {
      if (map[event.layer] !== 'error' && map[event.layer] !== 'ok' && map[event.layer] !== 'degraded') {
        map[event.layer] = 'running'
      }
    } else if (event.status === 'skipped') {
      map[event.layer] = 'skipped'
    } else if (event.status === 'empty') {
      map[event.layer] = recovered.has(event.layer) ? 'degraded' : 'ok'
    } else if (event.status === 'error') {
      map[event.layer] = 'error'
    } else {
      map[event.layer] = recovered.has(event.layer) ? 'degraded' : 'ok'
    }
  }
  for (const layer of recovered) {
    if (map[layer] !== 'error') map[layer] = 'degraded'
  }
  if (status === 'running') {
    const order = LAYERS.map((l) => l.id)
    const last = [...trace].reverse().find((e) => e.status === 'running')
    if (last) map[last.layer] = 'running'
    else {
      const next = order.find((id) => !map[id])
      if (next) map[next] = 'running'
    }
  }
  return map
}

function labelize(value: string) {
  return value.replaceAll('_', ' ')
}
