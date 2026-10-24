import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DecideResponse } from '../api/types'
import { newQuestion } from '../lib/request'
import { fixture } from '../test/fixtures'
import { stubApi } from '../test/stub-api'
import { useCompare } from './compare'
import { useTargets } from './targets'

const partial = fixture<DecideResponse>('post_decide.partial.json')

function reset() {
  useTargets.setState({ defaultTargets: ['decision-1@foundry'] })
  const q = newQuestion('bribe')
  q.instructions = 'Does the player offer the monsters something of value?'
  useCompare.setState({
    mode: 'quick',
    draft: { stateMode: 'text', stateText: 'Six goblins.', questions: [q] },
    targets: [],
    asked: null,
    asking: false,
    askError: null,
  })
}

function bodyOf(call: unknown[]) {
  return JSON.parse((call[1] as RequestInit).body as string) as { targets: string[] }
}

describe('compare store', () => {
  beforeEach(reset)
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends a quick test to the default targets', async () => {
    const fetchMock = stubApi({ 'POST /api/decide': { body: fixture('post_decide.json') } })
    await useCompare.getState().ask()
    expect(fetchMock.mock.calls.map((c) => bodyOf(c).targets)).toEqual([['decision-1@foundry']])
    const { asked } = useCompare.getState()
    expect(asked?.columns.map((c) => [c.target, c.state])).toEqual([['decision-1@foundry', 'ok']])
    expect(asked?.askedAt).toBe(fixture<DecideResponse>('post_decide.json').asked_at)
  })

  it('checks the default targets when the full request opens', () => {
    useCompare.getState().setMode('full')
    expect(useCompare.getState().targets).toEqual(['decision-1@foundry'])
  })

  it('sends a full request once per target and places each result in its column', async () => {
    useCompare.setState({ mode: 'full', targets: partial.results.map((r) => r.target) })
    const fetchMock = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const { targets } = JSON.parse(init?.body as string) as { targets: string[] }
      const results = partial.results.filter((r) => r.target === targets[0])
      return new Response(JSON.stringify({ ...partial, results }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)
    await useCompare.getState().ask()
    expect(fetchMock.mock.calls.map((c) => bodyOf(c).targets)).toEqual(
      partial.results.map((r) => [r.target]),
    )
    const columns = useCompare.getState().asked?.columns ?? []
    expect(columns.map((c) => [c.target, c.state])).toEqual([
      ['decision-1@foundry', 'ok'],
      ['clef-flash@workers-ai', 'ok'],
      ['clef-flash@ollama', 'failed'],
    ])
  })

  it('fails only the column of a target the server rejects', async () => {
    useCompare.setState({ mode: 'full', targets: ['clef@nowhere'] })
    stubApi({ 'POST /api/decide': { status: 422, body: fixture('post_decide.422.json') } })
    await useCompare.getState().ask()
    const { askError, asked } = useCompare.getState()
    expect(askError).toBeNull()
    expect(asked?.columns[0]).toMatchObject({
      state: 'failed',
      error: { code: 'invalid_request', message: 'Unknown target: clef@nowhere' },
    })
  })

  it('keeps a request error that is about the questions', async () => {
    useCompare.setState({ mode: 'full', targets: ['decision-1@foundry'] })
    const error = {
      code: 'invalid_request',
      message: 'Too few options',
      field: 'questions.intent.choice.criteria',
      details: [{ field: 'questions.intent.choice.criteria', message: 'Too few options' }],
    }
    stubApi({ 'POST /api/decide': { status: 422, body: { error } } })
    await useCompare.getState().ask()
    expect(useCompare.getState().askError).toMatchObject({
      field: 'questions.intent.choice.criteria',
    })
  })

  it('lets the server pick when the default targets have not loaded', async () => {
    useTargets.setState({ defaultTargets: [] })
    const fetchMock = stubApi({ 'POST /api/decide': { body: fixture('post_decide.json') } })
    await useCompare.getState().ask()
    expect(fetchMock.mock.calls.map((c) => bodyOf(c).targets)).toEqual([[]])
    expect(useCompare.getState().asked?.columns.map((c) => c.target)).toEqual([
      'decision-1@foundry',
    ])
  })
})
