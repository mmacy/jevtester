// The sequential ramp from the mockup: surface blue to pale mint. Every grid
// uses it for "more", whether that's a probability, a share of cases, or a
// metric's rank among targets.

type Rgb = readonly [number, number, number]

export const HEAT_STOPS: readonly (readonly [number, Rgb])[] = [
  [0, [24, 47, 59]],
  [0.15, [31, 74, 94]],
  [0.4, [47, 127, 147]],
  [0.7, [99, 183, 184]],
  [1, [200, 236, 217]],
]

// Text on a cell turns dark above this value, where the ramp gets light.
export const INK_THRESHOLD = 0.55

const DARK_INK = '#0e2029'
const LIGHT_INK = '#dbe8ef'

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0
  return Math.min(1, Math.max(0, value))
}

/** The ramp color for a value from 0 to 1, as `rgb(r,g,b)`. Values outside the range are clamped. */
export function heat(value: number): string {
  const v = clamp01(value)
  for (let i = 1; i < HEAT_STOPS.length; i++) {
    const [b, cb] = HEAT_STOPS[i]
    if (v <= b) {
      const [a, ca] = HEAT_STOPS[i - 1]
      const t = (v - a) / (b - a)
      return `rgb(${ca.map((c, k) => Math.round(c + (cb[k] - c) * t)).join(',')})`
    }
  }
  return `rgb(${HEAT_STOPS[HEAT_STOPS.length - 1][1].join(',')})`
}

/** The text color that reads on `heat(value)`. */
export function ink(value: number): string {
  return clamp01(value) > INK_THRESHOLD ? DARK_INK : LIGHT_INK
}

/** A left-to-right CSS gradient through the ramp's stops, for a key. */
export function heatGradient(): string {
  return `linear-gradient(90deg, ${HEAT_STOPS.map(([v]) => heat(v)).join(', ')})`
}
