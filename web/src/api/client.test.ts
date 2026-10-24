import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, ServerUnreachableError } from './client'
import { useServer } from './server-store'

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

describe('api client', () => {
  beforeEach(() => {
    useServer.setState({ unreachable: false })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed body', async () => {
    const fetchMock = respond(200, { targets: [], checked_at: null })
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.listTargets()).resolves.toEqual({ targets: [], checked_at: null })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/targets',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('sends a JSON body', async () => {
    const fetchMock = respond(200, {})
    vi.stubGlobal('fetch', fetchMock)
    await api.decide({ state: 'Goblins', questions: {}, targets: ['decision-1@foundry'] })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body as string)).toEqual({
      state: 'Goblins',
      questions: {},
      targets: ['decision-1@foundry'],
    })
  })

  it('throws the error envelope as an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      respond(422, {
        error: {
          code: 'invalid_request',
          message: 'Unknown target: clef@nowhere',
          field: 'targets.0',
          details: [{ field: 'targets.0', message: 'Unknown target: clef@nowhere' }],
        },
      }),
    )
    const error = await api.listTargets().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 422,
      code: 'invalid_request',
      message: 'Unknown target: clef@nowhere',
      field: 'targets.0',
      details: [{ field: 'targets.0', message: 'Unknown target: clef@nowhere' }],
    })
  })

  it('turns a response without the envelope into an internal error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Teapot', { status: 418 })))
    await expect(api.listTargets()).rejects.toMatchObject({
      status: 418,
      code: 'internal',
      message: 'GET /api/targets returned 418',
    })
  })

  it.each([502, 503, 504])(
    'treats a %i without the envelope as an unreachable server, as the dev proxy sends',
    async (status) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
      await expect(api.listTargets()).rejects.toBeInstanceOf(ServerUnreachableError)
      expect(useServer.getState().unreachable).toBe(true)
    },
  )

  it('throws when a success has a body that is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 200 })))
    await expect(api.listTargets()).rejects.toMatchObject({
      code: 'internal',
      message: "GET /api/targets returned a body that isn't JSON",
    })
  })

  it('marks the server unreachable when no answer comes back, and clears it on the next answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.listTargets()).rejects.toBeInstanceOf(ServerUnreachableError)
    expect(useServer.getState().unreachable).toBe(true)

    vi.stubGlobal('fetch', respond(200, { targets: [], checked_at: null }))
    await api.listTargets()
    expect(useServer.getState().unreachable).toBe(false)
  })

  it('lets an aborted call reject without marking the server unreachable', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')))
    await expect(
      api.decide({ state: 'x', questions: {} }, controller.signal),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(useServer.getState().unreachable).toBe(false)
  })
})
