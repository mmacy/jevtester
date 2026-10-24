import { useState } from 'react'

import { api } from '../api/client'
import type { ProbeVariant } from '../api/types'
import { useLoad } from '../hooks/use-load'
import { heat, ink } from '../lib/heat'
import { buildMatrix, type MatrixColumn } from '../lib/matrix'
import { cellKey, probeGrid, VARIANT_LABELS } from '../lib/probes'
import { useTargets } from '../store/targets'
import { AnswerMatrix } from './answer-matrix'
import { ApiErrorState } from './api-error'
import { HeatKey } from './heat-key'
import { EmptyState, LoadingRows, Spinner } from './states'

interface Selected {
  caseId: string
  target: string
  variant: ProbeVariant
}

function RateCell({
  rate,
  label,
  onSelect,
  selected,
}: {
  rate: number | null
  label: string
  onSelect?: () => void
  selected?: boolean
}) {
  if (rate === null)
    return <td className="h-10 rounded-[2px] bg-surface px-2 text-right text-faint">None</td>
  return (
    <td
      className={`h-10 rounded-[2px] text-right ${selected ? 'shadow-[inset_0_0_0_2px_var(--color-pick)]' : ''}`}
      style={{ background: heat(rate), color: ink(rate) }}
    >
      {onSelect ? (
        <button
          type="button"
          onClick={onSelect}
          aria-pressed={selected}
          className="h-full w-full cursor-pointer px-2 text-right"
        >
          {label}
        </button>
      ) : (
        <span className="px-2">{label}</span>
      )}
    </td>
  )
}

/** A selected cell's case: the original answers next to each variant's. */
function CaseVariants({ runId, selected }: { runId: string; selected: Selected }) {
  const targets = useTargets((s) => s.targets) ?? []
  const runCase = useLoad(
    () => api.getRunCase(runId, selected.caseId),
    `${runId}:${selected.caseId}`,
  )
  if (runCase.error) return <ApiErrorState error={runCase.error} onRetry={runCase.reload} />
  if (!runCase.data) return <Spinner label="Loading case" />
  const results = runCase.data.results.filter(
    (r) =>
      r.target === selected.target &&
      (r.variant === null || r.variant.startsWith(selected.variant)),
  )
  const columns: MatrixColumn[] = results.map((r, i) => ({
    target: r.target,
    key: `${r.variant ?? 'original'}:${r.repeat}:${i}`,
    label: r.variant ?? 'Original',
    state: r.result.ok ? 'ok' : 'failed',
    result: r.result,
  }))
  const rows = buildMatrix(
    { state: runCase.data.case.state, questions: runCase.data.questions, images: [] },
    columns,
    (t) => targets.some((x) => x.name === t && x.local),
  )
  return (
    <section aria-label="Variants" className="mt-6">
      <h3 className="m-0 mb-2 font-display text-[18px] font-bold [font-stretch:75%]">
        {selected.caseId} on {selected.target}, {VARIANT_LABELS[selected.variant]}
      </h3>
      {columns.length === 0 ? (
        <EmptyState label="No results for this variant" />
      ) : (
        <AnswerMatrix columns={columns} rows={rows} targets={targets} />
      )}
    </section>
  )
}

/** Each case's change rate under each variant, for each target. */
export function ProbeGrid({ runId, version }: { runId: string; version: string }) {
  const report = useLoad(() => api.getProbes(runId), `${runId}:${version}`)
  const [selected, setSelected] = useState<Selected | null>(null)
  if (report.error) return <ApiErrorState error={report.error} onRetry={report.reload} />
  if (!report.data) {
    return (
      <table>
        <tbody>
          <LoadingRows rows={4} columns={5} />
        </tbody>
      </table>
    )
  }
  const grid = probeGrid(report.data)
  if (grid.cases.length === 0) return <EmptyState label="No probe results yet" />
  const isSelected = (caseId: string, target: string, variant: ProbeVariant) =>
    selected?.caseId === caseId && selected.target === target && selected.variant === variant
  return (
    <div>
      <div className="mb-2 flex justify-end">
        <HeatKey label="Share of variants that changed an answer" />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] table-fixed border-separate border-spacing-0.5">
          <thead>
            <tr>
              <th className="w-44" />
              {grid.targets.map((t) => (
                <th
                  key={t}
                  colSpan={grid.variants.length}
                  scope="colgroup"
                  className="truncate px-2 text-left font-display text-[17px] font-bold [font-stretch:62.5%]"
                >
                  {t}
                </th>
              ))}
            </tr>
            <tr>
              <th className="px-2 text-left text-sm font-medium text-dim">Case</th>
              {grid.targets.flatMap((t) =>
                grid.variants.map((v) => (
                  <th
                    key={`${t}|${v}`}
                    scope="col"
                    className="px-2 text-right text-xs font-medium text-dim"
                  >
                    {VARIANT_LABELS[v]}
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {grid.cases.map((caseId) => (
              <tr key={caseId}>
                <th
                  scope="row"
                  className="truncate px-2 text-left font-mono text-sm font-normal text-pick"
                >
                  {caseId}
                </th>
                {grid.targets.flatMap((t) =>
                  grid.variants.map((v) => {
                    const cell = grid.cells.get(cellKey(caseId, t, v))
                    if (!cell) return <td key={`${t}|${v}`} className="rounded-[2px] bg-surface" />
                    return (
                      <RateCell
                        key={`${t}|${v}`}
                        rate={cell.rate}
                        label={`${cell.changed} of ${cell.instances}`}
                        selected={isSelected(caseId, t, v)}
                        onSelect={() => setSelected({ caseId, target: t, variant: v })}
                      />
                    )
                  }),
                )}
              </tr>
            ))}
            <tr>
              <th scope="row" className="px-2 pt-2 text-left text-[13px] font-medium text-dim">
                Change rate
              </th>
              {grid.targets.flatMap((t) =>
                grid.variants.map((v) => {
                  const rate = grid.summary.get(`${t}|${v}`) ?? null
                  return (
                    <RateCell
                      key={`${t}|${v}`}
                      rate={rate}
                      label={rate === null ? '' : `${Math.round(rate * 100)}%`}
                    />
                  )
                }),
              )}
            </tr>
          </tbody>
        </table>
      </div>
      {selected ? <CaseVariants runId={runId} selected={selected} /> : null}
    </div>
  )
}
