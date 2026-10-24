import { create } from 'zustand'

import { api } from '../api/client'
import type { TargetInfo } from '../api/types'

interface TargetsState {
  targets: TargetInfo[] | null
  /** The targets a request goes to when it names none. */
  defaultTargets: string[]
  checkedAt: string | null
  loading: boolean
  checking: boolean
  error: unknown
  /** Reads the targets and their last health check. */
  load: () => Promise<void>
  /** Runs every health check. */
  check: () => Promise<void>
}

export const useTargets = create<TargetsState>((set) => ({
  targets: null,
  defaultTargets: [],
  checkedAt: null,
  loading: false,
  checking: false,
  error: null,
  load: async () => {
    set({ loading: true, error: null })
    try {
      const list = await api.listTargets()
      set({
        targets: list.targets,
        defaultTargets: list.default_targets,
        checkedAt: list.checked_at,
      })
    } catch (error) {
      set({ error })
    } finally {
      set({ loading: false })
    }
  },
  check: async () => {
    set({ checking: true, error: null })
    try {
      const list = await api.checkTargets()
      set({
        targets: list.targets,
        defaultTargets: list.default_targets,
        checkedAt: list.checked_at,
      })
    } catch (error) {
      set({ error })
    } finally {
      set({ checking: false })
    }
  },
}))

/** A target can take requests when its last check found it ready, with or without warnings. */
export function isReady(target: TargetInfo): boolean {
  return target.status === 'ready' || target.status === 'warning'
}
