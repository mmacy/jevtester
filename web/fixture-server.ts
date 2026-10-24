// Fixture mode: answers /api requests from the backend's saved responses in
// tests/fixtures/api/, so the UI builds and tests without a running server.
//
// A fixture's file name is the method and the path after /api, joined with
// underscores. A `{name}` part matches any one path segment:
//
//   get_targets.json              GET /api/targets
//   get_runs_{id}.json            GET /api/runs/0142
//   get_runs_{id}_events.sse      GET /api/runs/0142/events, replayed as SSE
//
// An exact name wins over one with placeholders. The query string is ignored.
//
// A variant adds a dot and a name after the route part, like
// post_decide.partial.json or post_decide.422.json. A request gets a variant
// only when its X-Fixture header names it. A numeric variant is served with
// that HTTP status.
import { readdirSync, readFileSync } from 'node:fs'
import type { ServerResponse } from 'node:http'
import { join } from 'node:path'

import type { Plugin } from 'vite'

const SSE_EXTENSIONS = ['.sse', '.txt']
const EXTENSIONS = ['.json', ...SSE_EXTENSIONS]

/** The request header that picks a fixture variant. */
export const VARIANT_HEADER = 'x-fixture'

interface FixtureName {
  method: string
  parts: string[]
  variant: string | null
}

/** Reads a fixture file name, or returns null when it isn't one. */
export function parseFixtureName(file: string): FixtureName | null {
  const ext = EXTENSIONS.find((e) => file.endsWith(e))
  if (!ext) return null
  const stem = file.slice(0, -ext.length)
  // Placeholders never contain a dot, so the first dot starts the variant.
  const dot = stem.indexOf('.')
  const route = dot === -1 ? stem : stem.slice(0, dot)
  const variant = dot === -1 ? null : stem.slice(dot + 1)
  // Split on underscores outside braces, so `{case_id}` stays one part.
  const [method, ...parts] = route.match(/\{[^}]*\}|[^_{}]+/g) ?? []
  if (!method) return null
  return { method, parts, variant }
}

/** The fixture file for a request and variant, or null when none matches. */
export function matchFixture(
  method: string,
  pathname: string,
  files: readonly string[],
  variant: string | null = null,
): string | null {
  const segments = pathname
    .replace(/^\/api\/?/, '')
    .split('/')
    .filter(Boolean)
  let best: { file: string; placeholders: number } | null = null
  for (const file of files) {
    const name = parseFixtureName(file)
    if (!name || name.variant !== variant) continue
    if (name.method !== method.toLowerCase() || name.parts.length !== segments.length) continue
    let placeholders = 0
    const matches = name.parts.every((part, i) => {
      if (part.startsWith('{')) {
        placeholders++
        return true
      }
      return part === segments[i]
    })
    if (matches && (best === null || placeholders < best.placeholders)) {
      best = { file, placeholders }
    }
  }
  return best?.file ?? null
}

/** The HTTP status to serve a fixture with: its variant if that's a status code, otherwise 200. */
export function fixtureStatus(file: string): number {
  const variant = parseFixtureName(file)?.variant
  return variant && /^[1-5]\d\d$/.test(variant) ? Number(variant) : 200
}

/** Splits an SSE fixture into its events, each without the blank line that ends it. */
export function splitEvents(text: string): string[] {
  return text
    .replace(/\r\n/g, '\n')
    .split(/\n\n+/)
    .map((block) => block.trim())
    .filter(Boolean)
}

function sendError(res: ServerResponse, status: number, code: string, message: string) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ error: { code, message } }))
}

async function replayEvents(res: ServerResponse, text: string, delayMs: number) {
  res.statusCode = 200
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.flushHeaders()
  for (const event of splitEvents(text)) {
    if (res.destroyed) return
    await new Promise((resolve) => setTimeout(resolve, delayMs))
    res.write(`${event}\n\n`)
  }
  res.end()
}

export function fixtureServer(dir: string, sseDelayMs = 150): Plugin {
  return {
    name: 'jevtester-fixtures',
    configureServer(server) {
      server.middlewares.use('/api', (req, res) => {
        const url = new URL(req.originalUrl ?? req.url ?? '/', 'http://fixtures')
        // A missing directory means no fixtures yet, not a broken server.
        let files: string[]
        try {
          files = readdirSync(dir)
        } catch {
          files = []
        }
        const header = req.headers[VARIANT_HEADER]
        const variant = (Array.isArray(header) ? header[0] : header) ?? null
        const file = matchFixture(req.method ?? 'GET', url.pathname, files, variant)
        if (!file) {
          const named = variant ? ` with variant ${variant}` : ''
          sendError(res, 404, 'not_found', `No fixture for ${req.method} ${url.pathname}${named}`)
          return
        }
        const body = readFileSync(join(dir, file), 'utf8')
        if (SSE_EXTENSIONS.some((e) => file.endsWith(e))) {
          void replayEvents(res, body, sseDelayMs)
          return
        }
        res.statusCode = fixtureStatus(file)
        res.setHeader('Content-Type', 'application/json')
        res.end(body)
      })
    },
  }
}
