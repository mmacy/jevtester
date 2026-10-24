import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { RunSummary } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { PanelHeading } from '../components/panel-heading'
import { ProbeGrid } from '../components/probe-grid'
import { RunBar } from '../components/run-bar'
import {
  CalibrationPanel,
  ChangesPanel,
  ConfusionPanel,
  MetricsPanel,
  Panel,
} from '../components/run-panels'
import { EmptyState, LoadingRows, Spinner } from '../components/states'
import { useLoad } from '../hooks/use-load'
import { useRun } from '../hooks/use-run'
import { formatDateTime, formatUsd, shortVersion } from '../lib/format'
import { isActive } from '../lib/run'
import { CaseStepper } from './case-stepper'

const TH = 'px-2 pb-1.5 text-left text-sm font-medium text-dim'
const TD = 'h-11 rounded-[2px] bg-surface px-2 text-[13.5px]'

const STATUS_CLASS: Record<RunSummary['status'], string> = {
  queued: 'text-dim',
  running: 'text-pick',
  finished: 'text-ok',
  cancelled: 'text-warn',
  failed: 'text-err',
}

function RunList() {
  const runs = useLoad(() => api.listRuns(), 'runs')
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading>Runs</PanelHeading>
      {runs.error ? <ApiErrorState error={runs.error} onRetry={runs.reload} /> : null}
      {runs.data && runs.data.runs.length === 0 ? (
        <EmptyState
          label="No runs"
          action={
            <Link to="/suites" className="text-pick">
              Suites
            </Link>
          }
        />
      ) : null}
      {!runs.error && (runs.loading || runs.data?.runs.length) ? (
        <table className="w-full table-fixed border-separate border-spacing-0.5">
          <thead>
            <tr>
              <th className={`${TH} w-24`}>Run</th>
              <th className={`${TH} w-32`}>Suite</th>
              <th className={`${TH} w-36`}>Question set</th>
              <th className={TH}>Targets</th>
              <th className={`${TH} w-28`}>Status</th>
              <th className={`${TH} w-44`}>Progress</th>
              <th className={`${TH} w-28`}>Cost</th>
              <th className={`${TH} w-36`}>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.data ? (
              runs.data.runs.map((run) => (
                <tr key={run.id}>
                  <td className={TD}>
                    <Link
                      to={`/runs/${encodeURIComponent(run.id)}`}
                      className="font-mono text-sm text-pick no-underline hover:underline"
                    >
                      {run.id}
                    </Link>
                    {run.kind === 'probe' ? (
                      <span className="ml-1.5 text-xs text-faint">probe</span>
                    ) : null}
                  </td>
                  <td className={TD}>{run.suite}</td>
                  <td className={`${TD} font-mono text-xs text-dim`}>
                    {shortVersion(run.question_set_version)}
                  </td>
                  <td className={`${TD} truncate text-sm text-dim`} title={run.targets.join(', ')}>
                    {run.targets.join(', ')}
                  </td>
                  <td className={`${TD} ${STATUS_CLASS[run.status]}`}>
                    {run.status[0].toUpperCase() + run.status.slice(1)}
                  </td>
                  <td className={TD}>
                    <span className="flex items-center gap-2 text-sm text-dim">
                      <span className="h-1.5 flex-1 overflow-hidden rounded-[3px] bg-bg">
                        <i
                          className="block h-full bg-[#63b7b8]"
                          style={{
                            width: `${run.counts.jobs ? (run.counts.done / run.counts.jobs) * 100 : 0}%`,
                          }}
                        />
                      </span>
                      {run.counts.done}/{run.counts.jobs}
                    </span>
                  </td>
                  <td className={TD}>
                    {run.cost_usd == null ? 'Unknown' : formatUsd(run.cost_usd)}
                  </td>
                  <td className={`${TD} text-sm text-dim`}>
                    {formatDateTime(run.started_at ?? run.created_at)}
                  </td>
                </tr>
              ))
            ) : (
              <LoadingRows rows={3} columns={8} />
            )}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

function RunPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { summary, error, reconnecting, setSummary } = useRun(id)
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  // Metrics change while a run runs, so they load again when its status changes.
  const version = summary ? `${summary.status}:${summary.counts.done === summary.counts.jobs}` : ''
  const metrics = useLoad(() => api.getMetrics(id), `${id}:${version}`)
  const runs = useLoad(() => api.listRuns(), `runs:${id}`)
  const baselines = (runs.data?.runs ?? [])
    .filter(
      (r) =>
        r.id !== id &&
        summary &&
        r.suite === summary.suite &&
        r.kind === 'suite' &&
        !isActive(r.status),
    )
    .map((r) => r.id)

  const cancel = async () => {
    setCancelling(true)
    setActionError(null)
    try {
      setSummary(await api.cancelRun(id))
    } catch (e) {
      setActionError(e)
    } finally {
      setCancelling(false)
    }
  }

  const rerun = async () => {
    if (!summary) return
    setActionError(null)
    try {
      const run =
        summary.kind === 'probe'
          ? await api.startProbes({
              suite: summary.suite,
              targets: summary.targets,
              variants: summary.variants,
              question_set_version: summary.question_set_version,
              no_cache: true,
            })
          : await api.startRun({
              suite: summary.suite,
              targets: summary.targets,
              question_set_version: summary.question_set_version,
              repeats: summary.repeats,
              no_cache: true,
              baseline: summary.baseline,
            })
      navigate(`/runs/${encodeURIComponent(run.id)}`)
    } catch (e) {
      setActionError(e)
    }
  }

  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      {error ? <ApiErrorState error={error} /> : null}
      {actionError ? (
        <div className="mb-3">
          <ApiErrorState error={actionError} />
        </div>
      ) : null}
      {summary ? (
        <>
          <RunBar
            run={summary}
            reconnecting={reconnecting}
            cancelling={cancelling}
            onCancel={() => void cancel()}
            onRerun={() => void rerun()}
          />
          {summary.kind === 'probe' ? (
            <div className="mt-6">
              <Panel title="Probes">
                <ProbeGrid runId={id} version={version} />
              </Panel>
            </div>
          ) : null}
          {summary.kind === 'suite' && metrics.error ? (
            <div className="mt-6">
              <ApiErrorState error={metrics.error} onRetry={metrics.reload} />
            </div>
          ) : null}
          {summary.kind === 'suite' && metrics.data ? (
            <>
              <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
                <Panel title="Metrics">
                  <MetricsPanel run={summary} metrics={metrics.data} />
                </Panel>
                <Panel title="Confusion matrix">
                  <ConfusionPanel runId={id} metrics={metrics.data} version={version} />
                </Panel>
              </div>
              <div className="mt-7 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
                <Panel title="Calibration">
                  <CalibrationPanel runId={id} metrics={metrics.data} version={version} />
                </Panel>
                <Panel title="Changed answers">
                  <ChangesPanel run={summary} baselines={baselines} />
                </Panel>
              </div>
            </>
          ) : summary.kind === 'suite' && metrics.loading ? (
            <div className="mt-6">
              <Spinner label="Loading metrics" />
            </div>
          ) : null}
        </>
      ) : !error ? (
        <Spinner label="Loading run" />
      ) : null}
    </section>
  )
}

export function RunsView() {
  return (
    <Routes>
      <Route index element={<RunList />} />
      <Route path=":id" element={<RunPage />} />
      <Route path=":id/changes/:caseId" element={<CaseStepper />} />
    </Routes>
  )
}
