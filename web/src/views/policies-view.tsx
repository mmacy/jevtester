import { useState } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type { PolicyDetail, SweepResult } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { FieldLabel } from '../components/fields'
import { PanelHeading } from '../components/panel-heading'
import { EmptyState, LoadingRows, Spinner } from '../components/states'
import { SweepChart } from '../components/sweep-chart'
import { useLoad } from '../hooks/use-load'
import { shortVersion } from '../lib/format'

const TH = 'px-2 pb-1.5 text-left text-sm font-medium text-dim'
const TD = 'h-10 rounded-[2px] bg-surface px-2 text-[13.5px]'
const SELECT =
  'w-full rounded border border-line bg-bg px-2 py-1.5 text-sm focus:border-pick focus:outline-none'
const NUMBER = 'w-20 rounded border border-line bg-bg px-1.5 py-1 text-sm'

function PolicyList() {
  const policies = useLoad(() => api.listPolicies(), 'policies')
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading>Policies</PanelHeading>
      {policies.error ? <ApiErrorState error={policies.error} onRetry={policies.reload} /> : null}
      {policies.data && policies.data.policies.length === 0 ? (
        <EmptyState label="No policies in suites/policies/" />
      ) : null}
      {!policies.error && (policies.loading || policies.data?.policies.length) ? (
        <table className="w-full table-fixed border-separate border-spacing-0.5">
          <thead>
            <tr>
              <th className={`${TH} w-48`}>Policy</th>
              <th className={`${TH} w-40`}>Version</th>
              <th className={TH}>Actions</th>
              <th className={`${TH} w-48`}>Suites</th>
            </tr>
          </thead>
          <tbody>
            {policies.data ? (
              policies.data.policies.map((p) => (
                <tr key={p.name}>
                  <td className={TD}>
                    <Link
                      to={`/policies/${encodeURIComponent(p.name)}`}
                      className="font-mono text-sm text-pick no-underline hover:underline"
                    >
                      {p.name}
                    </Link>
                  </td>
                  <td className={`${TD} font-mono text-xs text-dim`}>{shortVersion(p.version)}</td>
                  <td className={`${TD} truncate`}>{p.actions.join(', ')}</td>
                  <td className={TD}>
                    {p.suites.join(', ') || <span className="text-faint">None</span>}
                  </td>
                </tr>
              ))
            ) : (
              <LoadingRows rows={2} columns={4} />
            )}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

function Editor({ policy, onSaved }: { policy: PolicyDetail; onSaved: (p: PolicyDetail) => void }) {
  const [text, setText] = useState(policy.yaml)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const changed = text !== policy.yaml

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      onSaved(await api.savePolicy(policy.name, text))
    } catch (e) {
      setError(e)
    } finally {
      setSaving(false)
    }
  }

  const details = error instanceof ApiError ? error.details : []
  return (
    <section aria-label="Policy">
      <PanelHeading note={shortVersion(policy.version)}>YAML</PanelHeading>
      <textarea
        aria-label="Policy YAML"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.min(40, Math.max(16, text.split('\n').length + 1))}
        className="w-full resize-y rounded border border-line bg-bg px-3 py-2 font-mono text-sm leading-relaxed focus:border-pick focus:outline-none"
      />
      {error ? (
        details.length > 0 ? (
          <ul
            aria-label="Policy errors"
            className="m-0 mt-2 list-none rounded bg-err-bg p-0 px-3 py-2 text-sm text-err-ink"
          >
            {details.map((d, i) => (
              <li key={i}>
                {d.line !== null ? <b className="font-mono text-err">Line {d.line} </b> : null}
                {d.field ? <code className="font-mono text-err">{d.field} </code> : null}
                {d.message}
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-2">
            <ApiErrorState error={error} />
          </div>
        )
      ) : null}
      <div className="mt-3 flex items-center gap-2.5">
        <Button primary onClick={() => void save()} disabled={saving || !changed}>
          Save
        </Button>
        {changed ? (
          <Button onClick={() => setText(policy.yaml)} disabled={saving}>
            Discard changes
          </Button>
        ) : null}
        {saving ? <Spinner label="Saving" /> : null}
      </div>
    </section>
  )
}

function Sweep({ policy }: { policy: PolicyDetail }) {
  const runs = useLoad(() => api.listRuns(), 'runs')
  const candidates = (runs.data?.runs ?? []).filter(
    (r) => r.kind === 'suite' && r.status === 'finished' && policy.suites.includes(r.suite),
  )
  const [runId, setRunId] = useState<string | null>(null)
  const run = candidates.find((r) => r.id === runId) ?? candidates[0] ?? null
  const [target, setTarget] = useState<string | null>(null)
  const chosenTarget = target && run?.targets.includes(target) ? target : (run?.targets[0] ?? null)
  const [threshold, setThreshold] = useState<string | null>(null)
  const chosenThreshold = threshold ?? policy.thresholds[0]?.name ?? null
  const [range, setRange] = useState({ start: 0, stop: 1, step: 0.05 })
  const [result, setResult] = useState<SweepResult | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [sweeping, setSweeping] = useState(false)
  const metrics = useLoad(
    () => (run ? api.getMetrics(run.id) : Promise.resolve(null)),
    `metrics:${run?.id ?? ''}`,
  )
  const decision = metrics.data?.targets.find((t) => t.target === chosenTarget)?.decision ?? null

  const sweep = async () => {
    if (!run || !chosenTarget || !chosenThreshold) return
    setSweeping(true)
    setError(null)
    try {
      setResult(
        await api.sweep(policy.name, {
          run_id: run.id,
          target: chosenTarget,
          threshold: chosenThreshold,
          ...range,
        }),
      )
    } catch (e) {
      setError(e)
    } finally {
      setSweeping(false)
    }
  }

  if (runs.data && candidates.length === 0) {
    return (
      <section aria-label="Sweep">
        <PanelHeading>Sweep</PanelHeading>
        <EmptyState
          label="No finished run of a suite that uses this policy"
          action={
            <Link to="/suites" className="text-pick">
              Suites
            </Link>
          }
        />
      </section>
    )
  }

  return (
    <section aria-label="Sweep">
      <PanelHeading>Sweep</PanelHeading>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <FieldLabel htmlFor="sweep-run">Run</FieldLabel>
          <select
            id="sweep-run"
            className={SELECT}
            value={run?.id ?? ''}
            onChange={(e) => setRunId(e.target.value)}
          >
            {candidates.map((r) => (
              <option key={r.id} value={r.id}>
                Run {r.id}, {r.suite}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="sweep-target">Target</FieldLabel>
          <select
            id="sweep-target"
            className={SELECT}
            value={chosenTarget ?? ''}
            onChange={(e) => setTarget(e.target.value)}
          >
            {(run?.targets ?? []).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="sweep-threshold">Threshold</FieldLabel>
          <select
            id="sweep-threshold"
            className={SELECT}
            value={chosenThreshold ?? ''}
            onChange={(e) => setThreshold(e.target.value)}
          >
            {policy.thresholds.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-dim">
        {(['start', 'stop', 'step'] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5">
            {k[0].toUpperCase() + k.slice(1)}
            <input
              type="number"
              step="0.05"
              value={range[k]}
              onChange={(e) => setRange((r) => ({ ...r, [k]: Number(e.target.value) }))}
              className={NUMBER}
            />
          </label>
        ))}
        <Button
          primary
          onClick={() => void sweep()}
          disabled={sweeping || !run || !chosenTarget || !chosenThreshold}
        >
          Sweep
        </Button>
        {sweeping ? <Spinner label="Sweeping" /> : null}
      </div>
      {decision ? (
        <p className="m-0 mt-3 text-[13px] text-dim">
          Run {run?.id} on {chosenTarget}: decision accuracy{' '}
          <b className="text-text">
            {decision.accuracy === null ? 'None' : decision.accuracy.toFixed(3)}
          </b>
          , decided{' '}
          <b className="text-text">
            {decision.decided_share === null
              ? 'None'
              : `${Math.round(decision.decided_share * 100)}%`}
          </b>
          , errors among decided{' '}
          <b className="text-text">
            {decision.error_rate === null ? 'None' : `${Math.round(decision.error_rate * 100)}%`}
          </b>
          {decision.cost !== null ? (
            <>
              , cost <b className="text-text">{decision.cost.toFixed(2)}</b>
            </>
          ) : null}
          , {decision.n} cases
        </p>
      ) : null}
      {error ? (
        <div className="mt-3">
          <ApiErrorState error={error} />
        </div>
      ) : null}
      {result ? (
        <div className="mt-4">
          <SweepChart
            points={result.points}
            current={result.current}
            threshold={result.threshold}
          />
          <table
            aria-label="Sweep points"
            className="mt-3 w-full table-fixed border-separate border-spacing-0.5"
          >
            <thead>
              <tr>
                {[result.threshold, 'Decided', 'Errors', 'Cost'].map((h) => (
                  <th key={h} className="px-2 py-1 text-right text-sm font-medium text-dim">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.points.map((p) => (
                <tr
                  key={p.value}
                  className={p.value === result.current ? 'font-semibold' : undefined}
                >
                  <td className={`${TD} text-right`}>
                    {p.value.toFixed(2)}
                    {p.value === result.current ? (
                      <span className="ml-1.5 text-xs text-pick">Current</span>
                    ) : null}
                  </td>
                  <td className={`${TD} text-right`}>
                    {p.decided_share === null ? 'None' : `${Math.round(p.decided_share * 100)}%`}
                  </td>
                  <td className={`${TD} text-right`}>
                    {p.error_rate === null ? 'None' : `${Math.round(p.error_rate * 100)}%`}
                  </td>
                  <td className={`${TD} text-right`}>
                    {p.cost === null ? 'None' : p.cost.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  )
}

function PolicyPage() {
  const { name = '' } = useParams()
  const loaded = useLoad(() => api.getPolicy(name), name)
  const [saved, setSaved] = useState<PolicyDetail | null>(null)
  const policy = saved?.name === name ? saved : loaded.data
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading note={policy ? `used by ${policy.suites.join(', ') || 'no suite'}` : undefined}>
        {name}
      </PanelHeading>
      {loaded.error ? <ApiErrorState error={loaded.error} onRetry={loaded.reload} /> : null}
      {policy ? (
        <div className="grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,600px)_minmax(0,1fr)]">
          <div>
            <Editor key={policy.version} policy={policy} onSaved={setSaved} />
            <section aria-label="Thresholds" className="mt-6">
              <PanelHeading>Thresholds</PanelHeading>
              <table className="w-full table-fixed border-separate border-spacing-0.5">
                <thead>
                  <tr>
                    <th className={`${TH} w-40`}>Threshold</th>
                    <th className={`${TH} w-24`}>Value</th>
                    <th className={TH}>Per target</th>
                  </tr>
                </thead>
                <tbody>
                  {policy.thresholds.map((t) => (
                    <tr key={t.name}>
                      <td className={`${TD} font-mono text-sm`}>{t.name}</td>
                      <td className={TD}>{t.value}</td>
                      <td className={`${TD} text-sm text-dim`}>
                        {Object.entries(t.per_target)
                          .map(([target, v]) => `${target} ${v}`)
                          .join(', ') || 'None'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="m-0 mt-2 text-[13px] text-dim">Actions: {policy.actions.join(', ')}</p>
            </section>
          </div>
          <Sweep key={policy.version} policy={policy} />
        </div>
      ) : loaded.loading ? (
        <Spinner label="Loading policy" />
      ) : null}
    </section>
  )
}

export function PoliciesView() {
  return (
    <Routes>
      <Route index element={<PolicyList />} />
      <Route path=":name" element={<PolicyPage />} />
    </Routes>
  )
}
