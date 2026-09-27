import { useEffect, useRef, useState, type ReactNode } from 'react'
import { LayerProcess } from './layerProcess'
import { SystemMessage } from './processKit'
import { enginesForLayer, LayerOutput, layerTitle } from './layerOutputs'
import { ComposerDock, LayerChrome, UserBubble, type DeskStatus } from './desk'
import { MarkdownText } from '../lib/markdown'
import type {
  ChatMessage,
  EditorialDecision,
  RunPhase,
  TraceEvent,
} from '../types/run'
import { EDITORIAL_LAYER, LAST_LAYER } from '../types/run'

const ASK_SUGGESTIONS = [
  'What could we not check?',
  'Which claims need a closer look?',
  'Explain this in one sentence',
]

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
  layerStatus?: (layer: number) => DeskStatus
  footer?: ReactNode
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
  layerStatus,
  footer,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [messages, busy, busyLabel, liveTrace])

  useEffect(() => {
    setDraft('')
  }, [messages.length, currentLayer])

  const currentCard = [...messages]
    .reverse()
    .find(
      (row) =>
        (row.kind === 'layer' || row.kind === 'error') &&
        !row.superseded &&
        (currentLayer == null || row.layer === currentLayer),
    )
  const lastMessage = messages.at(-1)
  const followUpAfterLayer =
    Boolean(currentCard) &&
    lastMessage != null &&
    lastMessage.id !== currentCard?.id &&
    (lastMessage.kind === 'question' || lastMessage.kind === 'answer')
  const editorialActive =
    phase === 'awaiting_decision' && currentLayer === EDITORIAL_LAYER && !busy
  const canAsk = Boolean(currentLayer) && !busy && phase !== 'idle'

  function submitAsk() {
    const question = draft.trim()
    if (!question || busy) return
    onAsk(question)
    setDraft('')
  }

  function focusComposer() {
    document.getElementById('desk-composer-input')?.focus()
  }

  return (
    <div className="chat-shell">
      <div className="chat-panel" ref={scroller}>
        <div className="chat-scroll">
          {messages.length === 0 && !busy && (
            <p className="muted">Layer output will appear here after you run verification.</p>
          )}
          {messages.map((message) => {
            const active = currentCard?.id === message.id && !busy
            const latestForLayer = [...messages]
              .reverse()
              .find((row) => row.kind === 'layer' && row.layer === message.layer)
            const cardId =
              message.kind === 'layer' && latestForLayer?.id === message.id
                ? `layer-card-${message.layer}`
                : undefined
            const superseded =
              (message.kind === 'layer' || message.kind === 'error') && message.superseded
            return (
              <article
                key={message.id}
                id={cardId}
                className={`chat-msg${superseded ? ' superseded' : ''}`}
              >
                <MessageBody
                  message={message}
                  active={active}
                  editorialActive={
                    editorialActive && message.kind === 'layer' && message.layer === EDITORIAL_LAYER
                  }
                  decision={decision}
                  notes={notes}
                  busy={busy}
                  status={layerStatus?.(message.layer) ?? (superseded ? 'pending' : 'done')}
                  phase={phase}
                  currentLayer={currentLayer}
                  onDecision={onDecision}
                  onNotes={onNotes}
                  onConfirmDecision={onConfirmDecision}
                  onProceed={onProceed}
                  onRerun={onRerun}
                  onAsk={focusComposer}
                />
              </article>
            )
          })}
          {busy && (
            <div className="chat-live">
              <LayerChrome
                layer={pendingLayer || currentLayer || 1}
                name={layerTitle(pendingLayer || currentLayer || 1)}
                status="running"
                running
              />
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
      </div>
      {followUpAfterLayer && currentCard && (
        <div className="desk-proceed-bar">
          <LayerActions
            message={currentCard}
            active={!busy}
            phase={phase}
            currentLayer={currentLayer}
            busy={busy}
            onProceed={onProceed}
            onRerun={onRerun}
            onAsk={focusComposer}
          />
        </div>
      )}
      {footer}
      <ComposerDock
        value={draft}
        onChange={setDraft}
        onSend={submitAsk}
        disabled={!canAsk}
        suggestions={ASK_SUGGESTIONS}
      />
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
  status,
  phase,
  currentLayer,
  onDecision,
  onNotes,
  onConfirmDecision,
  onProceed,
  onRerun,
  onAsk,
}: {
  message: ChatMessage
  active: boolean
  editorialActive: boolean
  decision: EditorialDecision | null
  notes: string
  busy: boolean
  status: DeskStatus
  phase: RunPhase
  currentLayer: number | null
  onDecision: (value: EditorialDecision) => void
  onNotes: (value: string) => void
  onConfirmDecision: () => void
  onProceed: () => void
  onRerun: () => void
  onAsk: () => void
}) {
  if (message.kind === 'question') {
    return <UserBubble>{message.text}</UserBubble>
  }
  if (message.kind === 'answer') {
    return (
      <LayerChrome layer={message.layer} name="Read-only answer" status="done" meta={`Layer ${message.layer}`}>
        <MarkdownText text={message.text} />
      </LayerChrome>
    )
  }

  const collapsed = Boolean(message.superseded)
  const meta = message.kind === 'layer' ? enginesForLayer(message.envelope, message.layer) : undefined
  const chromeStatus: DeskStatus = collapsed ? 'pending' : status
  const actions = (
    <LayerActions
      message={message}
      active={active}
      phase={phase}
      currentLayer={currentLayer}
      busy={busy}
      onProceed={onProceed}
      onRerun={onRerun}
      onAsk={onAsk}
    />
  )

  if (message.kind === 'error') {
    const body = (
      <LayerChrome
        layer={message.layer}
        name={layerTitle(message.layer)}
        status="flagged"
        meta="Did not complete"
        actions={collapsed ? undefined : actions}
      >
        <SystemMessage variant="error">{message.detail}</SystemMessage>
        <p className="muted">This layer did not complete. It will not advance until it succeeds.</p>
      </LayerChrome>
    )
    return collapsed ? <details className="chat-fold">{wrap(body)}</details> : body
  }

  const layerBody = (
    <LayerChrome
      layer={message.layer}
      name={layerTitle(message.layer)}
      status={chromeStatus}
      meta={meta}
      actions={collapsed ? undefined : actions}
    >
      <LayerOutput
        layer={message.layer}
        run={message.envelope}
        editorial={
          message.layer === EDITORIAL_LAYER
            ? {
                active: editorialActive && active,
                decision,
                notes,
                busy,
                onDecision,
                onNotes,
                onConfirm: onConfirmDecision,
              }
            : undefined
        }
      />
    </LayerChrome>
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

function LayerActions({
  message,
  active,
  phase,
  currentLayer,
  busy,
  onProceed,
  onRerun,
  onAsk,
}: {
  message: ChatMessage
  active: boolean
  phase: RunPhase
  currentLayer: number | null
  busy: boolean
  onProceed: () => void
  onRerun: () => void
  onAsk: () => void
}) {
  if (message.kind === 'question' || message.kind === 'answer') return null
  if (message.layer === EDITORIAL_LAYER && message.kind === 'layer') return null

  const failed = message.kind === 'error' || (active && phase === 'error')
  const complete = active && phase === 'complete' && currentLayer === LAST_LAYER
  const disabled = !active || busy

  if (complete) {
    return <p className="muted chat-complete">Pipeline complete. Decision support only.</p>
  }

  return (
    <>
      {failed ? null : (
        <button type="button" className="primary" disabled={disabled} onClick={onProceed}>
          Proceed
        </button>
      )}
      <button type="button" className="ghost" disabled={disabled} onClick={onRerun}>
        Generate again
      </button>
      <button type="button" className="ghost" disabled={disabled} onClick={onAsk}>
        Ask a question
      </button>
    </>
  )
}
