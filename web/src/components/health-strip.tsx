import { Link } from 'react-router-dom'

import type { TargetInfo, TargetStatus } from '../api/types'
import { healthSummary } from '../lib/health'

const BLOCK: Record<TargetStatus, string> = {
  ready: 'bg-ok',
  warning: 'bg-warn',
  down: 'bg-err',
  unchecked: 'bg-line',
}

/** One block per target, colored by status, linking to the Targets view. */
export function HealthStrip({ targets }: { targets: readonly TargetInfo[] }) {
  const summary = healthSummary(targets)
  return (
    <Link
      to="/targets"
      aria-label={`Target status: ${summary}`}
      className="flex items-center gap-1 text-sm text-dim no-underline hover:text-text"
    >
      {targets.map((target) => (
        <span
          key={target.name}
          title={`${target.name}: ${target.status}`}
          data-status={target.status}
          className={`h-2 w-[22px] ${BLOCK[target.status]}`}
        />
      ))}
      <em className="ml-2 not-italic">{summary}</em>
    </Link>
  )
}
