import { heat, ink } from '../lib/heat'

interface HeatCellProps {
  /** The probability or share, from 0 to 1. */
  value: number
  /** Decimal places to show. */
  digits?: number
  /** Outline the cell as the chosen answer. */
  picked?: boolean
}

/** A matrix cell colored by the heat ramp, with its value and a thin bar. */
export function HeatCell({ value, digits = 4, picked = false }: HeatCellProps) {
  const width = `${Math.min(1, Math.max(0, value)) * 100}%`
  return (
    <td
      className={`relative h-[38px] rounded-[2px] px-2 text-right text-base ${
        picked ? 'font-[650] shadow-[inset_0_0_0_2px_var(--color-pick)]' : ''
      }`}
      style={{ background: heat(value), color: ink(value) }}
      data-picked={picked || undefined}
    >
      {value.toFixed(digits)}
      <span
        aria-hidden="true"
        className="absolute right-1.5 bottom-[5px] left-1.5 h-0.5 bg-white/12"
      >
        <i className="block h-full bg-current opacity-70" style={{ width }} />
      </span>
    </td>
  )
}
