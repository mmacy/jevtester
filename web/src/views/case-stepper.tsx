import { useCallback, useEffect, useMemo } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { AnswerValue, RunCase } from '../api/types'
import { AnswerMatrix } from '../components/answer-matrix'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { HeatKey } from '../components/heat-key'
import { PanelHeading } from '../components/panel-heading'
import { EmptyState, Spinner } from '../components/states'
import { useLoad } from '../hooks/use-load'
import { stateSummary } from '../lib/format'
import { buildMatrix, type MatrixColumn } from '../lib/matrix'
import { useTargets } from '../store/targets'

function columnsFor(runCase: RunCase, runId: string): MatrixColumn[] {
  return runCase.results
    .filter((r) => r.repeat === 0 && r.variant === null)
    .map((r) => ({
      target: r.target,
      key: `${runId}:${r.target}`,
      label: `Run ${runId}`,
      state: r.result.ok ? 'ok' : 'failed',
      result: r.result,
    }))
}

/** One changed case at a time: its state, and each target's answers in the baseline and this run. */
export function CaseStepper() {
  const { id = '', caseId = '' } = useParams()
  const [params] = useSearchParams()
  const baseline = params.get('baseline') ?? ''
  const navigate = useNavigate()
  const targets = useTargets((s) => s.targets) ?? []

  const changes = useLoad(() => api.getChanges(id, baseline), `${id}:${baseline}`)
  const current = useLoad(() => api.getRunCase(id, caseId), `${id}:${caseId}`)
  const before = useLoad(() => api.getRunCase(baseline, caseId), `${baseline}:${caseId}`)

  const caseIds = useMemo(
    () => [...new Set((changes.data?.changes ?? []).map((c) => c.case_id))],
    [changes.data],
  )
  const index = caseIds.indexOf(caseId)
  const go = useCallback(
    (to: number) => {
      const next = caseIds[to]
      if (next)
        navigate(
          `/runs/${encodeURIComponent(id)}/changes/${encodeURIComponent(next)}?baseline=${encodeURIComponent(baseline)}`,
        )
    },
    [caseIds, navigate, id, baseline],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'ArrowLeft') go(index - 1)
      if (e.key === 'ArrowRight') go(index + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, index])

  const runCase = current.data
  const columns: MatrixColumn[] = runCase
    ? columnsFor(runCase, id).flatMap((column) => {
        const old = before.data
          ? columnsFor(before.data, baseline).find((c) => c.target === column.target)
          : undefined
        return old ? [old, column] : [column]
      })
    : []
  const local = new Set(targets.filter((t) => t.local).map((t) => t.name))
  const rows = runCase
    ? buildMatrix(
        { state: runCase.case.state, questions: runCase.questions, images: [] },
        columns,
        (t) => local.has(t),
      )
    : []
  const expected: Record<string, AnswerValue> = {}
  for (const [q, e] of Object.entries(runCase?.case.expected ?? {})) {
    if (e.answer !== null) expected[q] = e.answer
  }
  const changed = (changes.data?.changes ?? []).filter((c) => c.case_id === caseId)

  return (
    <section className="px-6 pt-5 pb-12">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <PanelHeading
          note={caseIds.length ? `${index + 1} of ${caseIds.length} changed cases` : undefined}
        >
          {caseId}
        </PanelHeading>
        <span className="flex-1" />
        <Button onClick={() => go(index - 1)} disabled={index <= 0}>
          Previous
        </Button>
        <Button onClick={() => go(index + 1)} disabled={index < 0 || index >= caseIds.length - 1}>
          Next
        </Button>
        <Link to={`/runs/${encodeURIComponent(id)}`} className="no-underline">
          <Button>Run {id}</Button>
        </Link>
      </div>
      {[current.error, before.error, changes.error].filter(Boolean).map((error, i) => (
        <div key={i} className="mb-3">
          <ApiErrorState error={error} />
        </div>
      ))}
      {runCase ? (
        <>
          <p className="m-0 mb-1 text-sm text-dim">State</p>
          <p className="m-0 mb-3 rounded bg-surface px-3 py-2 text-[13.5px]">
            {stateSummary(runCase.case.state)}
          </p>
          {changed.length > 0 ? (
            <p className="m-0 mb-3 text-[13px] text-dim">
              Changed:{' '}
              {changed.map((c) => (
                <span key={`${c.target}:${c.question}`} className="mr-3">
                  <b className="font-mono text-pick">{c.question}</b> on {c.target}, {c.status}
                </span>
              ))}
            </p>
          ) : null}
          <div className="mb-2 flex justify-end">
            <HeatKey label="Probability" showPick />
          </div>
          <AnswerMatrix columns={columns} rows={rows} targets={targets} expected={expected} />
        </>
      ) : current.loading ? (
        <Spinner label="Loading case" />
      ) : (
        <EmptyState label="No such case in this run" />
      )}
    </section>
  )
}
