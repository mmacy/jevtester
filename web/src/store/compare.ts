import { create } from 'zustand'

import { api, ApiError, ServerUnreachableError } from '../api/client'
import type { DecisionRequest, TargetResult } from '../api/types'
import type { MatrixColumn } from '../lib/matrix'
import { asEchoed, newQuestion, toRequest, type RequestDraft } from '../lib/request'
import { useTargets } from './targets'

export type CompareMode = 'quick' | 'full'

export interface Asked {
  request: DecisionRequest
  askedAt: string | null
  columns: MatrixColumn[]
}

interface CompareState {
  mode: CompareMode
  draft: RequestDraft
  /** The targets checked in the full request, in the config's order. */
  targets: string[]
  asked: Asked | null
  asking: boolean
  /** A failure of the request itself, like a 422, rather than of one target. */
  askError: unknown
  setMode: (mode: CompareMode) => void
  updateDraft: (change: (draft: RequestDraft) => RequestDraft) => void
  setTargets: (targets: string[]) => void
  ask: () => Promise<void>
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

let controller: AbortController | null = null

export const useCompare = create<CompareState>((set, get) => ({
  mode: 'quick',
  draft: emptyDraft(),
  targets: [],
  asked: null,
  asking: false,
  askError: null,
  setMode: (mode) => {
    // The full request starts with the default targets checked.
    if (mode === 'full' && get().targets.length === 0) {
      set({ targets: [...useTargets.getState().defaultTargets] })
    }
    set({ mode })
  },
  updateDraft: (change) => set({ draft: change(get().draft) }),
  setTargets: (targets) => set({ targets }),
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

    // One call per target, so each column fills in when its answer arrives.
    const pending: MatrixColumn[] = targets.map((target) => ({
      target,
      state: 'pending',
      result: null,
    }))
    set({ asking: true, askError: null, asked: { request, askedAt: null, columns: pending } })
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
          if (error instanceof ApiError && error.code === 'invalid_request' && isCurrent()) {
            set({ askError: error })
          }
          place(failedColumn(target, error), null)
        }
      }),
    )
    if (isCurrent()) set({ asking: false })
  },
}))
