/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

import { fixtureServer } from './fixture-server.ts'

const FIXTURE_DIR =
  process.env.JEVTESTER_FIXTURES ?? fileURLToPath(new URL('../tests/fixtures/api', import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === 'fixtures' ? [fixtureServer(FIXTURE_DIR)] : [])],
  build: {
    // `jevtester serve` serves the built UI from here. Git ignores it.
    outDir: '../src/jevtester/static',
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: mode === 'fixtures' ? undefined : { '/api': 'http://127.0.0.1:8640' },
  },
  test: {
    // Pure-logic tests run in node. Component tests opt into jsdom with a
    // `// @vitest-environment jsdom` pragma.
    environment: 'node',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', '*.test.ts'],
  },
}))
