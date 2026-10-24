import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Without vitest globals, Testing Library can't register its own cleanup.
afterEach(() => {
  cleanup()
})
