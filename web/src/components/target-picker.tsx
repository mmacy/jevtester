import type { TargetInfo } from '../api/types'

interface TargetPickerProps {
  targets: readonly TargetInfo[]
  selected: readonly string[]
  onChange: (selected: string[]) => void
}

/** A checkbox per target. A down target can't be checked, and shows why. */
export function TargetPicker({ targets, selected, onChange }: TargetPickerProps) {
  const toggle = (name: string, on: boolean) => {
    const next = new Set(selected)
    if (on) next.add(name)
    else next.delete(name)
    // Keep the config's order.
    onChange(targets.map((t) => t.name).filter((n) => next.has(n)))
  }
  return (
    <fieldset className="m-0 mt-2 grid gap-1 border-0 p-0">
      <legend className="sr-only">Targets</legend>
      {targets.map((target) => {
        const down = target.status === 'down'
        return (
          <label
            key={target.name}
            className={`flex items-center gap-2 rounded border border-line-soft px-2 py-1 text-[13px] ${down ? 'text-faint' : ''}`}
          >
            <input
              type="checkbox"
              className="accent-pick"
              disabled={down}
              checked={!down && selected.includes(target.name)}
              onChange={(e) => toggle(target.name, e.target.checked)}
            />
            <span className="shrink-0 whitespace-nowrap">{target.name}</span>
            {down ? (
              <small
                className="ml-auto min-w-0 truncate text-xs text-err"
                title={target.reason ?? undefined}
              >
                {target.reason}
              </small>
            ) : null}
          </label>
        )
      })}
    </fieldset>
  )
}
