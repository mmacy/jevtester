import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { ProbeVariant } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { FieldLabel } from '../components/fields'
import { PanelHeading } from '../components/panel-heading'
import { EmptyState, Spinner } from '../components/states'
import { TargetPicker } from '../components/target-picker'
import { useLoad } from '../hooks/use-load'
import { formatDateTime } from '../lib/format'
import { VARIANT_LABELS } from '../lib/probes'
import { useTargets } from '../store/targets'

const VARIANTS = Object.keys(VARIANT_LABELS) as ProbeVariant[]

const SELECT =
  'w-full rounded border border-line bg-bg px-2 py-1.5 text-sm focus:border-pick focus:outline-none'

export function ProbesView() {
  const navigate = useNavigate()
  const suites = useLoad(() => api.listSuites(), 'suites')
  const runs = useLoad(() => api.listRuns(), 'runs')
  const allTargets = useTargets((s) => s.targets) ?? []
  const [suiteName, setSuiteName] = useState<string | null>(null)
  const [targets, setTargets] = useState<string[] | null>(null)
  const [variants, setVariants] = useState<ProbeVariant[]>([
    'option_order',
    'key_order',
    'bare_levels',
  ])
  const [useCache, setUseCache] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const suite =
    suites.data?.suites.find((s) => s.name === suiteName) ?? suites.data?.suites[0] ?? null
  const chosenTargets = targets ?? suite?.targets ?? []
  const probes = (runs.data?.runs ?? []).filter((r) => r.kind === 'probe')

  const toggle = (variant: ProbeVariant, on: boolean) =>
    setVariants((current) => VARIANTS.filter((v) => (v === variant ? on : current.includes(v))))

  const start = async () => {
    if (!suite) return
    setStarting(true)
    setError(null)
    try {
      const run = await api.startProbes({
        suite: suite.name,
        targets: chosenTargets,
        variants,
        no_cache: !useCache,
      })
      navigate(`/runs/${encodeURIComponent(run.id)}`)
    } catch (e) {
      setError(e)
      setStarting(false)
    }
  }

  return (
    <section className="grid max-w-[1440px] grid-cols-1 gap-8 px-6 pt-5 pb-12 xl:grid-cols-[400px_minmax(0,1fr)]">
      <div aria-label="Probe" role="form">
        <PanelHeading>Probe a suite</PanelHeading>
        {error ? <ApiErrorState error={error} /> : null}
        {suites.error ? <ApiErrorState error={suites.error} onRetry={suites.reload} /> : null}
        <div className="space-y-3">
          <div>
            <FieldLabel htmlFor="probe-suite">Suite</FieldLabel>
            <select
              id="probe-suite"
              className={SELECT}
              value={suite?.name ?? ''}
              disabled={!suites.data}
              onChange={(e) => {
                setSuiteName(e.target.value)
                setTargets(null)
              }}
            >
              {(suites.data?.suites ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span className="text-sm text-dim">Targets</span>
            <TargetPicker targets={allTargets} selected={chosenTargets} onChange={setTargets} />
          </div>
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-1 text-sm text-dim">Variants</legend>
            <div className="grid gap-1">
              {VARIANTS.map((v) => (
                <label
                  key={v}
                  className="flex items-center gap-2 rounded border border-line-soft px-2 py-1 text-[13px]"
                >
                  <input
                    type="checkbox"
                    className="accent-pick"
                    checked={variants.includes(v)}
                    onChange={(e) => toggle(v, e.target.checked)}
                  />
                  {VARIANT_LABELS[v]}
                </label>
              ))}
              <label className="flex items-center gap-2 rounded border border-line-soft px-2 py-1 text-[13px] text-faint">
                <input type="checkbox" disabled />
                Paraphrase
                <small className="ml-auto text-xs">Needs Claude</small>
              </label>
            </div>
          </fieldset>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="accent-pick"
              checked={useCache}
              onChange={(e) => setUseCache(e.target.checked)}
            />
            Use cache
          </label>
          <div className="flex items-center gap-2.5">
            <Button
              primary
              onClick={() => void start()}
              disabled={starting || !suite || chosenTargets.length === 0 || variants.length === 0}
            >
              Start probes
            </Button>
            {starting ? <Spinner label="Starting probes" /> : null}
          </div>
        </div>
      </div>
      <div>
        <PanelHeading>Probe runs</PanelHeading>
        {runs.error ? <ApiErrorState error={runs.error} onRetry={runs.reload} /> : null}
        {runs.data && probes.length === 0 ? <EmptyState label="No probe runs" /> : null}
        {probes.length > 0 ? (
          <table className="w-full table-fixed border-separate border-spacing-0.5">
            <thead>
              <tr>
                {['Run', 'Suite', 'Variants', 'Status', 'Started'].map((h) => (
                  <th key={h} className="px-2 pb-1.5 text-left text-sm font-medium text-dim">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {probes.map((r) => (
                <tr key={r.id}>
                  <td className="h-11 rounded-[2px] bg-surface px-2">
                    <Link
                      to={`/runs/${encodeURIComponent(r.id)}`}
                      className="font-mono text-sm text-pick no-underline hover:underline"
                    >
                      {r.id}
                    </Link>
                  </td>
                  <td className="rounded-[2px] bg-surface px-2 text-[13.5px]">{r.suite}</td>
                  <td className="truncate rounded-[2px] bg-surface px-2 text-sm text-dim">
                    {r.variants.map((v) => VARIANT_LABELS[v]).join(', ')}
                  </td>
                  <td className="rounded-[2px] bg-surface px-2 text-[13.5px]">
                    {r.status[0].toUpperCase() + r.status.slice(1)}
                  </td>
                  <td className="rounded-[2px] bg-surface px-2 text-sm text-dim">
                    {formatDateTime(r.started_at ?? r.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  )
}
