import { describe, expect, it } from 'vitest'

import { formatBytes, formatCount, formatUsd, shortVersion, stateSummary } from './format'

describe('formatBytes', () => {
  it('uses the largest whole binary unit', () => {
    expect(formatBytes(512)).toBe('512 bytes')
    expect(formatBytes(4_194_304)).toBe('4 MiB')
    expect(formatBytes(8_388_608)).toBe('8 MiB')
    expect(formatBytes(65_536)).toBe('64 KiB')
    expect(formatBytes(1_572_864)).toBe('1.5 MiB')
  })
})

describe('formatCount', () => {
  it('adds thousands separators', () => {
    expect(formatCount(24576)).toBe('24,576')
  })
})

describe('formatUsd', () => {
  it('shows small amounts to two significant digits', () => {
    expect(formatUsd(0)).toBe('$0')
    expect(formatUsd(0.038)).toBe('$0.038')
    expect(formatUsd(0.0000074)).toBe('$0.0000074')
    expect(formatUsd(0.00000703)).toBe('$0.0000070')
    expect(formatUsd(1.5)).toBe('$1.50')
  })
})

describe('shortVersion', () => {
  it('keeps 12 characters', () => {
    expect(shortVersion('95e251b70a75ea722a0c62ce')).toBe('95e251b70a75')
  })
})

describe('stateSummary', () => {
  it('joins the text in a JSON state', () => {
    expect(stateSummary('Goblins')).toBe('Goblins')
    expect(stateSummary({ party: 'Three', monsters: { kind: 'Goblins', count: 6 } })).toBe(
      'Three · Goblins · 6',
    )
    expect(stateSummary(['a', null, 'b'])).toBe('a · b')
  })
})
