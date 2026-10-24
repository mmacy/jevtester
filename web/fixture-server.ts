// Fixture mode: answers /api requests from the backend's saved responses in
// tests/fixtures/api/, so the UI builds and tests without a running server.
//
// A fixture's file name is the method and the path after /api, joined with
// underscores. A `{name}` part matches any one path segment:
//
//   get_targets.json            GET /api/targets
//   get_runs_{id}.json          GET /api/runs/0142
//   get_runs_{id}_events.sse    GET /api/runs/0142/events, replayed as SSE
//
// An exact name wins over one with placeholders. The query string is ignored.
import { readdirSync, readFileSync } from 'node:fs'
import type { ServerResponse } from 'node:http'
import { join } from 'node:path'

import type { Plugin } from 'vite'

const SSE_EXTENSIONS = ['.sse', '.txt']
const EXTENSIONS = ['.json', ...SSE_EXTENSIONS]

/** The fixture file for a request, or null when none matches. */
export function matchFixture(
  method: string,
  pathname: string,
  files: readonly string[],
): string | null {
  const segments = pathname
    .replace(/^\/api\/?/, '')
    .split('/')
    .filter(Boolean)
  let best: { file: string; placeholders: number } | null = null
  for (const file of files) {
    const ext = EXTENSIONS.find((e) => file.endsWith(e))
    if (!ext) continue
    const [fileMethod, ...parts] = file.slice(0, -ext.length).split('_')
    if (fileMethod !== method.toLowerCase() || parts.length !== segments.length) continue
    let placeholders = 0
    const matches = parts.every((part, i) => {
      if (/^\{[^}]+\}$/.test(part)) {
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
        const file = matchFixture(req.method ?? 'GET', url.pathname, files)
        if (!file) {
          sendError(res, 404, 'no_fixture', `No fixture for ${req.method} ${url.pathname}`)
          return
        }
        const body = readFileSync(join(dir, file), 'utf8')
        if (SSE_EXTENSIONS.some((e) => file.endsWith(e))) {
          void replayEvents(res, body, sseDelayMs)
          return
        }
        res.statusCode = 200
        res.setHeader('Content-Type', 'application/json')
        res.end(body)
      })
    },
  }
}
