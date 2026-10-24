import { useEffect, useState } from 'react'

/** Seconds since the component mounted, updated each second. */
export function useElapsed(): number {
  const [start] = useState(() => Date.now())
  const [now, setNow] = useState(start)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  return Math.floor((now - start) / 1000)
}
