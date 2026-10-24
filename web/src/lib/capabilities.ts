// The Targets grid's rows: how each capability reads in a cell.
import type { TargetInfo } from '../api/types'
import { formatBytes, formatCount, formatUsd } from './format'

export type CellTone = 'ok' | 'warn' | 'err' | 'faint' | null

export interface CapabilityCell {
  text: string
  /** A second line under the text, for a down target's detail. */
  detail?: string
  tone: CellTone
}

export interface CapabilityRow {
  label: string
  cell: (target: TargetInfo) => CapabilityCell
}

const plain = (text: string): CapabilityCell => ({ text, tone: null })
const unknown: CapabilityCell = { text: 'Unknown', tone: 'faint' }

export function statusCell(target: TargetInfo): CapabilityCell {
  switch (target.status) {
    case 'ready':
      return { text: 'Ready', tone: 'ok' }
    case 'warning': {
      const warnings = target.warnings.map((w) => w.message).join('. ')
      return { text: 'Ready', detail: warnings || undefined, tone: 'warn' }
    }
    case 'down':
      return { text: target.reason ?? 'Down', detail: target.detail ?? undefined, tone: 'err' }
    case 'unchecked':
      return { text: 'Not checked', tone: 'faint' }
  }
}

function range(min: number | null | undefined, max: number | null | undefined): CapabilityCell {
  if (max == null) return unknown
  return plain(`${min ?? 1} to ${max}`)
}

export const CAPABILITY_ROWS: readonly CapabilityRow[] = [
  { label: 'Status', cell: statusCell },
  {
    label: 'Credentials',
    cell: (t) => {
      if (t.credential) return plain(t.credential)
      if (t.local) return plain('None, local')
      return t.status === 'unchecked' ? { text: 'Not checked', tone: 'faint' } : unknown
    },
  },
  { label: 'Probabilities', cell: (t) => plain(t.capabilities.probabilities ? 'Yes' : 'No') },
  {
    label: 'Images',
    cell: ({ capabilities: c }) => {
      if (!c.images) return plain('No')
      const parts = [c.max_images == null ? 'Yes' : `Up to ${c.max_images}`]
      if (c.max_total_image_bytes != null)
        parts.push(`${formatBytes(c.max_total_image_bytes)} total`)
      return plain(parts.join(', '))
    },
  },
  {
    label: 'Context window',
    cell: ({ capabilities: c }) => {
      const truncates = c.truncates_state ? 'truncates state' : null
      if (c.context_window == null) return truncates ? plain(`Unknown, ${truncates}`) : unknown
      const size = `${formatCount(c.context_window)} tokens`
      return plain(truncates ? `${size}, ${truncates}` : size)
    },
  },
  {
    label: 'Questions per request',
    cell: ({ capabilities: c }) => range(1, c.max_questions),
  },
  {
    label: 'Options or levels',
    cell: ({ capabilities: c }) => range(c.min_options ?? 2, c.max_options),
  },
  {
    label: 'Concurrency',
    cell: ({ capabilities: c }) => {
      const parts = [c.concurrency === 1 ? '1 at a time' : `${c.concurrency} at once`]
      if (c.concurrency_group) parts.push(`shared with ${c.concurrency_group}`)
      if (c.requests_per_minute != null)
        parts.push(`${formatCount(c.requests_per_minute)} requests a minute`)
      return plain(parts.join(', '))
    },
  },
  {
    label: 'Input cost per 1M tokens',
    cell: (t) => {
      if (t.local) return plain('Free')
      const cost = t.capabilities.input_cost_per_mtok_usd
      return cost == null ? unknown : plain(formatUsd(cost))
    },
  },
]
