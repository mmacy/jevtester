// Turning an asked request into a case for a suite.
import type {
  AnswerValue,
  CaseInput,
  DecisionRequest,
  QuestionOutput,
  QuestionSet,
  State,
} from '../api/types'

/** The first id like `case-1`, `case-2` that the suite doesn't have. */
export function nextCaseId(existing: readonly string[]): string {
  const taken = new Set(existing)
  let n = existing.length + 1
  while (taken.has(`case-${n}`)) n++
  return `case-${n}`
}

function sameAnswers(a: QuestionOutput, b: QuestionOutput): boolean {
  if (a.type !== b.type) return false
  // A yes-or-no answer is the same whatever its criteria say.
  if (a.type === 'noul') return true
  return JSON.stringify(a.criteria) === JSON.stringify(b.criteria)
}

/**
 * The asked questions whose answers can't be checked against the suite's
 * question set: missing there, or with another type, options, or levels.
 */
export function unmatchedQuestions(asked: DecisionRequest, set: QuestionSet): string[] {
  return Object.entries(asked.questions)
    .filter(([id, question]) => {
      const theirs = set.questions[id]
      return !theirs || !sameAnswers(question, theirs)
    })
    .map(([id]) => id)
}

/** Splits comma-separated tags, dropping blanks and repeats. */
export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ]
}

export interface CaseFields {
  id: string
  state: State
  tags: string[]
  expected: Record<string, AnswerValue>
  tolerance: Record<string, number>
  /** Questions whose expectations the suite can't check, which are left out. */
  skip: readonly string[]
}

export function buildCase({ id, state, tags, expected, tolerance, skip }: CaseFields): CaseInput {
  const kept = Object.entries(expected).filter(([q]) => !skip.includes(q))
  return {
    id: id.trim(),
    state,
    tags,
    provenance: 'human',
    expected: Object.fromEntries(
      kept.map(([q, answer]) => [q, { answer, tolerance: tolerance[q] ?? 0 }]),
    ),
  }
}
