import type { EditorialDecision, Health, RunEnvelope, TraceEvent } from '../types/run'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type StepAction = 'proceed' | 'rerun'

export type StepResult = {
  run_id: string
  layer: number
  next_layer: number | null
  envelope: RunEnvelope
}

export async function fetchHealth(probe = false): Promise<Health | null> {
  try {
    const res = await fetch(`/api/health?probe=${probe ? 'true' : 'false'}`)
    if (!res.ok) return null
    return (await res.json()) as Health
  } catch {
    return null
  }
}

export async function startRun(text: string, url: string): Promise<StepResult> {
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, url }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `Run failed (${res.status})`)
  }
  return (await res.json()) as StepResult
}

export async function fetchRun(runId: string): Promise<RunEnvelope> {
  const res = await fetch(`/api/runs/${runId}`)
  if (!res.ok) {
    throw new ApiError(
      res.status,
      res.status === 404
        ? 'The API restarted and this run is gone. Start a new authentication.'
        : 'Could not load run',
    )
  }
  return (await res.json()) as RunEnvelope
}

export async function stepRun(runId: string, action: StepAction = 'proceed'): Promise<StepResult> {
  try {
    const res = await fetch(`/api/runs/${runId}/step`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    if (res.status === 409) {
      const body = await res.text()
      if (isRunningConflict(body)) {
        return waitForSettledRun(runId)
      }
      throw new Error(body || 'Step conflict')
    }
    if (!res.ok) {
      const body = await res.text()
      throw new Error(body || `Step failed (${res.status})`)
    }
    return (await res.json()) as StepResult
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof Error && (isAbortOrNetwork(err) || isRunningConflict(err.message))) {
      return waitForSettledRun(runId)
    }
    throw err
  }
}

function isRunningConflict(body: string) {
  const lower = body.toLowerCase()
  return (
    lower.includes('already running') || lower.includes('while a layer is executing')
  )
}

function isAbortOrNetwork(err: Error) {
  const text = err.message.toLowerCase()
  return (
    err.name === 'TypeError' ||
    text.includes('failed to fetch') ||
    text.includes('network') ||
    text.includes('timeout') ||
    text.includes('abort')
  )
}

async function waitForSettledRun(runId: string): Promise<StepResult> {
  const deadline = Date.now() + 8 * 60 * 1000
  while (Date.now() < deadline) {
    let envelope: RunEnvelope
    try {
      envelope = await fetchRun(runId)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) throw err
      await new Promise((resolve) => setTimeout(resolve, 1000))
      continue
    }
    if (
      envelope.phase === 'awaiting_decision' ||
      envelope.phase === 'complete' ||
      envelope.phase === 'error'
    ) {
      return {
        run_id: runId,
        layer: envelope.current_layer ?? 0,
        next_layer: null,
        envelope,
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error('Timed out waiting for the current layer to finish')
}

export async function askRun(
  runId: string,
  layer: number,
  question: string,
): Promise<string> {
  const res = await fetch(`/api/runs/${runId}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layer, question }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `Ask failed (${res.status})`)
  }
  const data = (await res.json()) as { answer: string }
  return data.answer
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
): Promise<StepResult> {
  const res = await fetch(`/api/runs/${runId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, notes }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || 'Could not save editorial decision')
  }
  return (await res.json()) as StepResult
}
