// The jevtester mark: a 3 by 3 heat grid beside the condensed name.
const CELLS = [
  '#c8ecd9',
  '#2f7f93',
  '#1f4a5e',
  '#63b7b8',
  '#c8ecd9',
  '#2f7f93',
  '#1f4a5e',
  '#2f7f93',
  '#c8ecd9',
]

export function Mark() {
  return (
    <div className="flex items-center gap-2 font-display text-[26px] leading-none font-extrabold tracking-[0.01em] [font-stretch:62.5%]">
      <span aria-hidden="true" className="inline-grid grid-cols-[repeat(3,6px)] gap-0.5">
        {CELLS.map((color, i) => (
          <b key={i} className="block size-1.5" style={{ background: color }} />
        ))}
      </span>
      jevtester
    </div>
  )
}
