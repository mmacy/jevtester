import { vi } from 'vitest'

type Reply = { status?: number; body: unknown } | (() => Promise<never>)

/**
 * Replaces fetch with canned replies keyed by `METHOD /api/path`. A request
 * with no reply gets a 404 in the error envelope.
 */
export function stubApi(replies: Record<string, Reply>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    const reply = replies[key]
    if (typeof reply === 'function') return reply()
    if (!reply) {
      return new Response(
        JSON.stringify({ error: { code: 'not_found', message: key, field: null, details: [] } }),
        { status: 404 },
      )
    }
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
