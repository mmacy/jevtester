import { describe, expect, it } from 'vitest'

import { cliCommand, shellQuote } from './cli-command'

describe('shellQuote', () => {
  it('leaves plain words alone and single-quotes the rest', () => {
    expect(shellQuote('decision-1@foundry')).toBe('decision-1@foundry')
    expect(shellQuote('Six goblins.')).toBe("'Six goblins.'")
    expect(shellQuote("The goblins' leader")).toBe(`'The goblins'\\'' leader'`)
  })

  it('round-trips a quote', () => {
    expect(shellQuote("it's")).toBe(`'it'\\''s'`)
  })
})

describe('cliCommand', () => {
  it('uses flags for a text state and one question', () => {
    const command = cliCommand(
      {
        state: 'Six goblins block the stairs.',
        questions: { question: { type: 'noul', instructions: 'Are the goblins hostile?' } },
      },
      [],
    )
    expect(command).toBe(
      [
        'uv run jevtester decide',
        "--state 'Six goblins block the stairs.'",
        "--question 'Are the goblins hostile?'",
        '--format json',
      ].join(' \\\n  '),
    )
  })

  it('adds the id, options, levels, and targets', () => {
    const choice = cliCommand(
      {
        state: 'Goblins',
        questions: {
          intent: {
            type: 'choice',
            instructions: 'What is the player trying to do?',
            criteria: { parley: 'Talk, bargain', fight: 'Attack' },
          },
        },
      },
      ['decision-1@foundry', 'clef-flash@workers-ai'],
    )
    expect(choice).toContain('--id intent')
    expect(choice).toContain("--option 'parley=Talk, bargain' \\\n  --option fight=Attack")
    expect(choice).toContain('--target decision-1@foundry \\\n  --target clef-flash@workers-ai')

    const score = cliCommand(
      {
        state: 'Goblins',
        questions: { q1: { type: 'score', instructions: 'React?', criteria: ['Attack', 'Flee'] } },
      },
      [],
    )
    expect(score).toContain('--level Attack \\\n  --level Flee')
  })

  it('sends anything else as JSON on stdin', () => {
    const body = {
      state: { party: 'Three' },
      questions: {
        bribe: { type: 'noul' as const, instructions: 'Bribe?' },
        intent: { type: 'choice' as const, instructions: 'Intent?', criteria: { a: 'A', b: 'B' } },
      },
    }
    const command = cliCommand(body, ['decision-1@foundry'])
    const [first, ...rest] = command.split('\n')
    expect(first).toBe(
      "uv run jevtester decide --request - --target decision-1@foundry --format json <<'JSON'",
    )
    expect(rest.at(-1)).toBe('JSON')
    expect(JSON.parse(rest.slice(0, -1).join('\n'))).toEqual(body)
  })
})
