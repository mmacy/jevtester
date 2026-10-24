import { describe, expect, it } from 'vitest'

import { wordDiff } from './word-diff'

describe('wordDiff', () => {
  it('marks the words that changed', () => {
    expect(wordDiff('How do goblins react?', 'How are goblins likely to react?')).toEqual([
      { text: 'How ', kind: 'same' },
      { text: 'do', kind: 'removed' },
      { text: 'are', kind: 'added' },
      { text: ' goblins ', kind: 'same' },
      { text: 'likely to ', kind: 'added' },
      { text: 'react?', kind: 'same' },
    ])
  })

  it('rebuilds both texts from the parts', () => {
    const before = 'Talk, bargain, or bribe'
    const after = 'Talk, bargain, bribe, or negotiate'
    const parts = wordDiff(before, after)
    expect(
      parts
        .filter((p) => p.kind !== 'added')
        .map((p) => p.text)
        .join(''),
    ).toBe(before)
    expect(
      parts
        .filter((p) => p.kind !== 'removed')
        .map((p) => p.text)
        .join(''),
    ).toBe(after)
  })

  it('handles empty text', () => {
    expect(wordDiff('', 'New')).toEqual([{ text: 'New', kind: 'added' }])
    expect(wordDiff('Old', '')).toEqual([{ text: 'Old', kind: 'removed' }])
  })
})
