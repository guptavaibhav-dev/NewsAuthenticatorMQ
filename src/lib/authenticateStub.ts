export type AuthVerdict = 'authentic' | 'unverified' | 'likely_false'

export type AuthResult = {
  verdict: AuthVerdict
  confidence: number
  model: string
  latencyMs: number
  rationale: string
}

/**
 * Initial test stub for the authentication model.
 * Replace with a real model call later.
 */
export async function authenticateNewsStub(
  content: string,
): Promise<AuthResult> {
  const started = performance.now()
  await delay(700 + Math.random() * 500)

  const length = content.trim().length
  const verdict: AuthVerdict =
    length < 40 ? 'unverified' : length % 3 === 0 ? 'likely_false' : 'authentic'

  return {
    verdict,
    confidence: 0.42 + (length % 50) / 100,
    model: 'newsauth-stub-v0',
    latencyMs: Math.round(performance.now() - started),
    rationale:
      'Placeholder response from the initial authentication stub. Wire a trained model here later.',
  }
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
