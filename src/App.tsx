import { useState } from 'react'
import { authenticateNewsStub } from './lib/authenticateStub'
import type { AuthResult } from './lib/authenticateStub'

type Status = 'idle' | 'running' | 'done'

export default function App() {
  const [content, setContent] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<AuthResult | null>(null)

  async function handleAuthenticate() {
    if (!content.trim()) return
    setStatus('running')
    setResult(null)
    const next = await authenticateNewsStub(content)
    setResult(next)
    setStatus('done')
  }

  return (
    <div className="app">
      <header className="header">
        <p className="brand">NewsAuth</p>
        <p className="tagline">A framework for authenticating news content</p>
      </header>

      <main className="main">
        <section className="panel input-panel" aria-labelledby="input-heading">
          <h1 id="input-heading">Authenticate</h1>
          <p className="lede">
            Paste a news claim, article excerpt, or social post. The model stub
            returns a placeholder verdict for UI testing.
          </p>

          <label className="field-label" htmlFor="news-content">
            News content
          </label>
          <textarea
            id="news-content"
            className="content-input"
            placeholder="Paste the piece of news you want to authenticate…"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
          />

          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={handleAuthenticate}
              disabled={!content.trim() || status === 'running'}
            >
              {status === 'running' ? 'Running stub…' : 'Run authentication stub'}
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setContent('')
                setResult(null)
                setStatus('idle')
              }}
              disabled={status === 'running'}
            >
              Clear
            </button>
          </div>
        </section>

        <section className="panel result-panel" aria-labelledby="result-heading">
          <h2 id="result-heading">Result</h2>

          {status === 'idle' && (
            <p className="muted">No run yet. Submit content to see stub output.</p>
          )}

          {status === 'running' && (
            <p className="muted pulse">Calling model stub…</p>
          )}

          {status === 'done' && result && (
            <div className="result">
              <dl className="result-grid">
                <div>
                  <dt>Verdict</dt>
                  <dd className="verdict">{result.verdict}</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{Math.round(result.confidence * 100)}%</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{result.model}</dd>
                </div>
                <div>
                  <dt>Latency</dt>
                  <dd>{result.latencyMs} ms</dd>
                </div>
              </dl>
              <p className="rationale">{result.rationale}</p>
              <p className="stub-note">Stub only — not a real authenticity judgement.</p>
            </div>
          )}
        </section>
      </main>

      <footer className="footer">
        <p>Thesis prototype · COMP4092 · Macquarie University</p>
      </footer>
    </div>
  )
}
