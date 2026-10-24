import { create } from 'zustand'

interface ServerState {
  /** True after a call got no answer, until the next call gets one. */
  unreachable: boolean
  setUnreachable: (unreachable: boolean) => void
}

export const useServer = create<ServerState>((set) => ({
  unreachable: false,
  setUnreachable: (unreachable) => set({ unreachable }),
}))
