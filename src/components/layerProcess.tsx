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
import type { RunEnvelope, TraceEvent } from '../types/run'
import { PIPELINE_LAYERS } from '../types/run'
import { mergeReasonPlain, plainLabel } from '../lib/plainLanguage'

export type LayerToolRow = {
  tool: string
  status: string
  detail: string
  hit_count: number
}

export type LayerSourceRow = {
  href: string
  label: string
  title: string
  description: string
}

export type TraceGroup = {
  process: string
  tool: string | null
  status: string
  details: string[]
}

export function inspectLayer(run: RunEnvelope | null, layer: number, liveTrace?: TraceEvent[]) {
  const layerId = PIPELINE_LAYERS.find((row) => row.n === layer)?.id
  const events = (liveTrace ?? run?.trace ?? []).filter(
    (event) => Boolean(layerId) && event.layer === layerId,
  )
  const tools = toolsForLayer(run, layer)
  const failures = tools.filter((row) => row.status === 'error' || row.status === 'skipped')
  const empty = tools.filter((row) => row.status === 'empty')
  const sources = sourcesForLayer(run, layer)
  const groups = groupTrace(events)
  return { events, tools, failures, empty, sources, groups }
}

export function machineryPieceCount(run: RunEnvelope | null, layer: number) {
  const { tools, sources, groups } = inspectLayer(run, layer)
  return groups.length + tools.length + sources.length
}

export function LayerDegradation({ run, layer }: { run: RunEnvelope; layer: number }) {
  const { failures, empty } = inspectLayer(run, layer)
  if (!failures.length && !empty.length) return null
  return (
    <div className="layer-degradation">
      {failures.length > 0 && (
        <SystemMessage variant={failures.some((row) => row.status === 'error') ? 'error' : 'warning'}>
          {failures.map((row) => plainLabel(row.tool) || row.tool).join(', ')}{' '}
          {failures.every((row) => row.status === 'skipped')
            ? 'were not run or were unavailable.'
            : 'failed or were not run.'}{' '}
          Recorded as missing coverage, not as a finding about the article.
        </SystemMessage>
      )}
      {empty.length > 0 && (
        <SystemMessage variant="warning">
          {empty.map((row) => plainLabel(row.tool) || row.tool).join(', ')} ran and returned
          nothing. That is not a true/false verdict.
        </SystemMessage>
      )}
    </div>
  )
}

export function LayerMachinery({ run, layer }: { run: RunEnvelope; layer: number }) {
  const { groups, tools, sources } = inspectLayer(run, layer)
  if (!groups.length && !tools.length && !sources.length) return null
  return (
    <div className="layer-machinery-flat">
      {groups.length > 0 && (
        <section>
          <h5>Process steps</h5>
          <ol className="plain-list machinery-list">
            {groups.map((group, index) => (
              <li key={`${group.process}-${index}`}>
                <span title={group.status}>
                  {group.process}
                  {group.tool ? ` · ${group.tool}` : ''} · {plainLabel(group.status)}
                </span>
                {group.details.map((detail) => (
                  <p key={detail} className="gloss">
                    {detail}
                  </p>
                ))}
              </li>
            ))}
          </ol>
        </section>
      )}
      {tools.length > 0 && (
        <section>
          <h5>Tools</h5>
          <ul className="plain-list machinery-list">
            {tools.map((row, index) => (
              <li key={`${row.tool}-${index}`} title={row.status}>
                {plainLabel(row.tool) || row.tool} — {plainLabel(row.status)}
                {row.hit_count ? ` — ${row.hit_count} hit${row.hit_count === 1 ? '' : 's'}` : ''}
                {row.detail ? ` — ${row.detail}` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}
      {sources.length > 0 && (
        <section>
          <h5>Source strip</h5>
          <ul className="plain-list machinery-list">
            {sources.map((item) => (
              <li key={item.href}>
                <a href={item.href} target="_blank" rel="noreferrer">
                  {item.label}
                </a>
                {item.description ? ` — ${item.description}` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

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
  const { events, tools, failures, empty, sources, groups } = inspectLayer(run, layer, liveTrace)

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

function toolsForLayer(run: RunEnvelope | null, layer: number): LayerToolRow[] {
  if (!run) return []
  if (layer === 1) {
    return [
      {
        tool: 'ingest',
        status: run.input.fetch_status,
        detail: run.input.fetch_error || run.input.publisher_domain || '',
        hit_count: run.input.extracted_char_count || 0,
      },
    ]
  }
  if (layer === 4) {
    const rows: LayerToolRow[] = []
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
    if (run.retrieval?.coverage.adapters.length) {
      return run.retrieval.coverage.adapters.map((report) => ({
        tool: report.adapter,
        status: report.status.startsWith('skipped') ? 'skipped' : report.status,
        detail: report.reason || '',
        hit_count: report.hits_returned,
      }))
    }
    return run.tool_results
  }
  return []
}

function sourcesForLayer(run: RunEnvelope | null, layer: number): LayerSourceRow[] {
  if (!run) return []
  const rows: LayerSourceRow[] = []
  if (layer >= 3 && run.retrieval) {
    for (const source of run.retrieval.independent_sources) {
      if (!source.representative_url) continue
      const merge = mergeReasonPlain(source.merge_reason)
      rows.push({
        href: source.representative_url,
        label: source.publisher_ids.join(', ') || hostOf(source.representative_url),
        title: source.representative_url,
        description: merge.label,
      })
    }
    for (const record of run.retrieval.factchecks) {
      if (!record.review_url) continue
      rows.push({
        href: record.review_url,
        label: record.reviewer_name || 'Fact-check',
        title: record.reviewed_claim_text,
        description: record.rating_text || 'prior review',
      })
    }
  }
  return rows
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function groupTrace(events: TraceEvent[]): TraceGroup[] {
  const groups: TraceGroup[] = []
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
