import { describe, expect, it } from 'vitest'

import type { DecideResponse, SuiteDetail } from '../api/types'
import { fixture } from '../test/fixtures'
import { buildCase, nextCaseId, parseTags, unmatchedQuestions } from './case'

const asked = fixture<DecideResponse>('post_decide.json').request
const suite = fixture<SuiteDetail>('get_suites_{name}.json')

describe('nextCaseId', () => {
  it('skips ids the suite has', () => {
    expect(nextCaseId(['a', 'b'])).toBe('case-3')
    expect(nextCaseId(['case-2', 'case-3'])).toBe('case-4')
  })
})

describe('unmatchedQuestions', () => {
  it('matches the parley request to the parley question set', () => {
    expect(unmatchedQuestions(asked, suite.question_set)).toEqual([])
  })

  it('names questions that are missing or answered differently', () => {
    const changed = structuredClone(asked)
    changed.questions.extra = { type: 'noul', instructions: 'Extra?', criteria: null }
    const intent = changed.questions.intent
    if (intent.type !== 'choice') throw new Error('intent should be a choice')
    intent.criteria = { parley: 'Talk', fight: 'Attack' }
    changed.questions.bribe = { ...changed.questions.bribe, instructions: 'Reworded?' }
    expect(unmatchedQuestions(changed, suite.question_set)).toEqual(['intent', 'extra'])
  })
})

describe('parseTags', () => {
  it('splits on commas and drops blanks and repeats', () => {
    expect(parseTags(' bribe, goblins,, bribe ')).toEqual(['bribe', 'goblins'])
  })
})

describe('buildCase', () => {
  it('builds a human case with each expectation the suite can check', () => {
    expect(
      buildCase({
        id: ' goblin-silver ',
        state: 'Goblins',
        tags: ['bribe'],
        expected: { intent: 'parley', bribe: true, reaction: 3 },
        tolerance: { reaction: 1 },
        skip: ['bribe'],
      }),
    ).toEqual({
      id: 'goblin-silver',
      state: 'Goblins',
      tags: ['bribe'],
      provenance: 'human',
      expected: {
        intent: { answer: 'parley', tolerance: 0 },
        reaction: { answer: 3, tolerance: 1 },
      },
    })
  })
})
