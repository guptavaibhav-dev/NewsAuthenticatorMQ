import {
  ChainOfThought,
  ChainOfThoughtStep,
  Source,
  SourceList,
  Steps,
  StepsItem,
  SystemMessage,
  Tool,
} from './processKit'
import type { EvidenceItem, RunEnvelope, TraceEvent, WikiHit } from '../types/run'
import { PIPELINE_LAYERS } from '../types/run'

export function LayerProcess({
  run,
  layer,
  liveTrace,
  live = false,
  defaultOpen = false,
}: {
  run: RunEnvelope | null
  layer: number
  liveTrace?: TraceEvent[]
  live?: boolean
  defaultOpen?: boolean
}) {
  const layerId = PIPELINE_LAYERS.find((row) => row.n === layer)?.id
  const events = (liveTrace ?? run?.trace ?? []).filter(
    (event) => Boolean(layerId) && event.layer === layerId,
  )
  const tools = toolsForLayer(run, layer)
  const failures = tools.filter((row) => row.status === 'error' || row.status === 'skipped')
  const empty = tools.filter((row) => row.status === 'empty')
  const sources = sourcesForLayer(run, layer)
  const groups = groupTrace(events)

  if (!events.length && !tools.length && !sources.length && !failures.length) {
    if (!live) return null
    return (
      <Steps title="Processing" defaultOpen>
        <StepsItem status="running">Starting layer {layer}…</StepsItem>
      </Steps>
    )
  }

  return (
    <div className="layer-process">
      {live && (
        <Steps title="Processing" defaultOpen>
          {events.length === 0 ? (
            <StepsItem status="running">Working…</StepsItem>
          ) : (
            events.map((event, index) => (
              <StepsItem key={`${event.ts}-${index}`} status={event.status}>
                <span className="pk-steps-process">{event.process}</span>
                {event.tool && <span className="pk-steps-meta"> · {event.tool}</span>}
                {event.detail && <span className="pk-steps-detail"> — {event.detail}</span>}
              </StepsItem>
            ))
          )}
        </Steps>
      )}

      {!live && groups.length > 0 && (
        <ChainOfThought>
          {groups.map((group, index) => (
            <ChainOfThoughtStep
              key={`${group.process}-${index}`}
              title={`${group.process}${group.tool ? ` · ${group.tool}` : ''} · ${group.status}`}
              defaultOpen={defaultOpen && index === groups.length - 1}
              isLast={index === groups.length - 1}
            >
              {group.details.map((detail) => (
                <p key={detail}>{detail}</p>
              ))}
            </ChainOfThoughtStep>
          ))}
        </ChainOfThought>
      )}

      {failures.length > 0 && (
        <SystemMessage variant={failures.some((row) => row.status === 'error') ? 'error' : 'warning'}>
          {failures.map((row) => row.tool).join(', ')}{' '}
          {failures.every((row) => row.status === 'skipped')
            ? 'skipped or unavailable.'
            : 'failed or were skipped.'}{' '}
          Recorded as missing coverage, not as falsity.
        </SystemMessage>
      )}
      {empty.length > 0 && (
        <SystemMessage variant="warning">
          Empty results from {empty.map((row) => row.tool).join(', ')}. That is not a true/false
          verdict.
        </SystemMessage>
      )}

      {tools.length > 0 && (
        <div className="pk-tool-list">
          {tools.map((row, index) => (
            <Tool
              key={`${row.tool}-${index}`}
              name={row.tool}
              state={row.status === 'ok' ? 'completed' : row.status}
              output={{
                hits: row.hit_count,
                detail: row.detail,
              }}
              errorText={row.status === 'error' ? row.detail : undefined}
              defaultOpen={row.status === 'error'}
            />
          ))}
        </div>
      )}

      {sources.length > 0 && (
        <div className="pk-source-block">
          <p className="pk-source-heading">Sources</p>
          <SourceList>
            {sources.map((item) => (
              <Source
                key={item.href}
                href={item.href}
                label={item.label}
                title={item.title}
                description={item.description}
              />
            ))}
          </SourceList>
        </div>
      )}
    </div>
  )
}

function toolsForLayer(run: RunEnvelope | null, layer: number) {
  if (!run) return []
  if (layer === 1) {
    return [
      {
        tool: 'ingest',
        status: run.input.fetch_status,
        detail: run.input.fetch_error || run.input.publisher_domain || '',
        hit_count: run.input.extracted_char_count || 0,
      },
      ...run.tool_results.filter((row) => row.tool === 'media'),
    ]
  }
  if (layer === 4) {
    const rows = []
    if (run.engines_used.nli) {
      rows.push({
        tool: run.engines_used.nli,
        status: run.engines_used.nli.includes('lexical') ? 'skipped' : 'ok',
        detail: 'claim×evidence NLI',
        hit_count: run.analysis.length,
      })
    }
    if (run.engines_used.evidence_llm) {
      rows.push({
        tool: run.engines_used.evidence_llm,
        status: run.engines_used.evidence_llm === 'skipped' ? 'skipped' : 'ok',
        detail: 'LLM evidence analyst',
        hit_count: 0,
      })
    }
    return rows
  }
  if (layer === 3) {
    return run.tool_results.filter((row) => row.tool !== 'media')
  }
  return []
}

function sourcesForLayer(run: RunEnvelope | null, layer: number) {
  if (!run) return []
  const rows: { href: string; label: string; title: string; description: string }[] = []
  if (layer >= 3) {
    for (const item of uniqueEvidence(run.evidence_items)) {
      if (!item.url) continue
      rows.push({
        href: item.url,
        label: item.outlet || hostOf(item.url),
        title: item.title || item.url,
        description: [item.tool, item.source_band, item.publisher_family]
          .filter(Boolean)
          .join(' · '),
      })
    }
    for (const hit of run.wiki_hits) {
      if (hit.url) rows.push(wikiSource(hit))
    }
    for (const fc of run.corroboration.fact_checks) {
      if (!fc.url) continue
      rows.push({
        href: fc.url,
        label: fc.publisher || 'Fact-check',
        title: fc.claim_text,
        description: fc.textual_rating || 'prior ClaimReview',
      })
    }
  }
  return rows
}

function wikiSource(hit: WikiHit) {
  return {
    href: hit.url || '#',
    label: hit.title || hit.query,
    title: hit.title || hit.query,
    description: hit.found ? hit.description || 'Wikipedia' : 'no page',
  }
}

function uniqueEvidence(items: EvidenceItem[]) {
  return [...new Map(items.map((item) => [item.source_id, item])).values()]
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function groupTrace(events: TraceEvent[]) {
  const groups: { process: string; tool: string | null; status: string; details: string[] }[] = []
  for (const event of events) {
    const last = groups.at(-1)
    if (last && last.process === event.process && last.tool === event.tool) {
      last.status = event.status
      if (event.detail && !last.details.includes(event.detail)) last.details.push(event.detail)
    } else {
      groups.push({
        process: event.process,
        tool: event.tool,
        status: event.status,
        details: event.detail ? [event.detail] : [],
      })
    }
  }
  return groups
}
