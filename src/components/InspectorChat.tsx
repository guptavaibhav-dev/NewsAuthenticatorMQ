import { useEffect, useRef, useState, type ReactNode } from 'react'
import { LayerProcess } from './layerProcess'
import { SystemMessage } from './processKit'
import { enginesForLayer, LayerOutput, layerTitle } from './layerOutputs'
import type {
  ChatMessage,
  EditorialDecision,
  RunEnvelope,
  RunPhase,
  TraceEvent,
} from '../types/run'
import { DECISIONS, EDITORIAL_LAYER, LAST_LAYER } from '../types/run'

type Props = {
  messages: ChatMessage[]
  phase: RunPhase
  currentLayer: number | null
  busy: boolean
  busyLabel?: string
  pendingLayer?: number | null
  liveTrace?: TraceEvent[]
  decision: EditorialDecision | null
  notes: string
  onDecision: (value: EditorialDecision) => void
  onNotes: (value: string) => void
  onConfirmDecision: () => void
  onProceed: () => void
  onRerun: () => void
  onAsk: (question: string) => void
}

export default function InspectorChat({
  messages,
  phase,
  currentLayer,
  busy,
  busyLabel,
  pendingLayer,
  liveTrace,
  decision,
  notes,
  onDecision,
  onNotes,
  onConfirmDecision,
  onProceed,
  onRerun,
  onAsk,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const [askOpen, setAskOpen] = useState(false)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [messages, busy, askOpen, busyLabel, liveTrace])

  useEffect(() => {
    setAskOpen(false)
    setDraft('')
  }, [messages.length, currentLayer])

  const latestId = messages.at(-1)?.id
  const editorialActive =
    phase === 'awaiting_decision' && currentLayer === EDITORIAL_LAYER && !busy

  function submitAsk() {
    const question = draft.trim()
    if (!question || busy) return
    onAsk(question)
    setDraft('')
    setAskOpen(false)
  }

  return (
    <div className="chat-panel" ref={scroller}>
      {messages.length === 0 && !busy && (
        <p className="muted">Layer output will appear here after you run verification.</p>
      )}
      {messages.map((message) => {
        const active = message.id === latestId && !busy
        return (
          <article
            key={message.id}
            className={`chat-msg${message.kind === 'layer' && message.superseded ? ' superseded' : ''}${message.kind === 'error' && message.superseded ? ' superseded' : ''}`}
          >
            <MessageBody
              message={message}
              active={active}
              editorialActive={editorialActive && message.kind === 'layer' && message.layer === EDITORIAL_LAYER}
              decision={decision}
              notes={notes}
              busy={busy}
              onDecision={onDecision}
              onNotes={onNotes}
              onConfirmDecision={onConfirmDecision}
            />
            <MessageActions
              message={message}
              active={active}
              phase={phase}
              currentLayer={currentLayer}
              busy={busy}
              askOpen={askOpen && active}
              draft={draft}
              onDraft={setDraft}
              onToggleAsk={() => setAskOpen((open) => !open)}
              onSubmitAsk={submitAsk}
              onProceed={onProceed}
              onRerun={onRerun}
            />
          </article>
        )
      })}
      {busy && (
        <div className="chat-live">
          <LayerProcess
            run={null}
            layer={pendingLayer || currentLayer || 1}
            liveTrace={liveTrace}
            live
            defaultOpen
          />
          <p className="muted pulse chat-busy">{busyLabel || 'Running layer…'}</p>
        </div>
      )}
    </div>
  )
}

function MessageBody({
  message,
  active,
  editorialActive,
  decision,
  notes,
  busy,
  onDecision,
  onNotes,
  onConfirmDecision,
}: {
  message: ChatMessage
  active: boolean
  editorialActive: boolean
  decision: EditorialDecision | null
  notes: string
  busy: boolean
  onDecision: (value: EditorialDecision) => void
  onNotes: (value: string) => void
  onConfirmDecision: () => void
}) {
  if (message.kind === 'question') {
    return (
      <>
        <p className="chat-kicker">Journalist · layer {message.layer}</p>
        <p>{message.text}</p>
      </>
    )
  }
  if (message.kind === 'answer') {
    return (
      <>
        <p className="chat-kicker">Read-only answer · layer {message.layer}</p>
        <p className="chat-answer">{message.text}</p>
      </>
    )
  }

  const collapsed = Boolean(message.superseded)
  const header = (
    <header className="chat-head">
      <p className="chat-kicker">
        Layer {message.layer} · {layerTitle(message.layer)}
        {message.kind === 'layer' ? ` · ${enginesForLayer(message.envelope, message.layer)}` : ''}
        {collapsed ? ' · superseded' : ''}
      </p>
    </header>
  )

  if (message.kind === 'error') {
    const body = (
      <>
        {header}
        <SystemMessage variant="error">{message.detail}</SystemMessage>
        <p className="muted">This layer did not complete. It will not advance until it succeeds.</p>
      </>
    )
    return collapsed ? <details className="chat-fold">{wrap(body)}</details> : body
  }

  const layerBody = (
    <>
      {header}
      <LayerOutput layer={message.layer} run={message.envelope} processOpen={!collapsed} />
      {message.layer === EDITORIAL_LAYER && (
        <EditorialControls
          envelope={message.envelope}
          active={editorialActive && active}
          decision={decision}
          notes={notes}
          busy={busy}
          onDecision={onDecision}
          onNotes={onNotes}
          onConfirm={onConfirmDecision}
        />
      )}
    </>
  )
  if (!collapsed) return layerBody
  return (
    <details className="chat-fold">
      <summary>
        Layer {message.layer} · {layerTitle(message.layer)} · superseded
      </summary>
      <div className="chat-fold-body">{layerBody}</div>
    </details>
  )
}

