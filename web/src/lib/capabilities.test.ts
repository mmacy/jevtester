import { describe, expect, it } from 'vitest'

import type { TargetInfo, TargetList } from '../api/types'
import { fixture } from '../test/fixtures'
import { CAPABILITY_ROWS, statusCell } from './capabilities'

const targets = fixture<TargetList>('get_targets.json').targets
const unchecked = fixture<TargetList>('get_targets.unchecked.json').targets

function byName(list: TargetInfo[], name: string): TargetInfo {
  const target = list.find((t) => t.name === name)
  if (!target) throw new Error(`No target ${name}`)
  return target
}

function row(label: string) {
  const found = CAPABILITY_ROWS.find((r) => r.label === label)
  if (!found) throw new Error(`No row ${label}`)
  return found
}

describe('statusCell', () => {
  it('reads each status', () => {
    expect(statusCell(byName(targets, 'decision-1@foundry'))).toEqual({ text: 'Ready', tone: 'ok' })
    expect(statusCell(byName(targets, 'clef-flash@ollama'))).toEqual({
      text: "clef-flash isn't pulled",
      detail: 'Run ollama pull clef-flash (11-12 GB)',
      tone: 'err',
    })
    const warning = statusCell(byName(targets, 'clef-flash@workers-ai'))
    expect(warning.tone).toBe('warn')
    expect(warning.text).toBe('Ready')
    expect(warning.detail).toBeTruthy()
    expect(statusCell(unchecked[0])).toEqual({ text: 'Not checked', tone: 'faint' })
  })
})

describe('capability rows', () => {
  it('reads a hosted target', () => {
    const foundry = byName(targets, 'decision-1@foundry')
    expect(row('Credentials').cell(foundry).text).toBe('Azure CLI, refreshes in 41 min')
    expect(row('Questions per request').cell(foundry).text).toBe('1 to 64')
    expect(row('Concurrency').cell(foundry).text).toBe('8 at once, 100 requests a minute')
    expect(row('Input cost per 1M tokens').cell(foundry)).toEqual({
      text: 'Unknown',
      tone: 'faint',
    })
    expect(row('Images').cell(foundry).text).toBe('No')
  })

  it('reads Workers AI limits', () => {
    const workers = byName(targets, 'clef-flash@workers-ai')
    expect(row('Images').cell(workers).text).toBe('Up to 4, 8 MiB total')
    expect(row('Context window').cell(workers).text).toBe('24,576 tokens, truncates state')
    expect(row('Input cost per 1M tokens').cell(workers).text).toBe('$0.038')
  })

  it('reads a local target', () => {
    const mlx = byName(targets, 'clef-flash-4bit@mlx')
    expect(row('Credentials').cell(mlx).text).toBe('None, local')
    expect(row('Input cost per 1M tokens').cell(mlx).text).toBe('Free')
    expect(row('Concurrency').cell(mlx).text).toBe('1 at a time, shared with mlx')
    const ollama = byName(targets, 'clef-flash@ollama')
    expect(row('Options or levels').cell(ollama).text).toBe('2 to 26')
  })

  it('says a hosted credential is not checked before the first check', () => {
    expect(row('Credentials').cell(byName(unchecked, 'decision-1@foundry'))).toEqual({
      text: 'Not checked',
      tone: 'faint',
    })
  })
})
