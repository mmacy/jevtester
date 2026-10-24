import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import { followRun } from '../api/events'
import type { RunSummary } from '../api/types'
import { isActive } from '../lib/run'

export interface RunState {
  summary: RunSummary | null
  error: unknown
  /** True while the event stream is reconnecting. */
  reconnecting: boolean
  /** Replaces the summary, as after a cancel. */
  setSummary: (summary: RunSummary) => void
}

/** Loads a run and, while it's queued or running, follows its events. */
export function useRun(id: string): RunState {
  const [state, setState] = useState<{ id: string; summary: RunSummary | null; error: unknown }>({
    id: '',
    summary: null,
    error: null,
  })
  const [reconnecting, setReconnecting] = useState(false)
  const stream = useRef<{ close: () => void } | null>(null)

  useEffect(() => {
    let live = true
    api.getRun(id).then(
      (summary) => {
        if (!live) return
        setState({ id, summary, error: null })
        if (!isActive(summary.status)) return
        stream.current = followRun(id, {
          onReconnecting: (value) => live && setReconnecting(value),
          onEvent: (event) => {
            if (!live) return
            setState((current) => {
              if (!current.summary) return current
              if ('summary' in event) return { ...current, summary: event.summary }
              const status = event.type === 'progress' ? event.status : current.summary.status
              return { ...current, summary: { ...current.summary, status, counts: event.counts } }
            })
          },
        })
      },
      (error: unknown) => {
        if (live) setState({ id, summary: null, error })
      },
    )
    return () => {
      live = false
      stream.current?.close()
      stream.current = null
    }
  }, [id])

  const setSummary = useCallback(
    (summary: RunSummary) => {
      // An ended run has nothing more to stream.
      if (!isActive(summary.status)) {
        stream.current?.close()
        setReconnecting(false)
      }
      setState({ id, summary, error: null })
    },
    [id],
  )

  const current = state.id === id
  return {
    summary: current ? state.summary : null,
    error: current ? state.error : null,
    reconnecting,
    setSummary,
  }
}
