// The answers matrix as data: one column per target, and rows for each
// question's options or levels, its confidence, and the speed and cost of
// each request. The component only draws what this returns.
import type { Answer, DecisionRequest, QuestionOutput, TargetResult } from '../api/types'
import { formatCount, formatUsd } from './format'

export type ColumnState = 'pending' | 'ok' | 'failed'

export interface MatrixColumn {
  target: string
  state: ColumnState
  result: TargetResult | null
  /** Why a failed call returned no result, when the request itself failed. */
  error?: { code: string; message: string } | null
}

export interface HeatValue {
  value: number | null
  picked: boolean
}

export type MatrixRow =
  | { kind: 'group'; key: string; id: string; instructions: string; type: string }
  | {
      kind: 'heat'
      key: string
      label: string
      sub: string | null
      digits: number
      cells: HeatValue[]
      spread: number | null
    }
  | { kind: 'score'; key: string; levels: number; cells: (number | null)[]; spread: number | null }
  | { kind: 'plain'; key: string; label: string; cells: (string | null)[]; warn: boolean[] }

// A spread at or above this shows in amber: the targets disagree.
export const SPREAD_ALERT = 0.05

// A score confidence below this shows in amber.
export const LOW_SCORE_CONFIDENCE = 0.1

/** Max minus min of the values present, or null with fewer than two. */
export function spread(values: readonly (number | null)[]): number | null {
  const present = values.filter((v): v is number => v !== null)
  if (present.length < 2) return null
  return Math.max(...present) - Math.min(...present)
}

export function typeLabel(question: QuestionOutput): string {
  switch (question.type) {
    case 'noul':
      return 'Yes or no'
    case 'choice':
      return 'Choice'
    case 'score':
      return `Score, ${question.criteria.length} levels`
  }
}

function answerOf<T extends Answer['type']>(
  column: MatrixColumn,
  id: string,
  type: T,
): Extract<Answer, { type: T }> | null {
  if (column.state !== 'ok' || !column.result) return null
  const answer = column.result.answers[id]
  return answer?.type === type ? (answer as Extract<Answer, { type: T }>) : null
}

function heatRow(
  key: string,
  label: string,
  sub: string | null,
  digits: number,
  cells: HeatValue[],
): MatrixRow {
  return { kind: 'heat', key, label, sub, digits, cells, spread: spread(cells.map((c) => c.value)) }
}

function plainRow(
  key: string,
  label: string,
  cells: (string | null)[],
  warn?: boolean[],
): MatrixRow {
  return { kind: 'plain', key, label, cells, warn: warn ?? cells.map(() => false) }
}

function choiceRows(
  id: string,
  question: Extract<QuestionOutput, { type: 'choice' }>,
  columns: MatrixColumn[],
) {
  const rows: MatrixRow[] = []
  const answers = columns.map((c) => answerOf(c, id, 'choice'))
  const options = Object.entries(question.criteria)
  for (const [option, description] of options) {
    rows.push(
      heatRow(
        `${id}:${option}`,
        option,
        description,
        4,
        answers.map((a) => ({
          value: a?.probabilities[option] ?? null,
          picked: a?.choice === option,
        })),
      ),
    )
  }
  // An option the question doesn't have, which some target chose or scored.
  const unknown = new Set<string>()
  for (const a of answers) {
    if (!a) continue
    if (!(a.choice in question.criteria)) unknown.add(a.choice)
    for (const option of Object.keys(a.unknown_probabilities)) unknown.add(option)
  }
  for (const option of unknown) {
    rows.push(
      heatRow(
        `${id}:unknown:${option}`,
        option,
        'Not an option',
        4,
        answers.map((a) => ({
          value: a?.unknown_probabilities[option] ?? null,
          picked: a?.choice === option,
        })),
      ),
    )
  }
  rows.push(
    plainRow(
      `${id}:confidence`,
      'Confidence',
      answers.map((a) => a?.confidence.toFixed(4) ?? null),
    ),
  )
  return rows
}

function noulRows(id: string, columns: MatrixColumn[]) {
  const answers = columns.map((c) => answerOf(c, id, 'noul'))
  return [
    heatRow(
      `${id}:yes`,
      'Yes',
      'Probability of yes',
      4,
      answers.map((a) => ({
        value: a?.probability ?? null,
        picked: a !== null && a.probability >= 0.5,
      })),
    ),
    plainRow(
      `${id}:confidence`,
      'Confidence',
      answers.map((a) => a?.confidence.toFixed(4) ?? null),
    ),
  ]
}

function scoreRows(
  id: string,
  question: Extract<QuestionOutput, { type: 'score' }>,
  columns: MatrixColumn[],
) {
  const answers = columns.map((c) => answerOf(c, id, 'score'))
  const rows: MatrixRow[] = question.criteria.map((level, i) =>
    heatRow(
      `${id}:${i}`,
      String(i),
      level,
      3,
      answers.map((a) => ({ value: a?.probabilities[i] ?? null, picked: a?.level === i })),
    ),
  )
  const scores = answers.map((a) => a?.score ?? null)
  rows.push({
    kind: 'score',
    key: `${id}:score`,
    levels: question.criteria.length,
    cells: scores,
    spread: spread(scores),
  })
  const confidence = answers.map((a) => a?.confidence ?? a?.server_confidence ?? null)
  rows.push(
    plainRow(
      `${id}:confidence`,
      'Confidence',
      confidence.map((c) => c?.toFixed(3) ?? null),
      confidence.map((c) => c !== null && c < LOW_SCORE_CONFIDENCE),
    ),
  )
  return rows
}

function usageRows(columns: MatrixColumn[], isLocal: (target: string) => boolean): MatrixRow[] {
  const results = columns.map((c) => (c.state === 'ok' ? c.result : null))
  return [
    { kind: 'group', key: 'usage', id: 'usage', instructions: 'Speed and cost', type: '' },
    plainRow(
      'latency',
      'Latency',
      results.map((r) =>
        r?.latency_ms == null ? null : `${formatCount(Math.round(r.latency_ms))} ms`,
      ),
    ),
    plainRow(
      'input',
      'Input tokens',
      results.map((r) => (r ? (r.usage.input_tokens?.toString() ?? 'Unknown') : null)),
    ),
    plainRow(
      'output',
      'Output tokens',
      results.map((r) => (r ? (r.usage.output_tokens?.toString() ?? 'Unknown') : null)),
    ),
    plainRow(
      'cost',
      'Cost',
      results.map((r, i) => {
        if (!r) return null
        if (isLocal(columns[i].target)) return 'Free'
        return r.cost_usd == null ? 'Unknown' : formatUsd(r.cost_usd)
      }),
    ),
  ]
}

/** Every row of the matrix for a request, across the given columns. */
export function buildMatrix(
  request: DecisionRequest,
  columns: MatrixColumn[],
  isLocal: (target: string) => boolean = () => false,
): MatrixRow[] {
  const rows: MatrixRow[] = []
  for (const [id, question] of Object.entries(request.questions)) {
    rows.push({
      kind: 'group',
      key: `${id}:group`,
      id,
      instructions: question.instructions,
      type: typeLabel(question),
    })
    switch (question.type) {
      case 'choice':
        rows.push(...choiceRows(id, question, columns))
        break
      case 'noul':
        rows.push(...noulRows(id, columns))
        break
      case 'score':
        rows.push(...scoreRows(id, question, columns))
        break
    }
  }
  rows.push(...usageRows(columns, isLocal))
  return rows
}