function wrap(body: ReactNode) {
  return (
    <>
      <summary>Superseded</summary>
      <div className="chat-fold-body">{body}</div>
    </>
  )
}

function EditorialControls({
  envelope,
  active,
  decision,
  notes,
  busy,
  onDecision,
  onNotes,
  onConfirm,
}: {
  envelope: RunEnvelope
  active: boolean
  decision: EditorialDecision | null
  notes: string
  busy: boolean
  onDecision: (value: EditorialDecision) => void
  onNotes: (value: string) => void
  onConfirm: () => void
}) {
  const recorded = envelope.human_decision.decision
  const locked = !active || Boolean(recorded)
  return (
    <div className="chat-decision">
      <p className="muted">
        Choose the newsroom outcome. The recommendation above is not auto-committed.
      </p>
      <div className="decision-grid">
        {DECISIONS.map((option) => {
          const selected = (active ? decision : recorded) === option
          return (
            <button
              key={option}
              type="button"
              className={selected ? 'primary' : 'ghost'}
              disabled={locked || busy}
              onClick={() => onDecision(option)}
            >
              {option.replaceAll('_', ' ')}
            </button>
          )
        })}
      </div>
      <label className="field-label" htmlFor="chat-decision-notes">
        Editorial notes
      </label>
      <textarea
        id="chat-decision-notes"
        className="content-input"
        rows={3}
        value={active ? notes : envelope.human_decision.notes}
        disabled={locked || busy}
        onChange={(e) => onNotes(e.target.value)}
      />
      {active && (
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={!decision || busy}
            onClick={onConfirm}
          >
            Confirm editorial decision
          </button>
        </div>
      )}
    </div>
  )
}

function MessageActions({
  message,
  active,
  phase,
  currentLayer,
  busy,
  askOpen,
  draft,
  onDraft,
  onToggleAsk,
  onSubmitAsk,
  onProceed,
  onRerun,
}: {
  message: ChatMessage
  active: boolean
  phase: RunPhase
  currentLayer: number | null
  busy: boolean
  askOpen: boolean
  draft: string
  onDraft: (value: string) => void
  onToggleAsk: () => void
  onSubmitAsk: () => void
  onProceed: () => void
  onRerun: () => void
}) {
  if (message.kind === 'question') return null
  const layer = message.layer
  if (layer === EDITORIAL_LAYER && message.kind === 'layer') return null

  const failed = message.kind === 'error' || (active && phase === 'error')
  const complete = active && phase === 'complete' && currentLayer === LAST_LAYER
  const disabled = !active || busy

  return (
    <div className="chat-actions-wrap">
      <div className="chat-actions">
        {complete ? (
          <p className="muted chat-complete">Pipeline complete. Decision support only.</p>
        ) : failed ? null : (
          <button type="button" className="primary" disabled={disabled} onClick={onProceed}>
            Ready to proceed?
          </button>
        )}
        <button type="button" className="ghost" disabled={disabled} onClick={onRerun}>
          Generate response again
        </button>
        <button type="button" className="ghost" disabled={disabled} onClick={onToggleAsk}>
          Questions or comments?
        </button>
      </div>
      {askOpen && active && (
        <div className="chat-ask">
          <label className="field-label" htmlFor="chat-ask-input">
            Question about this layer
          </label>
          <textarea
            id="chat-ask-input"
            className="content-input"
            rows={3}
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            placeholder="Ask about this layer’s output. The answer cannot change the run."
          />
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={busy || !draft.trim()}
              onClick={onSubmitAsk}
            >
              Submit question
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
