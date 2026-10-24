import { useEffect, useId, type ReactNode } from 'react'

/** A modal panel over the page. Escape closes it. */
export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const titleId = useId()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-20 flex items-start justify-center overflow-y-auto bg-black/50 p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="mt-16 w-full max-w-[560px] rounded border border-line bg-surface p-5"
      >
        <h2
          id={titleId}
          className="m-0 mb-3.5 font-display text-[22px] font-bold [font-stretch:75%]"
        >
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}
