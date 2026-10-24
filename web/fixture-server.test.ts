import { describe, expect, it } from 'vitest'

import { matchFixture, splitEvents } from './fixture-server.ts'

const FILES = [
  'get_targets.json',
  'post_targets_check.json',
  'post_decide.json',
  'get_runs.json',
  'get_runs_{id}.json',
  'get_runs_0142.json',
  'get_runs_{id}_events.sse',
  'get_question-sets_{name}_diff.json',
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

describe('splitEvents', () => {
  it('splits on blank lines and drops empty blocks', () => {
    const text = 'event: progress\ndata: {"sent": 1}\n\n\nevent: finished\r\ndata: {}\r\n\r\n'
    expect(splitEvents(text)).toEqual([
      'event: progress\ndata: {"sent": 1}',
      'event: finished\ndata: {}',
    ])
  })
})
