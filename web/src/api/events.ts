// Follows a run's server-sent events. Every event carries the run's counts,
// so a client that reconnects needs no history. The browser reconnects on
// its own whenever a stream drops, so this closes the stream itself after a
// final event.
import type { RunEvent } from './types'

const EVENT_TYPES = [
  'progress',
  'result',
  'target_skipped',
  'finished',
  'cancelled',
  'error',
] as const

const FINAL = new Set<RunEvent['type']>(['finished', 'cancelled', 'error'])

export interface RunStream {
  close: () => void
}

export interface RunStreamHandlers {
  onEvent: (event: RunEvent) => void
  /** True while the browser is reconnecting a dropped stream. */
  onReconnecting: (reconnecting: boolean) => void
}

export function followRun(
  runId: string,
  { onEvent, onReconnecting }: RunStreamHandlers,
): RunStream {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`)
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (message) => {
      onReconnecting(false)
      const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent
      onEvent(event)
      if (FINAL.has(event.type)) source.close()
    })
  }
  source.onerror = () => {
    if (source.readyState !== EventSource.CLOSED) onReconnecting(true)
  }
  return { close: () => source.close() }
}

export function isFinal(event: RunEvent): boolean {
  return FINAL.has(event.type)
}
