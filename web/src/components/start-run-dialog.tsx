import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { Suite } from '../api/types'
import { useLoad } from '../hooks/use-load'
import { formatDateTime, shortVersion } from '../lib/format'
import { useTargets } from '../store/targets'
import { ApiErrorState } from './api-error'
import { Button } from './button'
import { Dialog } from './dialog'
import { FieldLabel } from './fields'
import { Spinner } from './states'
import { TargetPicker } from './target-picker'

const SELECT =
  'w-full rounded border border-line bg-bg px-2 py-1.5 text-sm focus:border-pick focus:outline-none'

/** Picks targets, a question set version, repeats, and the cache, then starts a run of a suite. */
export function StartRunDialog({ suite, onClose }: { suite: Suite; onClose: () => void }) {
  const navigate = useNavigate()
  const allTargets = useTargets((s) => s.targets) ?? []
  const defaults = useTargets((s) => s.defaultTargets)
  const [targets, setTargets] = useState<string[]>(
    suite.targets.length > 0 ? suite.targets : defaults,
  )
  const versions = useLoad(() => api.listVersions(suite.question_set), suite.question_set)
  const [version, setVersion] = useState<string | null>(null)
  const [repeats, setRepeats] = useState(1)
  const [useCache, setUseCache] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const current = versions.data?.versions.find((v) => v.current)?.version ?? null
  const chosen = version ?? current

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      const run = await api.startRun({
        suite: suite.name,
        targets,
        question_set_version: chosen,
        repeats,
        no_cache: !useCache,
      })
      navigate(`/runs/${encodeURIComponent(run.id)}`)
    } catch (e) {
      setError(e)
      setStarting(false)
    }
  }

  return (
    <Dialog title={`Run ${suite.name}`} onClose={onClose}>
      <div className="space-y-3">
        {error ? <ApiErrorState error={error} /> : null}
        <div>
          <span className="text-sm text-dim">Targets</span>
          <TargetPicker targets={allTargets} selected={targets} onChange={setTargets} />
        </div>
        <div>
          <FieldLabel htmlFor="run-version">Question set version</FieldLabel>
          {versions.error ? (
            <ApiErrorState error={versions.error} onRetry={versions.reload} />
          ) : (
            <select
              id="run-version"
              className={SELECT}
              disabled={!versions.data}
              value={chosen ?? ''}
              onChange={(e) => setVersion(e.target.value)}
            >
              {(versions.data?.versions ?? []).map((v) => (
                <option key={v.version} value={v.version}>
                  {shortVersion(v.version)}, {formatDateTime(v.first_seen)}
                  {v.current ? ', current' : ''}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-5">
          <label className="flex items-center gap-2 text-sm text-dim">
            Repeats
            <input
              type="number"
              min={1}
              value={repeats}
              onChange={(e) => setRepeats(Math.max(1, Math.floor(Number(e.target.value)) || 1))}
              className="w-16 rounded border border-line bg-bg px-1.5 py-1 text-sm text-text"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="accent-pick"
              checked={useCache}
              onChange={(e) => setUseCache(e.target.checked)}
            />
            Use cache
          </label>
        </div>
        <div className="flex items-center gap-2.5 pt-1">
          <Button
            primary
            onClick={() => void start()}
            disabled={starting || targets.length === 0 || !chosen}
          >
            Start run
          </Button>
          <Button onClick={onClose}>Cancel</Button>
          {starting || versions.loading ? (
            <Spinner label={starting ? 'Starting run' : 'Loading versions'} />
          ) : null}
        </div>
      </div>
    </Dialog>
  )
}
