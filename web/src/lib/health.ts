import type { TargetInfo } from '../api/types'
import { isReady } from '../store/targets'

/** The health strip's count line. */
export function healthSummary(targets: readonly TargetInfo[]): string {
  if (targets.length === 0) return 'No targets'
  if (targets.every((t) => t.status === 'unchecked')) return 'Targets not checked'
  return `${targets.filter(isReady).length} of ${targets.length} targets ready`
}
