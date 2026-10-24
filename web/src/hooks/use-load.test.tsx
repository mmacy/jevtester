// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useLoad } from './use-load'

describe('useLoad', () => {
  it('loads, reloads, and loads again for a new key', async () => {
    const load = vi.fn(async (key: string) => `${key}:${load.mock.calls.length}`)
    const { result, rerender } = renderHook(({ k }) => useLoad(() => load(k), k), {
      initialProps: { k: 'a' },
    })
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.data).toBe('a:1'))
    expect(result.current.loading).toBe(false)

    act(() => result.current.reload())
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.data).toBe('a:2'))

    rerender({ k: 'b' })
    expect(result.current.data).toBeNull()
    await waitFor(() => expect(result.current.data).toBe('b:3'))
  })

  it('keeps the error', async () => {
    const { result } = renderHook(() => useLoad(() => Promise.reject(new Error('nope')), 'x'))
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error))
    expect(result.current.loading).toBe(false)
  })
})
