// Display rules for runs: duration, progress, and the metrics grid.
import type {
  QuestionMetrics,
  QuestionType,
  RunCounts,
  RunStatus,
  TargetMetrics,
} from '../api/types'
import { formatCount, formatUsd } from './format'

export function isActive(status: RunStatus): boolean {
  return status === 'queued' || status === 'running'
}

/** The time between two instants, like `4 m 05 s`. */
export function formatDuration(startIso: string, endIso: string): string {
  const seconds = Math.max(0, Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  if (h > 0) return `${h} h ${pad(m)} m`
  if (m > 0) return `${m} m ${pad(s)} s`
  return `${s} s`
}

export type SegmentKind = 'sent' | 'cached' | 'failed' | 'skipped'

export interface ProgressSegment {
  kind: SegmentKind
  count: number
  /** The share of all jobs, from 0 to 1. */
  share: number
  label: string
}

/** The progress bar's segments, in order, leaving out the empty ones. */
export function progressSegments(counts: RunCounts): ProgressSegment[] {
  const share = (n: number) => (counts.jobs > 0 ? n / counts.jobs : 0)
  const skippedOn = counts.targets.filter((t) => t.skipped > 0).map((t) => t.target)
  const segments: ProgressSegment[] = [
    { kind: 'sent', count: counts.sent, share: share(counts.sent), label: `${counts.sent} sent` },
    {
      kind: 'cached',
      count: counts.cached,
      share: share(counts.cached),
      label: `${counts.cached} from cache`,
    },
    {
      kind: 'failed',
      count: counts.failed,
      share: share(counts.failed),
      label: `${counts.failed} failed`,
    },
    {
      kind: 'skipped',
      count: counts.skipped,
      share: share(counts.skipped),
      label: `${counts.skipped} skipped${skippedOn.length ? ` on ${skippedOn.join(', ')}` : ''}`,
    },
  ]
  return segments.filter((s) => s.count > 0)
}

export interface MetricColumn {
  label: string
  higherBetter: boolean
  /** What a cell reads when its value is null. */
  missing: string
  value: (target: TargetMetrics, question: QuestionMetrics | undefined) => number | null
  format: (value: number) => string
}

const ratio = (v: number) => v.toFixed(3)
const ms = (v: number) => `${formatCount(Math.round(v))} ms`

const quality = (
  label: string,
  key: keyof QuestionMetrics,
  higherBetter: boolean,
  format: (v: number) => string = ratio,
): MetricColumn => ({
  label,
  higherBetter,
  missing: 'None',
  value: (_t, q) => (q ? (q[key] as number | null) : null),
  format,
})

const QUALITY: Record<QuestionType, MetricColumn[]> = {
  choice: [
    quality('Accuracy', 'accuracy', true),
    quality('Macro-F1', 'macro_f1', true),
    quality('Calibration error', 'ece', false),
    quality('Abstention', 'abstention_rate', false),
    quality('Consistency', 'consistency', true),
  ],
  noul: [
    quality('Accuracy', 'accuracy', true),
    quality('Brier score', 'brier', false),
    quality('Log loss', 'log_loss', false),
    quality('AUROC', 'auroc', true),
    quality('Calibration error', 'ece', false),
    quality('Consistency', 'consistency', true),
  ],
  score: [
    quality('Accuracy', 'accuracy', true),
    quality('Within tolerance', 'within_tolerance', true),
    quality('Mean absolute error', 'mae', false, (v) => v.toFixed(2)),
    quality('Consistency', 'consistency', true),
  ],
}

const SPEED: MetricColumn[] = [
  {
    label: 'p50 latency',
    higherBetter: false,
    missing: 'None',
    value: (t) => t.latency_p50_ms,
    format: ms,
  },
  {
    label: 'p95 latency',
    higherBetter: false,
    missing: 'None',
    value: (t) => t.latency_p95_ms,
    format: ms,
  },
  {
    label: 'Cost per 1,000',
    higherBetter: false,
    missing: 'Unknown',
    value: (t) => t.cost_per_1k_usd,
    format: formatUsd,
  },
]

/** The grid's columns for a question type: those any target has a value for, then speed and cost. */
export function metricColumns(
  type: QuestionType,
  targets: TargetMetrics[],
  question: string,
): MetricColumn[] {
  const shown = (column: MetricColumn) =>
    targets.some(
      (t) =>
        column.value(
          t,
          t.questions.find((q) => q.question === question),
        ) !== null,
    )
  return [...QUALITY[type].filter(shown), ...SPEED]
}

/**
 * How good a value is among the targets, as a heat ramp position from 0.12
 * to 0.87, so the best target is brightest. Null when there's no value.
 */
export function rankShade(
  values: readonly (number | null)[],
  value: number | null,
  higherBetter: boolean,
) {
  if (value === null) return null
  const present = values.filter((v): v is number => v !== null)
  const lo = Math.min(...present)
  const hi = Math.max(...present)
  let q = hi === lo ? 1 : (value - lo) / (hi - lo)
  if (!higherBetter) q = 1 - q
  return 0.12 + q * 0.75
}
