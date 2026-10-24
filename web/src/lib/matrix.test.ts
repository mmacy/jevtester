import { describe, expect, it } from 'vitest'

import type { DecideResponse, TargetResult } from '../api/types'
import { fixture } from '../test/fixtures'
import { formatCount, formatUsd } from './format'
import { buildMatrix, spread, type MatrixColumn, type MatrixRow } from './matrix'

const partial = fixture<DecideResponse>('post_decide.partial.json')

function columnsOf(results: TargetResult[]): MatrixColumn[] {
  return results.map((result) => ({
    target: result.target,
    state: result.ok ? 'ok' : 'failed',
    result,
  }))
}

function find(rows: MatrixRow[], key: string) {
  const row = rows.find((r) => r.key === key)
  if (!row) throw new Error(`No row ${key}`)
  return row
}

describe('spread', () => {
  it('is max minus min of the values present', () => {
    expect(spread([0.9, null, 0.6])).toBeCloseTo(0.3)
    expect(spread([0.9, null])).toBeNull()
  })
})

describe('buildMatrix', () => {
  const columns = columnsOf(partial.results)
  const rows = buildMatrix(partial.request, columns, (t) => t.endsWith('@ollama'))

  it('has a group per question, in request order, then speed and cost', () => {
    const groups = rows.filter((r) => r.kind === 'group').map((r) => r.key)
    expect(groups).toEqual([
      ...Object.keys(partial.request.questions).map((id) => `${id}:group`),
      'usage',
    ])
  })

  it('lists choice options in option order and outlines each target’s choice', () => {
    const parley = find(rows, 'intent:parley')
    expect(parley.kind).toBe('heat')
    if (parley.kind !== 'heat') return
    expect(parley.cells.map((c) => c.picked)).toEqual([true, true, false])
    expect(parley.cells[0].value).toBeCloseTo(0.9996, 3)
    expect(parley.cells[2].value).toBeNull()
    expect(parley.spread).not.toBeNull()
  })

  it('outlines the score level the evaluator counts', () => {
    const foundry = partial.results[0].answers.reaction
    if (foundry.type !== 'score') throw new Error('reaction should be a score')
    const level = find(rows, `reaction:${foundry.level}`)
    if (level.kind !== 'heat') throw new Error('expected a heat row')
    expect(level.cells[0].picked).toBe(true)
    const score = find(rows, 'reaction:score')
    if (score.kind !== 'score') throw new Error('expected a score row')
    expect(score.levels).toBe(5)
    expect(score.cells[0]).toBeCloseTo(2.21, 2)
  })

  it('leaves a failed target’s cells empty', () => {
    const latency = find(rows, 'latency')
    if (latency.kind !== 'plain') throw new Error('expected a plain row')
    const [foundry, workers] = partial.results
    expect(latency.cells).toEqual([
      `${formatCount(Math.round(foundry.latency_ms ?? 0))} ms`,
      `${formatCount(Math.round(workers.latency_ms ?? 0))} ms`,
      null,
    ])
    const cost = find(rows, 'cost')
    if (cost.kind !== 'plain') throw new Error('expected a plain row')
    // Foundry's price isn't known yet, and the Ollama target failed.
    expect(cost.cells).toEqual(['Unknown', formatUsd(workers.cost_usd ?? 0), null])
  })

  it('adds a row for an option the question does not have', () => {
    const result = structuredClone(partial.results[0])
    const intent = result.answers.intent
    if (intent.type !== 'choice') throw new Error('intent should be a choice')
    intent.choice = 'flee'
    intent.unknown_probabilities = { flee: 0.6 }
    const withUnknown = buildMatrix(partial.request, columnsOf([result]))
    const row = find(withUnknown, 'intent:unknown:flee')
    if (row.kind !== 'heat') throw new Error('expected a heat row')
    expect(row.sub).toBe('Not an option')
    expect(row.cells).toEqual([{ value: 0.6, picked: true }])
  })

  it('shows a missing score probability as empty', () => {
    const result = structuredClone(partial.results[0])
    const reaction = result.answers.reaction
    if (reaction.type !== 'score') throw new Error('reaction should be a score')
    reaction.probabilities[4] = null
    const row = find(buildMatrix(partial.request, columnsOf([result])), 'reaction:4')
    if (row.kind !== 'heat') throw new Error('expected a heat row')
    expect(row.cells[0].value).toBeNull()
  })

  it('marks a low score confidence', () => {
    const result = structuredClone(partial.results[0])
    const reaction = result.answers.reaction
    if (reaction.type !== 'score') throw new Error('reaction should be a score')
    reaction.server_confidence = 0.02
    const row = find(buildMatrix(partial.request, columnsOf([result])), 'reaction:confidence')
    if (row.kind !== 'plain') throw new Error('expected a plain row')
    expect(row.cells).toEqual(['0.020'])
    expect(row.warn).toEqual([true])
  })
})
