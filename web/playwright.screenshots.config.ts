import { defineConfig, devices } from '@playwright/test'

// Captures the docs screenshots into docs/images/ (`npm run screenshots`).
// Like the e2e suite, it runs the UI in fixture mode on port 5174, so it needs
// no backend, no target, and no network. The CLI shots also need uv.
const PORT = 5174
const URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './screenshots',
  forbidOnly: !!process.env.CI,
  use: {
    baseURL: URL,
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: 'en-US',
    timezoneId: 'UTC',
  },
  webServer: {
    command: `npx vite --mode fixtures --port ${PORT} --strictPort`,
    url: URL,
    reuseExistingServer: !process.env.CI,
  },
})
