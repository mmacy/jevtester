// A word-by-word diff, for showing what changed in a question's wording.

export interface DiffPart {
  text: string
  kind: 'same' | 'added' | 'removed'
}

function words(text: string): string[] {
  // Keep the spaces as their own tokens, so joining the parts restores the text.
  return text.split(/(\s+)/).filter((t) => t !== '')
}

/** The parts of `before` and `after`, in order, using the longest common run of words. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = words(before)
  const b = words(after)
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  )
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const parts: DiffPart[] = []
  const push = (text: string, kind: DiffPart['kind']) => {
    const last = parts.at(-1)
    if (last?.kind === kind) last.text += text
    else parts.push({ text, kind })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push(a[i], 'same')
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push(a[i++], 'removed')
    } else {
      push(b[j++], 'added')
    }
  }
  while (i < a.length) push(a[i++], 'removed')
  while (j < b.length) push(b[j++], 'added')
  return parts
}
