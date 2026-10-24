import { heatGradient } from '../lib/heat'

interface HeatKeyProps {
  label: string
  low?: string
  high?: string
  /** Show the gold outline that marks a chosen answer. */
  showPick?: boolean
}

/** The legend for a heat grid: what the ramp measures, its ends, and the pick outline. */
export function HeatKey({ label, low = '0', high = '1', showPick = false }: HeatKeyProps) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-dim">
      <span>{label}</span>
      <span>{low}</span>
      <span
        data-testid="heat-ramp"
        className="h-2.5 w-[120px] rounded-[2px]"
        style={{ background: heatGradient() }}
      />
      <span>{high}</span>
      {showPick ? (
        <>
          <span className="ml-3 h-2.5 w-3.5 border-2 border-pick" />
          <span>Chosen answer</span>
        </>
      ) : null}
    </div>
  )
}
