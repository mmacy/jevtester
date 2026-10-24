import type { ReactNode } from 'react'

export function PanelHeading({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <h2 className="m-0 mb-3.5 flex items-baseline gap-3 font-display text-[22px] font-bold tracking-[0.005em] [font-stretch:75%]">
      {children}
      {note ? (
        <small className="font-sans text-sm font-normal text-dim [font-stretch:100%]">{note}</small>
      ) : null}
    </h2>
  )
}
