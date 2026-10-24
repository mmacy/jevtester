import { describe, expect, it } from 'vitest'

import {
  fixtureStatus,
  matchFixture,
  parseFixtureName,
  pickDecideResults,
  splitEvents,
} from './fixture-server.ts'

const FILES = [
  'get_targets.json',
  'post_targets_check.json',
  'post_decide.json',
  'get_runs.json',
  'get_runs_{id}.json',
  'get_runs_0142.json',
  'get_runs_{id}_events.sse',
  'get_question-sets_{name}_diff.json',
  'get_runs_{id}_cases_{case_id}.json',
  'post_decide.partial.json',
  'post_decide.422.json',
  'README.md',
]

describe('matchFixture', () => {
  it('matches by method and path', () => {
    expect(matchFixture('GET', '/api/targets', FILES)).toBe('get_targets.json')
    expect(matchFixture('POST', '/api/targets/check', FILES)).toBe('post_targets_check.json')
    expect(matchFixture('post', '/api/decide', FILES)).toBe('post_decide.json')
  })

  it('fills a placeholder with any one segment', () => {
    expect(matchFixture('GET', '/api/runs/0007', FILES)).toBe('get_runs_{id}.json')
    expect(matchFixture('GET', '/api/runs/0007/events', FILES)).toBe('get_runs_{id}_events.sse')
    expect(matchFixture('GET', '/api/question-sets/parley/diff', FILES)).toBe(
      'get_question-sets_{name}_diff.json',
    )
  })

  it('matches a placeholder whose name has an underscore', () => {
    expect(matchFixture('GET', '/api/runs/0142/cases/parley-07', FILES)).toBe(
      'get_runs_{id}_cases_{case_id}.json',
    )
  })

  it('lets a segment value contain underscores', () => {
    expect(matchFixture('GET', '/api/runs/parley_07', FILES)).toBe('get_runs_{id}.json')
  })

  it('prefers an exact name over a placeholder', () => {
    expect(matchFixture('GET', '/api/runs/0142', FILES)).toBe('get_runs_0142.json')
  })

  it('returns null for an unknown path or method', () => {
    expect(matchFixture('GET', '/api/policies/parley', FILES)).toBeNull()
    expect(matchFixture('DELETE', '/api/targets', FILES)).toBeNull()
    expect(matchFixture('GET', '/api/runs/0142/events/extra', FILES)).toBeNull()
  })
})

describe('parseFixtureName', () => {
  it('keeps a placeholder with an underscore as one part', () => {
    expect(parseFixtureName('get_runs_{id}_cases_{case_id}.json')).toEqual({
      method: 'get',
      parts: ['runs', '{id}', 'cases', '{case_id}'],
      variant: null,
    })
  })

  it('reads a variant after the first dot', () => {
    expect(parseFixtureName('post_decide.422.json')).toEqual({
      method: 'post',
      parts: ['decide'],
      variant: '422',
    })
  })

  it('skips files that are not fixtures', () => {
    expect(parseFixtureName('README.md')).toBeNull()
  })
})

describe('variants', () => {
  it('serves a variant only when the request names it', () => {
    expect(matchFixture('POST', '/api/decide', FILES)).toBe('post_decide.json')
    expect(matchFixture('POST', '/api/decide', FILES, 'partial')).toBe('post_decide.partial.json')
    expect(matchFixture('POST', '/api/decide', FILES, '422')).toBe('post_decide.422.json')
    expect(matchFixture('POST', '/api/decide', FILES, 'missing')).toBeNull()
  })

  it('serves a numeric variant with that status', () => {
    expect(fixtureStatus('post_decide.422.json')).toBe(422)
    expect(fixtureStatus('post_decide.partial.json')).toBe(200)
    expect(fixtureStatus('post_decide.json')).toBe(200)
  })
})

describe('splitEvents', () => {
  it('splits on blank lines and drops empty blocks', () => {
    const text = 'event: progress\ndata: {"sent": 1}\n\n\nevent: finished\r\ndata: {}\r\n\r\n'
    expect(splitEvents(text)).toEqual([
      'event: progress\ndata: {"sent": 1}',
      'event: finished\ndata: {}',
    ])
  })
})

describe('pickDecideResults', () => {
  const single = { asked_at: 'x', results: [{ target: 'a', ok: true }] }
  const partial = {
    asked_at: 'y',
    results: [
      { target: 'a', ok: true },
      { target: 'b', ok: true },
    ],
  }

  it('serves the fixture as it is when no targets are named', () => {
    expect(pickDecideResults(single, [partial], [])).toBe(single)
  })

  it('answers each named target from any decide fixture', () => {
    expect(pickDecideResults(single, [partial], ['b']).results).toEqual([{ target: 'b', ok: true }])
    expect(pickDecideResults(single, [partial], ['b']).asked_at).toBe('x')
  })

  it('fails a target no fixture has', () => {
    expect(pickDecideResults(single, [partial], ['c']).results[0]).toMatchObject({
      target: 'c',
      ok: false,
      error: { code: 'not_ready' },
    })
  })
})
