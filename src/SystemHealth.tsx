import type { Health, HealthStatus } from './types/run'

type Props = {
  health: Health | null
  loading: boolean
  error: string | null
  onRefresh: () => void
}

export default function SystemHealth({ health, loading, error, onRefresh }: Props) {
  return (
    <section className="system-health" aria-labelledby="system-heading">
      <div className="system-head">
        <div>
          <h1 id="system-heading">System health</h1>
          <p className="lede">
            Live status of API keys, verification services, engines, modules, and
            the seven framework layers. Keys are never displayed.
          </p>
        </div>
        <button type="button" className="primary" onClick={onRefresh} disabled={loading}>
          {loading ? 'Checking…' : 'Check keys and layers'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !health && <p className="muted pulse">Probing providers…</p>}

      {health?.summary && (
        <dl className="result-grid">
          <div>
            <dt>Keys working</dt>
            <dd>
              {health.summary.keys_working}/{health.summary.keys_total}
            </dd>
          </div>
          <div>
            <dt>Keys configured</dt>
            <dd>
              {health.summary.keys_configured}/{health.summary.keys_total}
            </dd>
          </div>
          <div>
            <dt>Layers ready</dt>
            <dd>
              {health.summary.layers_ready}/{health.summary.layers_total}
            </dd>
          </div>
          <div>
            <dt>Last check</dt>
            <dd>{formatTime(health.checked_at)}</dd>
          </div>
        </dl>
      )}

      <h2>Seven layers</h2>
      <ol className="layer-health">
        {(health?.layers ?? []).map((layer) => (
          <li key={layer.id} className={statusClass(layer.status)}>
            <span className="layer-order">{layer.order}</span>
            <div>
              <p className="item-title">{layer.label}</p>
              <p className="item-detail">{layer.detail}</p>
              {layer.depends_on.length > 0 && (
                <p className="item-meta">Depends on: {layer.depends_on.join(', ')}</p>
              )}
            </div>
            <StatusBadge status={layer.status} />
          </li>
        ))}
      </ol>

      <h2>API keys</h2>
      <div className="table-wrap">
        <table className="status-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Env variable</th>
              <th>Status</th>
              <th>Used by</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {(health?.keys ?? []).map((row) => (
              <tr key={row.id}>
                <td>{row.label}</td>
                <td>
                  <code>{row.env}</code>
                </td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
                <td className="muted">{row.used_by.join('; ')}</td>
                <td className="muted">{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Engines</h2>
      <ul className="card-grid">
        {(health?.engines ?? []).map((engine) => (
          <li key={engine.id} className={statusClass(engine.status)}>
            <StatusBadge status={engine.status} />
            <p className="item-title">{engine.role}</p>
            <p className="item-meta">{engine.model}</p>
            <p className="item-detail">{engine.detail}</p>
          </li>
        ))}
      </ul>

      <h2>Services</h2>
      <ul className="card-grid">
        {(health?.services ?? []).map((service) => (
          <li key={service.id} className={statusClass(service.status)}>
            <StatusBadge status={service.status} />
            <p className="item-title">{service.label}</p>
            <p className="item-meta">{service.kind}</p>
            <p className="item-detail">{service.detail}</p>
          </li>
        ))}
      </ul>

      <h2>Modules</h2>
      <div className="table-wrap">
        <table className="status-table">
          <thead>
            <tr>
              <th>Module</th>
              <th>Layer</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {(health?.modules ?? []).map((mod) => (
              <tr key={mod.id}>
                <td>{mod.label}</td>
                <td>{mod.layer}</td>
                <td>
                  <StatusBadge status={mod.status} />
                </td>
                <td className="muted">{mod.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function StatusBadge({ status }: { status: HealthStatus }) {
  return <span className={`badge ${statusClass(status)}`}>{labelize(status)}</span>
}

function statusClass(status: string) {
  if (status === 'working' || status === 'ready') return 'is-good'
  if (status === 'configured' || status === 'degraded' || status === 'fallback') return 'is-warn'
  if (status === 'error' || status === 'unavailable' || status === 'missing') return 'is-bad'
  return 'is-idle'
}

function labelize(value: string) {
  return value.replaceAll('_', ' ')
}

function formatTime(value?: string) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}
