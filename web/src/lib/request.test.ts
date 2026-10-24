import { describe, expect, it } from 'vitest'

import {
  asEchoed,
  fitsQuickTest,
  hasErrors,
  newQuestion,
  nextQuestionId,
  parseState,
  toRequest,
  validateDraft,
  type RequestDraft,
} from './request'

function draft(overrides: Partial<RequestDraft> = {}): RequestDraft {
  const q = newQuestion('q1')
  q.instructions = 'Are the goblins hostile?'
  return {
    stateMode: 'text',
    stateText: 'Six goblins block the stairs.',
    questions: [q],
    ...overrides,
  }
}

describe('parseState', () => {
  it('keeps text as is', () => {
    expect(parseState('text', 'Goblins')).toEqual({ state: 'Goblins' })
  })

  it('parses a JSON object or array', () => {
    expect(parseState('json', '{"party": "Three"}')).toEqual({ state: { party: 'Three' } })
    expect(parseState('json', '[1, 2]')).toEqual({ state: [1, 2] })
  })

  it('rejects empty text, bad JSON, and JSON scalars', () => {
    expect(parseState('text', '  ')).toEqual({ error: 'State is empty' })
    expect(parseState('json', '{party')).toMatchObject({
      error: expect.stringMatching(/^Invalid JSON/),
    })
    expect(parseState('json', '"text"')).toEqual({ error: 'State must be a JSON object or array' })
  })
})

describe('validateDraft', () => {
  it('passes a quick test', () => {
    expect(hasErrors(validateDraft(draft()))).toBe(false)
  })

  it('finds each problem with a question', () => {
    const choice = newQuestion('intent', 'choice')
    choice.options = [{ name: 'parley', description: '' }]
    const score = newQuestion('intent', 'score')
    score.instructions = 'How do they react?'
    score.levels = ['Attack', '']
    const errors = validateDraft(draft({ questions: [choice, score] }))
    expect(errors.questions[choice.key]).toEqual([
      'Id intent is used twice',
      'Question is empty',
      'Needs at least 2 options',
    ])
    expect(errors.questions[score.key]).toEqual(['Id intent is used twice', 'A level is empty'])
  })

  it('needs a question', () => {
    expect(validateDraft(draft({ questions: [] })).questions['']).toEqual([
      'Needs at least 1 question',
    ])
  })
})

describe('toRequest', () => {
  it('builds each question type in order', () => {
    const intent = newQuestion('intent', 'choice')
    intent.instructions = 'What is the player trying to do?'
    intent.options = [
      { name: 'parley', description: 'Talk' },
      { name: 'fight', description: 'Attack' },
    ]
    const reaction = newQuestion('reaction', 'score')
    reaction.instructions = 'How do they react?'
    reaction.levels = ['Attack at once', 'Friendly']
    const body = toRequest(
      draft({
        stateMode: 'json',
        stateText: '{"party": "Three"}',
        questions: [intent, ...draft().questions, reaction],
      }),
    )
    expect(body).toEqual({
      state: { party: 'Three' },
      questions: {
        intent: {
          type: 'choice',
          instructions: 'What is the player trying to do?',
          criteria: { parley: 'Talk', fight: 'Attack' },
        },
        q1: { type: 'noul', instructions: 'Are the goblins hostile?' },
        reaction: {
          type: 'score',
          instructions: 'How do they react?',
          criteria: ['Attack at once', 'Friendly'],
        },
      },
    })
    expect(Object.keys(body.questions)).toEqual(['intent', 'q1', 'reaction'])
    expect(asEchoed(body).questions.q1).toEqual({
      type: 'noul',
      instructions: 'Are the goblins hostile?',
      criteria: null,
    })
  })
})

describe('nextQuestionId', () => {
  it('skips ids in use', () => {
    expect(nextQuestionId([newQuestion('q1'), newQuestion('q3')])).toBe('q2')
  })
})

describe('fitsQuickTest', () => {
  it('fits one yes-or-no question on one target', () => {
    expect(fitsQuickTest(draft(), 1)).toBe(true)
    expect(fitsQuickTest(draft(), 2)).toBe(false)
    expect(fitsQuickTest(draft({ stateMode: 'json' }), 1)).toBe(false)
    expect(fitsQuickTest(draft({ questions: [newQuestion('a', 'choice')] }), 1)).toBe(false)
  })
})
