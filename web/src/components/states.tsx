// The states every view and data component shares: loading, empty, error, and
// a target that can't run.
import type { ReactNode } from 'react'

import type { ErrorDetail } from '../api/types'
import { useElapsed } from '../hooks/use-elapsed'
import { Button } from './button'

// A wait longer than this shows its elapsed time.
export const SHOW_ELAPSED_AFTER_S = 10

/** A small spinner, with the elapsed time once a wait runs long. */
export function Spinner({ label = 'Loading' }: { label?: string }) {
  const elapsed = useElapsed()
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-dim">
      <span
        aria-hidden="true"
        className="size-3 animate-spin rounded-full border-2 border-line border-t-pick"
      />
      <span className="sr-only">{label}</span>
      {elapsed >= SHOW_ELAPSED_AFTER_S ? <span>{elapsed} s</span> : null}
    </span>
  )
}

/** Gray placeholder rows in a grid's frame while its data loads. */
export function LoadingRows({ rows, columns }: { rows: number; columns: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} data-testid="loading-row">
          {Array.from({ length: columns }, (_, c) => (
            <td key={c} className="h-[38px] animate-pulse rounded-[2px] bg-surface" />
          ))}
        </tr>
      ))}
    </>
  )
}

/** A label for an empty grid, and the action that fills it. */
export function EmptyState({ label, action }: { label: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border border-dashed border-line px-4 py-5 text-dim">
      <span>{label}</span>
      {action}
    </div>
  )
}

interface ErrorStateProps {
  code: string
  message: string
  details?: readonly ErrorDetail[]
  onRetry?: () => void
}

/** An API error's code and message, each validation detail, and a retry. */
export function ErrorState({ code, message, details = [], onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="rounded bg-err-bg px-4 py-3 text-err-ink shadow-[inset_3px_0_0_var(--color-err)]"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <b className="font-mono text-sm font-normal text-err">{code}</b>
        <span>{message}</span>
        {onRetry ? (
          <Button className="ml-auto" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </div>
      {details.length > 0 ? (
        <ul className="m-0 mt-2 list-none p-0 text-sm">
          {details.map((detail) => (
            <li key={`${detail.field}:${detail.message}`}>
              {detail.field ? <code className="font-mono text-err">{detail.field}</code> : null}{' '}
              {detail.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/** The hatched cell for a target that can't run. Its column keeps its place in the grid. */
export function NotReadyCell({ label }: { label?: string }) {
  return (
    <td className="hatch h-[38px] rounded-[2px] px-2 text-center text-xs text-faint" data-not-ready>
      {label}
    </td>
  )
}

/** The bar under the top bar when the jevtester server can't be reached. */
export function ServerUnreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-center gap-4 border-b border-line bg-err-bg px-6 py-2 text-err-ink"
    >
      <span>Can't reach the jevtester server at 127.0.0.1:8640</span>
      <Button onClick={onRetry}>Retry</Button>
    </div>
  )
}
