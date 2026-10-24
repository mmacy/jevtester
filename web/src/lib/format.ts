// Display formats shared across views.

/** A local clock time, like `14:02`. */
export function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** A byte count in the largest whole binary unit, like `4 MiB`. */
export function formatBytes(bytes: number): string {
  const units = ['bytes', 'KiB', 'MiB', 'GiB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  const shown = Number.isInteger(value) ? value.toString() : value.toFixed(1)
  return `${shown} ${units[unit]}`
}

/** A whole number with thousands separators, like `24,576`. */
export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

/** A dollar amount, with enough digits to show a fraction of a cent. */
export function formatUsd(value: number): string {
  if (value === 0) return '$0'
  if (value >= 0.01) return `$${value.toFixed(value >= 1 ? 2 : 3)}`
  return `$${value.toPrecision(2)}`
}
