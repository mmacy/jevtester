import { describe, expect, it } from 'vitest'

import { HEAT_STOPS, heat, heatGradient, ink } from './heat'

describe('heat', () => {
  it('returns each stop color at its stop', () => {
    for (const [v, rgb] of HEAT_STOPS) {
      expect(heat(v)).toBe(`rgb(${rgb.join(',')})`)
    }
  })

  it('interpolates between stops', () => {
    // Halfway between 0.4 (47,127,147) and 0.7 (99,183,184).
    expect(heat(0.55)).toBe('rgb(73,155,166)')
  })

  it('clamps values outside 0 to 1', () => {
    expect(heat(-0.2)).toBe(heat(0))
    expect(heat(1.7)).toBe(heat(1))
    expect(heat(Number.NaN)).toBe(heat(0))
  })
})

describe('ink', () => {
  it('switches to dark text above 0.55', () => {
    expect(ink(0.55)).toBe('#dbe8ef')
    expect(ink(0.56)).toBe('#0e2029')
  })
})

describe('heatGradient', () => {
  it('runs through every stop', () => {
    const gradient = heatGradient()
    expect(gradient.startsWith('linear-gradient(90deg, ')).toBe(true)
    for (const [v] of HEAT_STOPS) expect(gradient).toContain(heat(v))
  })
})
