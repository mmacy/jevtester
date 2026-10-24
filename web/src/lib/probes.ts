import type { ProbeReport, ProbeVariant } from '../api/types'

export const VARIANT_LABELS: Record<ProbeVariant, string> = {
  option_order: 'Option order',
  key_order: 'JSON key order',
  bare_levels: 'Bare-number levels',
  pad_state: 'State padding',
}

export interface ProbeCellView {
  changed: number
  instances: number
  rate: number | null
}

export interface ProbeGridModel {
  targets: string[]
  variants: ProbeVariant[]
  cases: string[]
  /** Keyed by `case|target|variant`. */
  cells: Map<string, ProbeCellView>
  /** Keyed by `target|variant`. */
  summary: Map<string, number | null>
}

export const cellKey = (caseId: string, target: string, variant: string) =>
  `${caseId}|${target}|${variant}`

/** The probe report as a grid: cases as rows, and a column for each target and variant. */
export function probeGrid(report: ProbeReport): ProbeGridModel {
  const targets = [
    ...new Set([...report.summary.map((s) => s.target), ...report.cells.map((c) => c.target)]),
  ]
  const cases = [...new Set(report.cells.map((c) => c.case_id))]
  const cells = new Map<string, ProbeCellView>()
  for (const c of report.cells) {
    cells.set(cellKey(c.case_id, c.target, c.variant), {
      changed: c.changed,
      instances: c.instances,
      rate: c.change_rate,
    })
  }
  const summary = new Map<string, number | null>()
  for (const s of report.summary) summary.set(`${s.target}|${s.variant}`, s.change_rate)
  return { targets, variants: report.variants, cases, cells, summary }
}
