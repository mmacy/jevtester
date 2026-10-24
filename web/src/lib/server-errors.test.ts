import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { serverErrors } from './server-errors'

function rejected(fields: (string | null)[]) {
  return new ApiError(422, {
    code: 'invalid_request',
    message: 'Invalid',
    field: fields[0],
    details: fields.map((field) => ({ field, message: `bad ${field}` })),
  })
}

describe('serverErrors', () => {
  it('puts each error on the question its path names', () => {
    const errors = serverErrors(rejected(['questions.reaction.score.criteria', 'name', null]), [
      'intent',
      'reaction',
    ])
    expect(errors).toEqual({
      reaction: ['bad questions.reaction.score.criteria'],
      '': ['bad name', 'bad null'],
    })
  })

  it('matches an id that has a dot in it', () => {
    const errors = serverErrors(rejected(['questions.a.b.choice.criteria', 'questions.a.noul']), [
      'a',
      'a.b',
    ])
    expect(errors).toEqual({
      'a.b': ['bad questions.a.b.choice.criteria'],
      a: ['bad questions.a.noul'],
    })
  })
})
