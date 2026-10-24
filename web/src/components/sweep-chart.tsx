import { useState } from 'react'

import type { SweepPoint } from '../api/types'

const W = 640
const H = 260
const PAD = { left: 44, right: 108, top: 16, bottom: 36 }

const SERIES = [
  { key: 'decided_share', label: 'Decided', color: 'var(--color-series-1)' },
  { key: 'error_rate', label: 'Errors', color: 'var(--color-series-2)' },
] as const

interface SweepChartProps {
  points: readonly SweepPoint[]
  current: number | null
  threshold: string
}

const percent = (v: number | null) => (v === null ? 'None' : `${Math.round(v * 100)}%`)

/** Share of cases decided and the error rate among them, as a threshold moves. */
export function SweepChart({ points, current, threshold }: SweepChartProps) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length === 0) return null
  const xs = points.map((p) => p.value)
  const lo = Math.min(...xs, current ?? Infinity)
  const hi = Math.max(...xs, current ?? -Infinity)
  const x = (v: number) =>
    PAD.left + (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (W - PAD.left - PAD.right)
  const y = (v: number) => PAD.top + (1 - v) * (H - PAD.top - PAD.bottom)
  const line = (key: (typeof SERIES)[number]['key']) =>
    points
      .filter((p) => p[key] !== null)
      .map(
        (p, i) =>
          `${i === 0 ? 'M' : 'L'}${x(p.value).toFixed(1)},${y(p[key] as number).toFixed(1)}`,
      )
      .join(' ')
  const last = points.at(-1)!
  const shown = hover === null ? null : points[hover]
  const step = points.length > 1 ? x(points[1].value) - x(points[0].value) : W

  return (
    <figure className="m-0">
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-dim" aria-hidden="true">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <i className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
        {current !== null ? (
          <span className="flex items-center gap-1.5">
            <i className="inline-block h-3 w-0 border-l-2 border-dashed border-faint" />
            Current {threshold}
          </span>
        ) : null}
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          role="img"
          aria-label={`Share decided and error rate against ${threshold}`}
          onMouseLeave={() => setHover(null)}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(t)}
                y2={y(t)}
                stroke="var(--color-line-soft)"
              />
              <text
                x={PAD.left - 8}
                y={y(t) + 4}
                textAnchor="end"
                fontSize="11"
                fill="var(--color-faint)"
              >
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % Math.max(1, Math.ceil(points.length / 8)) === 0 || i === points.length - 1 ? (
              <text
                key={p.value}
                x={x(p.value)}
                y={H - PAD.bottom + 16}
                textAnchor="middle"
                fontSize="11"
                fill="var(--color-faint)"
              >
                {p.value.toFixed(2)}
              </text>
            ) : null,
          )}
          <text
            x={(PAD.left + W - PAD.right) / 2}
            y={H - 4}
            textAnchor="middle"
            fontSize="11"
            fill="var(--color-dim)"
          >
            {threshold}
          </text>
          {current !== null ? (
            <line
              x1={x(current)}
              x2={x(current)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--color-faint)"
              strokeWidth="2"
              strokeDasharray="4 4"
            />
          ) : null}
          {shown ? (
            <line
              x1={x(shown.value)}
              x2={x(shown.value)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--color-dim)"
            />
          ) : null}
          {SERIES.map((s) => (
            <g key={s.key}>
              <path
                d={line(s.key)}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinejoin="round"
              />
              {points.map((p, i) =>
                p[s.key] === null ? null : (
                  <circle
                    key={p.value}
                    cx={x(p.value)}
                    cy={y(p[s.key] as number)}
                    r={hover === i ? 5 : 4}
                    fill={s.color}
                    stroke="var(--color-bg)"
                    strokeWidth="2"
                  />
                ),
              )}
              {last[s.key] !== null ? (
                <text
                  x={x(last.value) + 10}
                  y={y(last[s.key] as number) + 4}
                  fontSize="12"
                  fill="var(--color-text)"
                >
                  {s.label} {percent(last[s.key])}
                </text>
              ) : null}
            </g>
          ))}
          {points.map((p, i) => (
            <rect
              key={p.value}
              x={x(p.value) - step / 2}
              y={PAD.top}
              width={step}
              height={H - PAD.top - PAD.bottom}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              data-testid="sweep-hit"
            />
          ))}
        </svg>
        {shown ? (
          <div
            role="tooltip"
            className="pointer-events-none absolute top-2 rounded border border-line bg-raise px-2.5 py-1.5 text-xs"
            style={{ left: `${(x(shown.value) / W) * 100}%`, transform: 'translateX(8px)' }}
          >
            <b className="block font-semibold">
              {threshold} {shown.value.toFixed(2)}
            </b>
            Decided {percent(shown.decided_share)}
            <br />
            Errors {percent(shown.error_rate)}
            {shown.cost !== null ? (
              <>
                <br />
                Cost {shown.cost.toFixed(2)}
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </figure>
  )
}
