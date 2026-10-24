import { create } from 'zustand'

import { api, ApiError, ServerUnreachableError } from '../api/client'
import type { AnswerValue, DecisionRequest, TargetResult } from '../api/types'
import type { MatrixColumn } from '../lib/matrix'
import {
  asEchoed,
  newQuestion,
  toRequest,
  type RequestBody,
  type RequestDraft,
} from '../lib/request'
import { useTargets } from './targets'

export type CompareMode = 'quick' | 'full'

export interface Asked {
  /** The request as the API echoes it, which labels the matrix rows. */
  request: DecisionRequest
  /** The state and questions as sent. */
  body: RequestBody
  /** The targets named. Empty when the server picked its defaults. */
  targets: string[]
  askedAt: string | null
  columns: MatrixColumn[]
}

/** The answer a case expects to each question, keyed by question id. */
export type Expected = Record<string, AnswerValue>

interface CompareState {
  mode: CompareMode
  draft: RequestDraft
  /** The targets checked in the full request, in the config's order. */
  targets: string[]
  asked: Asked | null
  asking: boolean
  /** A failure of the request itself, like a 422, rather than of one target. */
  askError: unknown
  /** Whether selecting a row in the matrix marks it as the expected answer. */
  marking: boolean
  expected: Expected
  /** Score levels of slack, keyed by question id. */
  tolerance: Record<string, number>
  setMarking: (marking: boolean) => void
  /** Sets or, with null, clears the expected answer to a question. */
  setExpected: (question: string, answer: AnswerValue | null) => void
  setTolerance: (question: string, tolerance: number) => void
  setMode: (mode: CompareMode) => void
  updateDraft: (change: (draft: RequestDraft) => RequestDraft) => void
  setTargets: (targets: string[]) => void
  ask: () => Promise<void>
  /** Opens a saved case in the full request, with its expected answers. */
  openCase: (
    draft: RequestDraft,
    targets: string[],
    expected: Expected,
    tolerance: Record<string, number>,
  ) => void
}

function emptyDraft(): RequestDraft {
  return { stateMode: 'text', stateText: '', questions: [newQuestion('q1')] }
}

function columnFor(result: TargetResult): MatrixColumn {
  return { target: result.target, state: result.ok ? 'ok' : 'failed', result }
}

function failedColumn(target: string, error: unknown): MatrixColumn {
  if (error instanceof ApiError) {
    return {
      target,
      state: 'failed',
      result: null,
      error: { code: error.code, message: error.message },
    }
  }
  if (error instanceof ServerUnreachableError) {
    return {
      target,
      state: 'failed',
      result: null,
      error: { code: 'connection', message: error.message },
    }
  }
  return {
    target,
    state: 'failed',
    result: null,
    error: { code: 'internal', message: String(error) },
  }
}

function keep<T>(values: Record<string, T>, body: RequestBody): Record<string, T> {
  return Object.fromEntries(Object.entries(values).filter(([id]) => id in body.questions))
}

function isRequestError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.code === 'invalid_request' &&
    !(error.field ?? '').startsWith('targets.')
  )
}

let controller: AbortController | null = null

export const useCompare = create<CompareState>((set, get) => ({
  mode: 'quick',
  draft: emptyDraft(),
  targets: [],
  asked: null,
  asking: false,
  askError: null,
  marking: false,
  expected: {},
  tolerance: {},
  setMarking: (marking) => set({ marking }),
  setExpected: (question, answer) => {
    const expected = { ...get().expected }
    if (answer === null) delete expected[question]
    else expected[question] = answer
    set({ expected })
  },
  setTolerance: (question, tolerance) =>
    set({ tolerance: { ...get().tolerance, [question]: tolerance } }),
  setMode: (mode) => {
    // The full request starts with the default targets checked.
    if (mode === 'full' && get().targets.length === 0) {
      set({ targets: [...useTargets.getState().defaultTargets] })
    }
    set({ mode })
  },
  updateDraft: (change) => set({ draft: change(get().draft) }),
  setTargets: (targets) => set({ targets }),
  openCase: (draft, targets, expected, tolerance) => {
    controller?.abort()
    set({
      mode: 'full',
      draft,
      targets,
      expected,
      tolerance,
      asked: null,
      askError: null,
      asking: false,
    })
  },
  ask: async () => {
    controller?.abort()
    const mine = new AbortController()
    controller = mine
    const { mode, draft } = get()
    // The quick test asks the config's default targets.
    const targets = mode === 'quick' ? useTargets.getState().defaultTargets : get().targets
    const body = toRequest(draft)
    const request = asEchoed(body)
    const isCurrent = () => controller === mine
    const sent = { request, body, targets }
    // Expected answers carry over for the questions this request still asks.
    set({ expected: keep(get().expected, body), tolerance: keep(get().tolerance, body) })

    if (targets.length === 0) {
      // The targets haven't loaded, so let the server pick its defaults.
      set({ asking: true, askError: null, asked: { ...sent, askedAt: null, columns: [] } })
      try {
        const response = await api.decide({ ...body, targets: [] }, mine.signal)
        if (isCurrent()) {
          set({
            asked: {
              ...sent,
              askedAt: response.asked_at,
              columns: response.results.map(columnFor),
            },
          })
        }
      } catch (error) {
        if (isCurrent() && !mine.signal.aborted) set({ askError: error, asked: null })
      } finally {
        if (isCurrent()) set({ asking: false })
      }
      return
    }

    // One call per target, so each column fills in when its answer arrives.
    const pending: MatrixColumn[] = targets.map((target) => ({
      target,
      state: 'pending',
      result: null,
    }))
    set({ asking: true, askError: null, asked: { ...sent, askedAt: null, columns: pending } })
    const place = (column: MatrixColumn, askedAt: string | null) => {
      if (!isCurrent()) return
      const asked = get().asked
      if (!asked) return
      set({
        asked: {
          ...asked,
          askedAt: asked.askedAt ?? askedAt,
          columns: asked.columns.map((c) => (c.target === column.target ? column : c)),
        },
      })
    }
    await Promise.all(
      targets.map(async (target) => {
        try {
          const response = await api.decide({ ...body, targets: [target] }, mine.signal)
          const result = response.results.find((r) => r.target === target) ?? response.results[0]
          place(result ? columnFor(result) : failedColumn(target, 'No result'), response.asked_at)
        } catch (error) {
          if (mine.signal.aborted) return
          // A 422 on the state or the questions is about the whole request. One on
          // targets.0 is about this column's target alone.
          if (isRequestError(error) && isCurrent()) set({ askError: error })
          place(failedColumn(target, error), null)
        }
      }),
    )
    if (isCurrent()) set({ asking: false })
  },
}))
