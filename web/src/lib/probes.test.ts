import { describe, expect, it } from 'vitest'

import type { ProbeReport } from '../api/types'
import { fixture } from '../test/fixtures'
import { cellKey, probeGrid } from './probes'

const report = fixture<ProbeReport>('get_runs_{id}_probes.json')

describe('probeGrid', () => {
  it('has a row per case and a column per target and variant', () => {
    const grid = probeGrid(report)
    expect(grid.variants).toEqual(report.variants)
    expect(grid.cases).toEqual([...new Set(report.cells.map((c) => c.case_id))])
    const first = report.cells[0]
    expect(grid.cells.get(cellKey(first.case_id, first.target, first.variant))).toEqual({
      changed: first.changed,
      instances: first.instances,
      rate: first.change_rate,
    })
    const s = report.summary[0]
    expect(grid.summary.get(`${s.target}|${s.variant}`)).toBe(s.change_rate)
  })
})
