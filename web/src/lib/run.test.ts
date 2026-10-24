import { describe, expect, it } from 'vitest'

import type { RunMetrics, RunSummary } from '../api/types'
import { fixture } from '../test/fixtures'
import { formatDuration, metricColumns, progressSegments, rankShade } from './run'

const run = fixture<RunSummary>('get_runs_{id}.json')
const metrics = fixture<RunMetrics>('get_runs_{id}_metrics.json')

describe('formatDuration', () => {
  it('shows the two largest units', () => {
    expect(formatDuration('2026-10-24T14:00:00Z', '2026-10-24T14:00:12Z')).toBe('12 s')
    expect(formatDuration('2026-10-24T14:00:00Z', '2026-10-24T14:04:05Z')).toBe('4 m 05 s')
    expect(formatDuration('2026-10-24T14:00:00Z', '2026-10-24T15:02:30Z')).toBe('1 h 02 m')
  })
})

describe('progressSegments', () => {
  it('names each kind of job and the targets that were skipped', () => {
    const segments = progressSegments(run.counts)
    const total = segments.reduce((sum, s) => sum + s.count, 0)
    expect(total).toBe(run.counts.done)
    const skipped = segments.find((s) => s.kind === 'skipped')
    const skippedOn = run.counts.targets.filter((t) => t.skipped > 0).map((t) => t.target)
    if (skippedOn.length > 0) expect(skipped?.label).toContain(skippedOn[0])
    expect(segments.every((s) => s.count > 0)).toBe(true)
  })
})

describe('metricColumns', () => {
  it('shows the quality metrics a question type has values for, then speed and cost', () => {
    const labels = metricColumns('choice', metrics.targets, 'intent').map((c) => c.label)
    expect(labels.slice(0, 2)).toEqual(['Accuracy', 'Macro-F1'])
    expect(labels.slice(-3)).toEqual(['p50 latency', 'p95 latency', 'Cost per 1,000'])
    expect(labels).not.toContain('Brier score')
  })
})

describe('rankShade', () => {
  it('makes the best value brightest either way round', () => {
    expect(rankShade([0.9, 0.5], 0.9, true)).toBeCloseTo(0.87)
    expect(rankShade([0.9, 0.5], 0.5, true)).toBeCloseTo(0.12)
    expect(rankShade([1500, 900], 900, false)).toBeCloseTo(0.87)
    expect(rankShade([0.5], 0.5, true)).toBeCloseTo(0.87)
    expect(rankShade([0.5, null], null, true)).toBeNull()
  })
})
