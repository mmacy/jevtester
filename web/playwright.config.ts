import { defineConfig, devices } from '@playwright/test'

// Port 5174 keeps the suite clear of a developer's dev server on 5173. The
// suite runs in fixture mode, so it needs no backend.
const PORT = 5174
const URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  forbidOnly: !!process.env.CI,
  use: { baseURL: URL, ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `npx vite --mode fixtures --port ${PORT} --strictPort`,
    url: URL,
    reuseExistingServer: !process.env.CI,
  },
})
