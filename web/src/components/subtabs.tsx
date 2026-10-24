interface SubtabsProps {
  label: string
  options: readonly string[]
  value: string | null
  onChange: (value: string) => void
}

/** Small toggle buttons that pick one of several, like a question or a target. */
export function Subtabs({ label, options, value, onChange }: SubtabsProps) {
  return (
    <div role="group" aria-label={label} className="mb-2.5 inline-flex flex-wrap gap-0.5">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
          className="cursor-pointer rounded-[3px] border border-line bg-surface px-2.5 py-0.5 text-sm text-dim aria-pressed:border-pick aria-pressed:text-text"
        >
          {option}
        </button>
      ))}
    </div>
  )
}
