import type { ReactNode } from 'react'
import { LAYERS } from '../types/run'

export type DeskStatus = 'done' | 'running' | 'flagged' | 'review' | 'pending'

export function toDeskStatus(state: string, review = false): DeskStatus {
  if (review) return 'review'
  if (state === 'running') return 'running'
  if (state === 'ok') return 'done'
  if (state === 'error' || state === 'degraded') return 'flagged'
  return 'pending'
}

export function deskStatusLabel(status: DeskStatus) {
  if (status === 'done') return 'Complete'
  if (status === 'running') return 'Running'
  if (status === 'flagged') return 'Needs a look'
  if (status === 'review') return 'Your turn'
  return 'Waiting'
}

export function LayerRail({
  layers,
  current,
  onSelect,
}: {
  layers: { n: number; name: string; status: DeskStatus }[]
  current?: number | null
  onSelect?: (n: number) => void
}) {
  return (
    <nav className="desk-rail" aria-label="Framework layers">
      <div className="desk-rail-head">
        <span className="desk-label">Layers</span>
        <span className="desk-label">{layers.filter((row) => row.status === 'done').length}/{layers.length}</span>
      </div>
      <ol>
        {layers.map((row) => {
          const currentStep = current === row.n
          return (
            <li key={row.n}>
              <button
                type="button"
                className={`desk-rail-item${row.status === 'pending' ? ' is-pending' : ''}`}
                aria-current={currentStep ? 'step' : undefined}
                onClick={() => onSelect?.(row.n)}
              >
                <span className="desk-rail-code">L{row.n}</span>
                <span className="desk-rail-name">{row.name}</span>
                <span className="desk-rail-state" title={deskStatusLabel(row.status)}>
                  <i className={`desk-dot desk-dot-${row.status}`} />
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

export function LayerChrome({
  layer,
  name,
  status = 'done',
  meta,
  children,
  actions,
  running = false,
  id,
}: {
  layer: number
  name?: string
  status?: DeskStatus
  meta?: string
  children?: ReactNode
  actions?: ReactNode
  running?: boolean
  id?: string
}) {
  const title = name ?? LAYERS.find((row) => row.n === layer)?.label ?? `Layer ${layer}`
  return (
    <div
      className={`desk-msg${status === 'flagged' ? ' is-flagged' : ''}${status === 'review' ? ' is-review' : ''}`}
      id={id}
    >
      <div className="desk-avatar" aria-hidden>
        L{layer}
      </div>
      <div className="desk-bubble">
        <header className="desk-msg-head">
          <span className="desk-msg-name">{title}</span>
          <span className="desk-label">{deskStatusLabel(status)}</span>
          {meta && <span className="desk-msg-meta desk-muted">{meta}</span>}
        </header>
        {running ? (
          <div className="desk-skel" aria-hidden>
            <i style={{ width: '92%' }} />
            <i style={{ width: '74%' }} />
            <i style={{ width: '58%' }} />
          </div>
        ) : (
          children
        )}
        {actions && <div className="desk-actions">{actions}</div>}
      </div>
    </div>
  )
}

export function UserBubble({
  children,
  time,
  kicker = 'You',
}: {
  children: ReactNode
  time?: string
  kicker?: string
}) {
  return (
    <div className="desk-you">
      <div className="desk-you-inner">
        <p className="desk-label">
          {kicker}
          {time ? ` · ${time}` : ''}
        </p>
        <div className="desk-you-bubble">{children}</div>
      </div>
    </div>
  )
}

export function ComposerDock({
  value,
  onChange,
  onSend,
  disabled,
  suggestions,
}: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled?: boolean
  suggestions?: string[]
}) {
  return (
    <div className="desk-composer">
      {suggestions && suggestions.length > 0 && (
        <div className="desk-sugs">
          {suggestions.map((chip) => (
            <button
              key={chip}
              type="button"
              className="desk-chip"
              disabled={disabled}
              onClick={() => onChange(chip)}
            >
              {chip}
            </button>
          ))}
        </div>
      )}
      <div className="desk-composer-row">
        <label className="visually-hidden" htmlFor="desk-composer-input">
          Question about this layer
        </label>
        <textarea
          id="desk-composer-input"
          rows={2}
          value={value}
          disabled={disabled}
          placeholder="Ask about this layer. The answer cannot change the run."
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (!disabled && value.trim()) onSend()
            }
          }}
        />
        <button
          type="button"
          className="primary"
          disabled={disabled || !value.trim()}
          onClick={onSend}
        >
          Send
        </button>
      </div>
    </div>
  )
}

export function scrollToLayerCard(layer: number) {
  const node = document.getElementById(`layer-card-${layer}`)
  node?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
