import type { ReactNode } from 'react'

export function Steps({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details className="pk-steps" open={defaultOpen}>
      <summary className="pk-steps-trigger">{title}</summary>
      <div className="pk-steps-body">
        <div className="pk-steps-bar" aria-hidden="true" />
        <div className="pk-steps-items">{children}</div>
      </div>
    </details>
  )
}

export function StepsItem({
  children,
  status = 'ok',
}: {
  children: ReactNode
  status?: string
}) {
  return <div className={`pk-steps-item is-${status}`}>{children}</div>
}

export function ChainOfThought({ children }: { children: ReactNode }) {
  return <div className="pk-cot">{children}</div>
}

export function ChainOfThoughtStep({
  title,
  children,
  defaultOpen = false,
  isLast = false,
}: {
  title: string
  children?: ReactNode
  defaultOpen?: boolean
  isLast?: boolean
}) {
  return (
    <details className="pk-cot-step" open={defaultOpen} data-last={isLast || undefined}>
      <summary className="pk-cot-trigger">{title}</summary>
      {children ? <div className="pk-cot-content">{children}</div> : null}
    </details>
  )
}

export function SourceList({ children }: { children: ReactNode }) {
  return <div className="pk-sources">{children}</div>
}

export function Source({
  href,
  label,
  title,
  description,
}: {
  href: string
  label: string
  title?: string
  description?: string
}) {
  let host = ''
  try {
    host = new URL(href).hostname.replace(/^www\./, '')
  } catch {
    host = label
  }
  return (
    <a className="pk-source" href={href} target="_blank" rel="noreferrer">
      <img
        className="pk-source-icon"
        src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`}
        alt=""
        width={14}
        height={14}
      />
      <span className="pk-source-label">{label}</span>
      {(title || description) && (
        <span className="pk-source-tip">
          {title && <strong>{title}</strong>}
          {description && <span>{description}</span>}
          <span className="pk-source-host">{host}</span>
        </span>
      )}
    </a>
  )
}

export function SystemMessage({
  variant = 'warning',
  children,
}: {
  variant?: 'action' | 'warning' | 'error'
  children: ReactNode
}) {
  return (
    <div className={`pk-sys pk-sys-${variant}`} role="status">
      {children}
    </div>
  )
}

export function Tool({
  name,
  state,
  input,
  output,
  errorText,
  defaultOpen = false,
}: {
  name: string
  state: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  errorText?: string
  defaultOpen?: boolean
}) {
  return (
    <details className={`pk-tool is-${state}`} open={defaultOpen}>
      <summary>
        <span className="pk-tool-name">{name}</span>
        <span className="pk-tool-state">{labelize(state)}</span>
      </summary>
      <div className="pk-tool-body">
        {input && Object.keys(input).length > 0 && (
          <p>
            <strong>Input.</strong> {formatFields(input)}
          </p>
        )}
        {output && Object.keys(output).length > 0 && (
          <p>
            <strong>Output.</strong> {formatFields(output)}
          </p>
        )}
        {errorText && <p className="pk-tool-error">{errorText}</p>}
      </div>
    </details>
  )
}

function formatFields(value: Record<string, unknown>) {
  return Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== null && item !== '')
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join(' · ')
}

function labelize(value: string) {
  return value.replaceAll('_', ' ')
}
