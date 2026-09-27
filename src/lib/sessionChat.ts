import type { ChatMessage, RunEnvelope, RunSession } from '../types/run'

function snapshotFor(session: RunSession, layer: number): RunEnvelope | null {
  const raw = session.snapshots[String(layer)] ?? session.snapshots[layer as unknown as string]
  return raw ?? null
}

function envelopeForLayer(session: RunSession, layer: number): RunEnvelope {
  const current = session.envelope
  if (layer === current.completed_layer || layer === current.current_layer) {
    return current
  }
  const nextSnap = snapshotFor(session, layer + 1)
  if (nextSnap) return nextSnap
  return current
}

export function reconstructChat(session: RunSession): ChatMessage[] {
  const current = session.envelope
  const maxLayer = Math.max(current.completed_layer, current.current_layer ?? 0)
  const byLayer = new Map<number, ChatMessage[]>()
  for (const row of session.messages) {
    const item: ChatMessage =
      row.kind === 'error'
        ? { id: row.id, kind: 'error', layer: row.layer, detail: row.text }
        : { id: row.id, kind: row.kind, layer: row.layer, text: row.text }
    const list = byLayer.get(row.layer) ?? []
    list.push(item)
    byLayer.set(row.layer, list)
  }

  const out: ChatMessage[] = []
  for (let layer = 1; layer <= maxLayer; layer += 1) {
    const env = envelopeForLayer(session, layer)
    const isError =
      current.phase === 'error' &&
      current.current_layer === layer &&
      current.completed_layer < layer
    if (isError) {
      out.push({
        id: `error-${layer}`,
        kind: 'error',
        layer,
        detail: current.error || 'Layer failed',
      })
    } else if (current.completed_layer >= layer || current.current_layer === layer) {
      out.push({
        id: `layer-${layer}`,
        kind: 'layer',
        layer,
        envelope: env,
      })
    }
    out.push(...(byLayer.get(layer) ?? []))
  }
  return out
}
