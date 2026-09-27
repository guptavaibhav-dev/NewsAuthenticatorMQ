import type { RunSummary } from '../types/run'

type Props = {
  runs: RunSummary[]
  loading: boolean
  error: string | null
  selectedId: string | null
  busy: boolean
  onRefresh: () => void
  onOpen: (runId: string) => void
}

function phaseCopy(phase: string, layer: number) {
  if (phase === 'complete') return 'Complete'
  if (phase === 'error') return 'Stopped'
  if (phase === 'awaiting_decision') return `Waiting at layer ${layer || '?'}`
  if (phase === 'running_layer') return `Running layer ${layer || '?'}`
  return layer ? `Layer ${layer}` : phase || 'Saved'
}

function formatWhen(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

export default function SessionHistory({
  runs,
  loading,
  error,
  selectedId,
  busy,
  onRefresh,
  onOpen,
}: Props) {
  return (
    <section className="session-history" aria-labelledby="history-heading">
      <div className="system-head">
        <div>
          <h1 id="history-heading">History</h1>
          <p className="lede">Past authentications on this machine. Open one to load it on the right.</p>
        </div>
        <button type="button" className="primary" onClick={onRefresh} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && runs.length === 0 && <p className="muted pulse">Loading saved sessions…</p>}
      {!loading && runs.length === 0 && !error && (
        <p className="muted">No saved sessions yet.</p>
      )}

      {runs.length > 0 && (
        <ul className="session-list">
          {runs.map((row) => (
            <li key={row.run_id}>
              <button
                type="button"
                className={`session-item${selectedId === row.run_id ? ' on' : ''}`}
                disabled={busy}
                onClick={() => onOpen(row.run_id)}
              >
                <span className="session-title">{row.title}</span>
                <span className="session-meta">
                  {phaseCopy(row.phase, row.completed_layer)}
                  {row.url ? ` · ${row.url}` : ''}
                </span>
                <span className="session-when">{formatWhen(row.updated_at || row.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
