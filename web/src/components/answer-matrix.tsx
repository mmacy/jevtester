import type { TargetInfo } from '../api/types'
import { codeLabel, ERROR_LABELS, WARNING_LABELS } from '../lib/codes'

import { SPREAD_ALERT, type MatrixColumn, type MatrixRow } from '../lib/matrix'
import { HeatCell } from './heat-cell'
import { NotReadyCell, Spinner } from './states'

interface AnswerMatrixProps {
  columns: MatrixColumn[]
  rows: MatrixRow[]
  targets: readonly TargetInfo[]
}

function ColumnStatus({ column }: { column: MatrixColumn }) {
  const base =
    'mt-1.5 block h-[74px] overflow-hidden rounded-[3px] px-1.5 py-1 text-xs leading-snug'
  if (column.state === 'pending') {
    return (
      <span className={`${base} bg-raise`}>
        <Spinner label={`Asking ${column.target}`} />
      </span>
    )
  }
  const error = column.result?.error ?? column.error ?? null
  if (column.state === 'failed' || error) {
    return (
      <span
        className={`${base} bg-err-bg text-err-ink shadow-[inset_3px_0_0_var(--color-err)]`}
        title={error?.message}
      >
        <b className="block font-[650] text-err">
          {error ? codeLabel(ERROR_LABELS, error.code) : 'Failed'}
        </b>
        {error?.message}
      </span>
    )
  }
  const warnings = column.result?.warnings ?? []
  if (warnings.length > 0) {
    return (
      <span
        className={`${base} bg-warn-bg text-warn-ink shadow-[inset_3px_0_0_var(--color-warn)]`}
        title={warnings.map((w) => w.message).join('\n')}
      >
        <b className="block font-[650] text-warn">
          {codeLabel(WARNING_LABELS, warnings[0].code)}
          {warnings.length > 1 ? ` and ${warnings.length - 1} more` : ''}
        </b>
        {warnings[0].message}
      </span>
    )
  }
  return <span className={`${base} bg-raise text-ok`}>Answered</span>
}

function Blank({ column }: { column: MatrixColumn }) {
  if (column.state === 'failed') return <NotReadyCell />
  if (column.state === 'pending')
    return <td className="h-[38px] animate-pulse rounded-[2px] bg-surface" />
  return <td className="h-[38px] rounded-[2px] bg-surface" />
}

function SpreadCell({ value, digits }: { value: number | null; digits: number }) {
  if (value === null) return <td />
  const alert = value >= SPREAD_ALERT
  return (
    <td
      className={`px-2 text-left text-sm ${alert ? 'text-warn' : 'text-dim'}`}
      data-alert={alert || undefined}
    >
      <span
        aria-hidden="true"
        className="mr-1.5 inline-block h-2 rounded-[1px] bg-warn align-middle"
        style={{ width: `${Math.max(2, value * 120)}px` }}
      />
      {value.toFixed(digits)}
    </td>
  )
}

function ScoreCell({ score, levels }: { score: number; levels: number }) {
  const at = levels > 1 ? score / (levels - 1) : 0
  return (
    <td className="relative h-8 rounded-[2px] bg-surface px-2 text-right">
      <span aria-hidden="true" className="absolute top-1/2 right-2 left-2 h-px bg-line" />
      <span
        aria-hidden="true"
        className="absolute top-[calc(50%-7px)] h-3.5 w-[3px] rounded-[1px] bg-pick"
        style={{ left: `calc(8px + (100% - 16px) * ${at})` }}
      />
      <span className="relative bg-surface pl-1 font-[650] text-pick">{score.toFixed(2)}</span>
    </td>
  )
}

