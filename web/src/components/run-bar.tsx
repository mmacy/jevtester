import type { RunSummary } from '../api/types'
import { formatUsd, shortVersion } from '../lib/format'
import { formatDuration, isActive, progressSegments, type SegmentKind } from '../lib/run'
import { Button } from './button'
import { Spinner } from './states'

const SEGMENT: Record<SegmentKind, string> = {
  sent: '#63b7b8',
  cached: '#2f7f93',
  failed: 'var(--color-err)',
  skipped: 'repeating-linear-gradient(135deg,#3b2626 0 4px,#152a35 4px 8px)',
}

const KEY: Record<SegmentKind, string> = {
  sent: '#63b7b8',
  cached: '#2f7f93',
  failed: 'var(--color-err)',
  skipped: 'var(--color-err)',
}

const STATUS: Record<RunSummary['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  finished: 'Finished',
  cancelled: 'Cancelled',
  failed: 'Failed',
}

interface RunBarProps {
  run: RunSummary
  reconnecting: boolean
  cancelling: boolean
  onCancel: () => void
  onRerun: () => void
}

/** A run's facts and progress, with cancel while it runs and rerun once it ends. */
export function RunBar({ run, reconnecting, cancelling, onCancel, onRerun }: RunBarProps) {
  const active = isActive(run.status)
  const segments = progressSegments(run.counts)
  const ended =
    run.finished_at && run.started_at ? formatDuration(run.started_at, run.finished_at) : null
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-[18px] rounded border border-line bg-surface px-4 py-3.5">
      <h2 className="m-0 font-display text-[30px] leading-none font-extrabold [font-stretch:70%]">
        Run {run.id}
      </h2>
      <div className="flex flex-wrap gap-x-[22px] gap-y-1 text-[13px] text-dim">
        <span>
          Suite <b className="font-semibold text-text">{run.suite}</b>
        </span>
        <span>
          Question set{' '}
          <b className="font-semibold text-text">{shortVersion(run.question_set_version)}</b>
          {run.baseline ? (
            <>
              {' '}
              against baseline <b className="font-semibold text-text">{run.baseline}</b>
            </>
          ) : null}
        </span>
        {run.kind === 'probe' ? <span>Probe run</span> : null}
        <span>
          <b className="font-semibold text-text">{run.case_count}</b> cases
        </span>
        <span>
          <b className="font-semibold text-text">{run.counts.jobs}</b> jobs
        </span>
        <span data-testid="run-status">
          {STATUS[run.status]}
          {ended ? (
            <>
              {' '}
              in <b className="font-semibold text-text">{ended}</b>
            </>
          ) : null}
        </span>
        <span>
          Cost{' '}
          <b className="font-semibold text-text">
            {run.cost_usd == null ? 'Unknown' : formatUsd(run.cost_usd)}
          </b>
        </span>
        {reconnecting ? <span className="text-warn">Reconnecting</span> : null}
      </div>
      {active ? (
        <span className="flex items-center gap-2">
          {cancelling ? <Spinner label="Cancelling" /> : null}
          <Button onClick={onCancel} disabled={cancelling}>
            Cancel
          </Button>
        </span>
      ) : (
        <Button onClick={onRerun}>Rerun without cache</Button>
      )}
      <div
        className="col-span-full flex h-1.5 overflow-hidden rounded-[3px] bg-bg"
        role="progressbar"
        aria-label="Progress"
        aria-valuemin={0}
        aria-valuemax={run.counts.jobs}
        aria-valuenow={run.counts.done}
        aria-valuetext={segments.map((s) => s.label).join(', ') || 'Nothing done'}
      >
        {segments.map((s) => (
          <i
            key={s.kind}
            className="block h-full"
            style={{ width: `${s.share * 100}%`, background: SEGMENT[s.kind] }}
          />
        ))}
      </div>
      <div className="col-span-full -mt-2 flex flex-wrap gap-[18px] text-xs text-dim">
        <span>
          {run.counts.done} of {run.counts.jobs} done
        </span>
        {segments.map((s) => (
          <span key={s.kind} className="flex items-center gap-1.5">
            <i className="inline-block h-1.5 w-2.5" style={{ background: KEY[s.kind] }} />
            {s.label}
          </span>
        ))}
        {error(run)}
      </div>
    </div>
  )
}

function error(run: RunSummary) {
  if (!run.error) return null
  return (
    <span className="text-err">
      {run.error.code}: {run.error.message}
    </span>
  )
}
