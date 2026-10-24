interface SegmentedProps<T extends string> {
  label: string
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}

/** A row of toggle buttons where one is pressed. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: SegmentedProps<T>) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex shrink-0 overflow-hidden rounded border border-line text-xs"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className="cursor-pointer px-2 py-0.5 whitespace-nowrap text-dim aria-pressed:bg-line aria-pressed:text-text"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