/** The answers grid: targets as columns, options and levels as rows, color for probability. */
export function AnswerMatrix({ columns, rows, targets }: AnswerMatrixProps) {
  const labels = new Map(targets.map((t) => [t.name, t.label]))
  const span = columns.length + 2
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] table-fixed border-separate border-spacing-0.5">
        <colgroup>
          <col className="w-[220px]" />
          {columns.map((column) => (
            <col
              key={column.target}
              className={column.state === 'failed' ? 'w-[132px]' : undefined}
            />
          ))}
          <col className="w-24" />
        </colgroup>
        <thead>
          <tr>
            <th />
            {columns.map((column) => (
              <th
                key={column.target}
                scope="col"
                className="bg-bg px-1.5 pt-1.5 pb-2 text-left align-top font-normal"
              >
                <span
                  className="block truncate font-display text-[17px] leading-tight font-bold [font-stretch:62.5%]"
                  title={column.target}
                >
                  {column.target}
                </span>
                <span className="mt-0.5 block truncate text-xs text-dim">
                  {labels.get(column.target)}
                </span>
                <ColumnStatus column={column} />
              </th>
            ))}
            <th scope="col" className="bg-bg px-1.5 pt-1.5 pb-2 text-left align-top font-normal">
              <span className="block font-display text-[17px] leading-tight font-bold [font-stretch:62.5%]">
                Spread
              </span>
              <span className="mt-0.5 block text-xs text-dim">max - min</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            switch (row.kind) {
              case 'group':
                return (
                  <tr key={row.key}>
                    <th
                      colSpan={span}
                      className="border-b border-line px-2 pt-[18px] pb-1.5 text-left font-normal"
                    >
                      {row.id !== 'usage' ? (
                        <span className="mr-2 font-mono text-sm text-pick">{row.id}</span>
                      ) : null}
                      <span className="font-display text-[16px] font-semibold [font-stretch:85%]">
                        {row.instructions}
                      </span>
                      {row.type ? (
                        <span className="ml-2 text-xs text-faint">{row.type}</span>
                      ) : null}
                    </th>
                  </tr>
                )
              case 'heat':
                return (
                  <tr key={row.key}>
                    <th scope="row" className="h-[38px] px-2 text-left leading-tight font-normal">
                      <b className="block text-[13.5px] font-semibold">{row.label}</b>
                      {row.sub ? (
                        <small className="block truncate text-xs text-faint" title={row.sub}>
                          {row.sub}
                        </small>
                      ) : null}
                    </th>
                    {columns.map((column, i) => {
                      const cell = row.cells[i]
                      if (column.state !== 'ok' || cell.value === null)
                        return <Blank key={column.target} column={column} />
                      return (
                        <HeatCell
                          key={column.target}
                          value={cell.value}
                          digits={row.digits}
                          picked={cell.picked}
                        />
                      )
                    })}
                    <SpreadCell value={row.spread} digits={row.digits} />
                  </tr>
                )
              case 'score':
                return (
                  <tr key={row.key}>
                    <th scope="row" className="h-8 px-2 text-left text-[13px] font-normal text-dim">
                      Score
                    </th>
                    {columns.map((column, i) => {
                      const score = row.cells[i]
                      if (column.state !== 'ok' || score === null)
                        return <Blank key={column.target} column={column} />
                      return <ScoreCell key={column.target} score={score} levels={row.levels} />
                    })}
                    <SpreadCell value={row.spread} digits={2} />
                  </tr>
                )
              case 'plain':
                return (
                  <tr key={row.key}>
                    <th scope="row" className="h-8 px-2 text-left text-[13px] font-normal text-dim">
                      {row.label}
                    </th>
                    {columns.map((column, i) => {
                      const text = row.cells[i]
                      if (column.state !== 'ok' || text === null)
                        return <Blank key={column.target} column={column} />
                      return (
                        <td
                          key={column.target}
                          className={`h-8 rounded-[2px] bg-surface px-2 text-right ${row.warn[i] ? 'text-warn' : 'text-text'}`}
                        >
                          {text}
                        </td>
                      )
                    })}
                    <td />
                  </tr>
                )
            }
          })}
        </tbody>
      </table>
    </div>
  )
}
