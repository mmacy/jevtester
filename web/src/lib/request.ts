// The request a person edits in Compare, and how it becomes a decide body.
import type { DecisionRequest, QuestionInput, QuestionOutput, State } from '../api/types'

export type QuestionType = QuestionInput['type']
export type StateMode = 'text' | 'json'

export interface OptionDraft {
  name: string
  description: string
}

export interface QuestionDraft {
  /** A stable key for React, separate from the id the person edits. */
  key: string
  id: string
  type: QuestionType
  instructions: string
  /** Choice options. Kept when the type changes, so changing back restores them. */
  options: OptionDraft[]
  /** Score levels, lowest first. */
  levels: string[]
}

export interface RequestDraft {
  stateMode: StateMode
  stateText: string
  questions: QuestionDraft[]
}

let nextKey = 0

export function newQuestion(id: string, type: QuestionType = 'noul'): QuestionDraft {
  nextKey += 1
  return { key: `q${nextKey}`, id, type, instructions: '', options: [], levels: [] }
}

/** The first id like `q1`, `q2` that no question has. */
export function nextQuestionId(questions: readonly QuestionDraft[]): string {
  const taken = new Set(questions.map((q) => q.id))
  let n = 1
  while (taken.has(`q${n}`)) n++
  return `q${n}`
}

export interface DraftErrors {
  state?: string
  /** Keyed by question key. */
  questions: Record<string, string[]>
}

export function hasErrors(errors: DraftErrors): boolean {
  return errors.state !== undefined || Object.keys(errors.questions).length > 0
}

export function parseState(mode: StateMode, text: string): { state: State } | { error: string } {
  if (text.trim() === '') return { error: 'State is empty' }
  if (mode === 'text') return { state: text }
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null)
      return { error: 'State must be a JSON object or array' }
    return { state: parsed as State }
  } catch (error) {
    return { error: `Invalid JSON: ${(error as Error).message}` }
  }
}

function questionErrors(question: QuestionDraft, ids: string[]): string[] {
  const errors: string[] = []
  const id = question.id.trim()
  if (id === '') errors.push('Id is empty')
  else if (ids.filter((other) => other === id).length > 1) errors.push(`Id ${id} is used twice`)
  if (question.instructions.trim() === '') errors.push('Question is empty')
  if (question.type === 'choice') {
    const names = question.options.map((o) => o.name.trim())
    if (names.length < 2) errors.push('Needs at least 2 options')
    if (names.some((n) => n === '')) errors.push('An option has no name')
    if (new Set(names).size !== names.length) errors.push('Option names repeat')
  }
  if (question.type === 'score') {
    if (question.levels.length < 2) errors.push('Needs at least 2 levels')
    if (question.levels.some((l) => l.trim() === '')) errors.push('A level is empty')
  }
  return errors
}

export function validateDraft(draft: RequestDraft): DraftErrors {
  const errors: DraftErrors = { questions: {} }
  const parsed = parseState(draft.stateMode, draft.stateText)
  if ('error' in parsed) errors.state = parsed.error
  if (draft.questions.length === 0) errors.questions[''] = ['Needs at least 1 question']
  const ids = draft.questions.map((q) => q.id.trim())
  for (const question of draft.questions) {
    const found = questionErrors(question, ids)
    if (found.length > 0) errors.questions[question.key] = found
  }
  return errors
}

function toQuestion(draft: QuestionDraft): QuestionInput {
  const instructions = draft.instructions.trim()
  switch (draft.type) {
    case 'noul':
      return { type: 'noul', instructions }
    case 'choice':
      return {
        type: 'choice',
        instructions,
        criteria: Object.fromEntries(
          draft.options.map((o) => [o.name.trim(), o.description.trim()]),
        ),
      }
    case 'score':
      return { type: 'score', instructions, criteria: draft.levels.map((l) => l.trim()) }
  }
}

/** The state and questions of a decide body. */
export interface RequestBody {
  state: State
  questions: Record<string, QuestionInput>
}

/** The state and questions to send. Call only on a draft with no errors. */
export function toRequest(draft: RequestDraft): RequestBody {
  const parsed = parseState(draft.stateMode, draft.stateText)
  if ('error' in parsed) throw new Error(parsed.error)
  return {
    state: parsed.state,
    questions: Object.fromEntries(draft.questions.map((q) => [q.id.trim(), toQuestion(q)])),
  }
}

/** The request as the API echoes it, to label the matrix before any answer arrives. */
export function asEchoed(request: RequestBody): DecisionRequest {
  const questions: Record<string, QuestionOutput> = {}
  for (const [id, q] of Object.entries(request.questions)) {
    questions[id] =
      q.type === 'noul' ? { type: 'noul', instructions: q.instructions, criteria: null } : q
  }
  return { state: request.state, questions, images: [] }
}

/** A draft fits the quick test when it has one yes-or-no question. */
export function fitsQuickTest(draft: RequestDraft, targetCount: number): boolean {
  return (
    draft.stateMode === 'text' &&
    draft.questions.length === 1 &&
    draft.questions[0].type === 'noul' &&
    targetCount <= 1
  )
}
