import type { ButtonHTMLAttributes } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  primary?: boolean
}

export function Button({ primary = false, className = '', type = 'button', ...rest }: ButtonProps) {
  const look = primary
    ? 'border-pick bg-pick font-[650] text-pick-ink'
    : 'border-line bg-raise font-medium hover:border-faint'
  return (
    <button
      type={type}
      className={`cursor-pointer rounded border px-3.5 py-[7px] disabled:cursor-default disabled:opacity-50 ${look} ${className}`}
      {...rest}
    />
  )
}
