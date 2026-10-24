// Form controls styled from the mockup.
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'

const FIELD =
  'w-full rounded border border-line bg-bg px-2.5 py-2 text-base leading-normal focus:border-pick focus:outline-none'

export function TextInput({ className = '', ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="text" className={`${FIELD} ${className}`} {...rest} />
}

export function TextArea({ className = '', ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${FIELD} resize-y ${className}`} {...rest} />
}

export function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm text-dim">
      {children}
    </label>
  )
}

export function FieldErrors({ errors }: { errors: readonly string[] | undefined }) {
  if (!errors || errors.length === 0) return null
  return (
    <ul className="m-0 mt-1 list-none p-0 text-sm text-err">
      {errors.map((error) => (
        <li key={error}>{error}</li>
      ))}
    </ul>
  )
}

/** A small square button for a row action, like moving or removing an option. */
export function IconButton({
  label,
  children,
  ...rest
}: { label: string; children: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className="size-7 shrink-0 cursor-pointer rounded border border-line-soft text-dim hover:border-faint hover:text-text disabled:cursor-default disabled:opacity-40"
      {...rest}
    >
      {children}
    </button>
  )
}
