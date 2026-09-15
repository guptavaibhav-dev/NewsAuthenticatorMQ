import { useEffect, useMemo, useRef, useState } from 'react'
import InspectorChat from './components/InspectorChat'
import { ApiError, fetchHealth, fetchRun, startRun, stepRun, submitDecision, askRun, subscribeRun } from './lib/api'
import SystemHealth from './SystemHealth'
import type {
  ChatMessage,
  EditorialDecision,
  Health,
  RunEnvelope,
  RunPhase,
  TraceEvent,
} from './types/run'
import { corroborationStateCopy } from './components/layerOutputs'
import { LAST_LAYER, LAYERS } from './types/run'

const SHOW_PROCESS_LOG = false

type Status = 'idle' | 'running' | 'done' | 'error'
type Tab = 'authenticate' | 'system'

export default function App() {
  const [tab, setTab] = useState<Tab>('authenticate')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [trace, setTrace] = useState<TraceEvent[]>([])
  const [run, setRun] = useState<RunEnvelope | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthLoading, setHealthLoading] = useState(false)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [decision, setDecision] = useState<EditorialDecision | null>(null)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingLayer, setPendingLayer] = useState<number | null>(null)
  const [recordOpen, setRecordOpen] = useState(false)
  const busyLock = useRef(false)

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
  const runInProgress =
    Boolean(run) && (run?.phase === 'running_layer' || run?.phase === 'awaiting_decision' || busy)
  const phase: RunPhase = run?.phase ?? 'idle'
  const recordReady =
    run?.phase === 'complete' && run.completed_layer >= LAST_LAYER && !busy

  useEffect(() => {
    if (!busy || !run?.run_id) return
    let cancelled = false
    const timer = window.setInterval(() => {
      void fetchRun(run.run_id)
        .then((envelope) => {
          if (!cancelled) setTrace(envelope.trace)
        })
        .catch((err) => {
          if (cancelled) return
          if (err instanceof ApiError && err.status === 404) {
            cancelled = true
            busyLock.current = false
            setBusy(false)
            setPendingLayer(null)
            setError(err.message)
            setStatus('error')
          }
        })
    }, 800)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [busy, run?.run_id])

  useEffect(() => {
    if (!recordOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setRecordOpen(false)
    }
    window.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [recordOpen])

  function applyEnvelope(envelope: RunEnvelope) {
    setRun(envelope)
    setTrace(envelope.trace)
    setError(envelope.phase === 'error' ? envelope.error : null)
    if (envelope.phase === 'complete') setStatus('done')
    else if (envelope.phase === 'error') setStatus('error')
    else setStatus('running')
  }

  function appendLayerResult(envelope: RunEnvelope, layer: number, supersede: boolean) {
    applyEnvelope(envelope)
    setMessages((prev) => {
      const next = supersede ? markSuperseded(prev, layer) : prev
      if (envelope.phase === 'error') {
        return [
          ...next,
          {
            id: newId(),
            kind: 'error',
            layer,
            detail: envelope.error || 'Layer failed',
          },
        ]
      }
      return [
        ...next,
        {
          id: newId(),
          kind: 'layer',
          layer,
          envelope: cloneRun(envelope),
        },
      ]
    })
  }

  async function handleRun() {
    if (!canRun || busyLock.current || runInProgress) return
    busyLock.current = true
    setBusy(true)
    setPendingLayer(1)
    setTrace([])
    setRun(null)
    setMessages([])
    setError(null)
    setDecision(null)
    setNotes('')
    setRecordOpen(false)
    setStatus('running')
    try {
      const result = await startRun(text, url)
      appendLayerResult(result.envelope, result.layer, false)
      if (SHOW_PROCESS_LOG) {
        subscribeRun(result.run_id, (event) => setTrace((prev) => [...prev, event]), () => {})
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start run')
      setStatus('error')
    } finally {
      busyLock.current = false
      setBusy(false)
      setPendingLayer(null)
    }
  }

  async function handleProceed() {
    if (!run || busyLock.current) return
    busyLock.current = true
    setBusy(true)
    setPendingLayer((run.current_layer || 0) + 1)
    try {
      const result = await stepRun(run.run_id, 'proceed')
      appendLayerResult(result.envelope, result.layer, false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not advance')
    } finally {
      busyLock.current = false
      setBusy(false)
      setPendingLayer(null)
    }
  }

  async function handleRerun() {
    if (!run || busyLock.current || run.current_layer == null) return
    busyLock.current = true
    setBusy(true)
    setPendingLayer(run.current_layer)
    try {
      const result = await stepRun(run.run_id, 'rerun')
      appendLayerResult(result.envelope, result.layer, true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not re-run layer')
    } finally {
      busyLock.current = false
      setBusy(false)
      setPendingLayer(null)
    }
  }

  async function handleAsk(question: string) {
    if (!run || run.current_layer == null || busyLock.current) return
    const layer = run.current_layer
    busyLock.current = true
    setBusy(true)
    setMessages((prev) => [
      ...prev,
      { id: newId(), kind: 'question', layer, text: question },
    ])
    try {
      const answer = await askRun(run.run_id, layer, question)
      setMessages((prev) => [...prev, { id: newId(), kind: 'answer', layer, text: answer }])
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Could not answer'
      setMessages((prev) => [...prev, { id: newId(), kind: 'answer', layer, text: detail }])
    } finally {
      busyLock.current = false
      setBusy(false)
    }
  }

  async function handleDecision() {
    if (!run || !decision || busyLock.current) return
    busyLock.current = true
    setBusy(true)
    setPendingLayer(7)
    try {
      const result = await submitDecision(run.run_id, decision, notes)
      applyEnvelope(result.envelope)
      setMessages((prev) => {
        const patched = prev.map((message) =>
          message.kind === 'layer' && message.layer === 6 && !message.superseded
            ? { ...message, envelope: cloneRun(result.envelope) }
            : message,
        )
        if (result.envelope.phase === 'error') {
          return [
            ...patched,
            {
              id: newId(),
              kind: 'error',
              layer: result.layer,
              detail: result.envelope.error || 'Documentation layer failed',
            },
          ]
        }
        return [
          ...patched,
          {
            id: newId(),
            kind: 'layer',
            layer: result.layer,
            envelope: cloneRun(result.envelope),
          },
        ]
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save editorial decision')
    } finally {
      busyLock.current = false
      setBusy(false)
      setPendingLayer(null)
    }
  }

  function handleClear() {
    if (busyLock.current) return
    setText('')
    setUrl('')
    setTrace([])
    setRun(null)
    setMessages([])
    setError(null)
    setStatus('idle')
    setDecision(null)
    setNotes('')
    setPendingLayer(null)
    setRecordOpen(false)
  }

  const layerState = useMemo(
    () => layerStatuses(run, trace, status, pendingLayer),
    [run, trace, status, pendingLayer],
  )

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
                  disabled={!canRun || busy || runInProgress}
                >
                  {busy && !run ? 'Starting…' : 'Run verification'}
                </button>
                <button type="button" className="ghost" onClick={handleClear} disabled={busy}>
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
                  No run yet. Submit text or a URL. Each layer will pause for your
                  decision before the next one runs.
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

              {busy && (
                <p className="muted pulse">
                  {pendingLayer
                    ? `Running layer ${pendingLayer}…`
                    : 'Examining content through the current layer…'}
                </p>
              )}
              {error && <p className="error">{error}</p>}

              {(status !== 'idle' || messages.length > 0) && (
                <InspectorChat
                  messages={messages}
                  phase={phase}
                  currentLayer={run?.current_layer ?? null}
                  busy={busy}
                  busyLabel={
                    pendingLayer ? `Running layer ${pendingLayer}…` : 'Working…'
                  }
                  pendingLayer={pendingLayer}
                  liveTrace={trace}
                  decision={decision}
                  notes={notes}
                  onDecision={setDecision}
                  onNotes={setNotes}
                  onConfirmDecision={() => void handleDecision()}
                  onProceed={() => void handleProceed()}
                  onRerun={() => void handleRerun()}
                  onAsk={(question) => void handleAsk(question)}
                />
              )}

              {SHOW_PROCESS_LOG && trace.length > 0 && (
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

              {recordReady && (
                <div className="record-launch">
                  <button
                    type="button"
                    className="primary"
                    onClick={() => setRecordOpen(true)}
                  >
                    View verification summary
                  </button>
                  <p className="muted">
                    Full claims, evidence, uncertainty, and the verification record.
                  </p>
                </div>
              )}
            </section>
            {recordOpen && run && (
              <div
                className="modal-backdrop"
                onClick={() => setRecordOpen(false)}
                role="presentation"
              >
                <div
                  className="modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="record-modal-heading"
                  onClick={(event) => event.stopPropagation()}
                >
                  <header className="modal-head">
                    <h2 id="record-modal-heading">Verification summary</h2>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setRecordOpen(false)}
                    >
                      Close
                    </button>
                  </header>
                  <p className="caveat modal-caveat">
                    Decision support only. Outputs are signals, not a true/false verdict.
                  </p>
                  <div className="modal-body">
                    <RunResults run={run} completedLayer={run.completed_layer} />
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>

      <footer className="footer">
        <p>Thesis prototype · COMP4092 · Macquarie University</p>
      </footer>
    </div>
  )
}

function RunResults({
  run,
  completedLayer,
}: {
  run: RunEnvelope
  completedLayer: number
}) {
  const outlets = evidenceColumns(run)
  const showInput = completedLayer >= 1
  const showClaims = completedLayer >= 2
  const showEvidence = completedLayer >= 3
  const showMatrix = completedLayer >= 4
  const showUncertainty = completedLayer >= 5
  const showRecord = completedLayer >= 7

  return (
    <div className="results-stack">
      <dl className="result-grid">
        {showEvidence && (
          <div>
            <dt>Existence</dt>
            <dd>
              {run.retrieval
                ? existenceSummary(run.retrieval.existence_class)
                : 'Layer 3 has not run'}
            </dd>
          </div>
        )}
        {showMatrix && (
          <div>
            <dt>Corroboration</dt>
            <dd>
              {corroborationStateCopy(run.corroboration.overall_state, {
                existenceClass:
                  run.corroboration.existence_class ?? run.retrieval?.existence_class,
                unscoredReason: run.corroboration.unscored_reason,
                pairsScored: run.corroboration.pairs_scored,
              })}
            </dd>
          </div>
        )}
        {showMatrix && (
          <div>
            <dt>Independent sources</dt>
            <dd>
              {run.retrieval?.independent_source_count ??
                run.corroboration.independent_source_count}
              {(run.corroboration.group_join_misses ?? 0) > 0
                ? ` (upper bound; ${run.corroboration.group_join_misses} join miss${
                    run.corroboration.group_join_misses === 1 ? '' : 'es'
                  })`
                : ''}
            </dd>
          </div>
        )}
        {showUncertainty && (
          <div>
            <dt>Publication risk</dt>
            <dd>{run.uncertainty.publication_risk}</dd>
          </div>
        )}
      </dl>

      {Object.keys(run.engines_used).length > 0 && (
        <p className="engines">
          Engines:{' '}
          {Object.entries(run.engines_used)
            .map(([layer, model]) => `${layer}: ${model}`)
            .join(' · ')}
        </p>
      )}

      {showClaims && run.classification.headline && (
        <p>
          <strong>Headline.</strong> {run.classification.headline}
        </p>
      )}
      {showInput && run.input.url && (
        <p className="muted">
          URL fetch: {run.input.fetch_status}
          {run.input.fetch_error ? ` — ${run.input.fetch_error}` : ''}
          {run.input.publisher_domain ? ` · ${run.input.publisher_domain}` : ''}
        </p>
      )}

      {showClaims && (
        <>
          <h3>Claims</h3>
          <ul className="plain-list">
            {run.classification.claims.map((claim) => {
              const ungrounded = (claim.grounding ?? 'not_found') === 'not_found'
              return (
                <li key={claim.id} className={ungrounded ? 'claim-unverified' : undefined}>
                  <code>{claim.id}</code> {claim.text}{' '}
                  <span className="muted">({claim.kind})</span>
                  {claim.agreement && claim.agreement !== 'both' && (
                    <>
                      {' '}
                      <span className="claim-flag">
                        {claim.agreement === 'pass_a_only' ? 'pass A only' : 'pass B only'} —
                        one extraction pass, lower confidence
                      </span>
                    </>
                  )}
                  {ungrounded ? (
                    <>
                      {' '}
                      <strong className="claim-flag">
                        unverified — quote not found in article
                      </strong>
                    </>
                  ) : (
                    <p className="claim-quote">“{claim.source_quote}”</p>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}

      {showClaims && run.classification.disagreements.length > 0 && (
        <>
          <h3>NER / LLM disagreements</h3>
          <ul className="plain-list">
            {run.classification.disagreements.map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
        </>
      )}

      {showMatrix && outlets.length > 0 && run.classification.claims.length > 0 && (
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

      {showEvidence && (
        <>
          <h3>Retrieved evidence</h3>
          {run.retrieval != null ? (
            run.retrieval.documents.length === 0 ? (
              <p className="muted">{existenceSummary(run.retrieval.existence_class)}</p>
            ) : (
              <ul className="plain-list">
                {run.retrieval.independent_sources.map((source) => (
                  <li key={source.source_id}>
                    <a href={source.representative_url} target="_blank" rel="noreferrer">
                      {source.publisher_ids.join(', ') || source.representative_url}
                    </a>{' '}
                    <span className="muted">
                      {source.merge_reason === 'none'
                        ? 'stands alone'
                        : source.merge_reason.replaceAll('_', ' ')}
                    </span>
                    <p className="claim-note">{source.merge_evidence}</p>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <p className="muted">Layer 3 has not run.</p>
          )}
        </>
      )}

      {showEvidence && (run.retrieval?.factchecks.length ?? 0) > 0 && (
        <>
          <h3>Prior fact-checks</h3>
          <ul className="plain-list">
            {run.retrieval!.factchecks.map((record) => (
              <li key={record.review_url}>
                {record.reviewer_name} rated this “{record.rating_text}” — their rating,
                not NewsAuth’s. {record.reviewed_claim_text}{' '}
                {record.review_url && (
                  <a href={record.review_url} target="_blank" rel="noreferrer">
                    source
                  </a>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {showEvidence && (run.retrieval?.entity_grounding.length ?? 0) > 0 && (
        <>
          <h3>Entity grounding</h3>
          <ul className="plain-list">
            {run.retrieval!.entity_grounding.map((row) => (
              <li key={row.entity_text}>
                {row.entity_text}:{' '}
                {row.entity_is_well_known
                  ? row.matched_title || 'found'
                  : 'no page — a gap in reference coverage, not evidence of invention'}
              </li>
            ))}
          </ul>
        </>
      )}

      {showUncertainty && (
        <>
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
        </>
      )}

      {showRecord && (
        <>
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
        </>
      )}
    </div>
  )
}

function layerStatuses(
  run: RunEnvelope | null,
  trace: TraceEvent[],
  status: Status,
  pendingLayer: number | null,
): Record<string, string> {
  const fromTrace = traceChipMap(trace, status)
  const map: Record<string, string> = {}
  for (const layer of LAYERS) {
    const n = layer.n
    if (pendingLayer === n) {
      map[layer.id] = 'running'
      continue
    }
    if (!run) {
      map[layer.id] = n === 1 && status === 'running' ? 'running' : 'idle'
      continue
    }
    if (n <= run.completed_layer) {
      map[layer.id] = fromTrace[layer.id] || 'ok'
      continue
    }
    if (n === run.current_layer) {
      if (run.phase === 'error') map[layer.id] = 'error'
      else if (run.phase === 'running_layer' || run.phase === 'awaiting_decision') {
        map[layer.id] = n === 6 ? 'running' : fromTrace[layer.id] || 'running'
      } else map[layer.id] = fromTrace[layer.id] || 'idle'
      continue
    }
    map[layer.id] = 'idle'
  }
  return map
}

function traceChipMap(trace: TraceEvent[], status: Status): Record<string, string> {
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
    const last = [...trace].reverse().find((e) => e.status === 'running')
    if (last) map[last.layer] = 'running'
  }
  return map
}

function markSuperseded(messages: ChatMessage[], layer: number): ChatMessage[] {
  let found = false
  const reversed = [...messages].reverse().map((message) => {
    if (
      !found &&
      (message.kind === 'layer' || message.kind === 'error') &&
      message.layer === layer &&
      !message.superseded
    ) {
      found = true
      return { ...message, superseded: true }
    }
    return message
  })
  return reversed.reverse()
}

function cloneRun(run: RunEnvelope): RunEnvelope {
  return structuredClone(run)
}

function newId() {
  return crypto.randomUUID()
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

function existenceSummary(klass: string) {
  if (klass === 'not_found') return 'No coverage found — this is an open question.'
  if (klass === 'out_of_range') {
    return 'Never looked — no configured adapter could search this article.'
  }
  return labelize(klass)
}
