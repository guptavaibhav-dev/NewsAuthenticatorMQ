import type { EditorialDecision, Health, RunEnvelope, TraceEvent } from '../types/run'

export async function fetchHealth(probe = false): Promise<Health | null> {
  try {
    const res = await fetch(`/api/health?probe=${probe ? 'true' : 'false'}`)
    if (!res.ok) return null
    return (await res.json()) as Health
  } catch {
    return null
  }
}

export async function startRun(text: string, url: string): Promise<string> {
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, url }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `Run failed (${res.status})`)
  }
  const data = (await res.json()) as { run_id: string }
  return data.run_id
}

export async function fetchRun(runId: string): Promise<RunEnvelope> {
  const res = await fetch(`/api/runs/${runId}`)
  if (!res.ok) throw new Error('Could not load run')
  return (await res.json()) as RunEnvelope
}

export function subscribeRun(
  runId: string,
  onEvent: (event: TraceEvent) => void,
  onComplete: () => void,
): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`)
  source.onmessage = (message) => {
    try {
      const data = JSON.parse(message.data) as TraceEvent
      if (data.type === 'complete') {
        onComplete()
        source.close()
        return
      }
      onEvent(data)
    } catch {
      /* ignore malformed chunks */
    }
  }
  source.onerror = () => {
    onComplete()
    source.close()
  }
  return () => source.close()
}

export async function submitDecision(
  runId: string,
  decision: EditorialDecision,
  notes: string,
): Promise<RunEnvelope> {
  const res = await fetch(`/api/runs/${runId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, notes }),
  })
  if (!res.ok) throw new Error('Could not save editorial decision')
  return (await res.json()) as RunEnvelope
}
