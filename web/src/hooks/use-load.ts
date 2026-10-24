import { useCallback, useEffect, useRef, useState } from 'react'

export interface Loaded<T> {
  data: T | null
  error: unknown
  loading: boolean
  reload: () => void
}

/** Loads data when the key changes, and again on reload. A stale answer is dropped. */
export function useLoad<T>(load: () => Promise<T>, key: string): Loaded<T> {
  // The key says when to load again, so the latest loader lives in a ref.
  const loader = useRef(load)
  useEffect(() => {
    loader.current = load
  })
  const [state, setState] = useState<{
    key: string
    attempt: number
    data: T | null
    error: unknown
  }>({
    key: '',
    attempt: -1,
    data: null,
    error: null,
  })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    loader.current().then(
      (data) => {
        if (live) setState({ key, attempt, data, error: null })
      },
      (error: unknown) => {
        if (live) setState({ key, attempt, data: null, error })
      },
    )
    return () => {
      live = false
    }
  }, [key, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  const current = state.key === key
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !current || state.attempt !== attempt,
    reload,
  }
}
