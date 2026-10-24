import { defineConfig, devices } from '@playwright/test'

// The built UI as `jevtester serve` ships it, against the real API and the
// repository's config. It's opt-in (`npm run e2e:serve`), since it needs uv
// and a build. It asks no target anything: the specs run no health check,
// decide, or run. The server itself still writes .jevtester/runs.sqlite as it
// starts. Port 8645 keeps it clear of a server on 8640 and of other local
// tools.
const PORT = 8645
const URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e-serve',
  forbidOnly: !!process.env.CI,
  use: { baseURL: URL, ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `uv run jevtester serve --port ${PORT}`,
    cwd: '..',
    url: `${URL}/api/targets`,
    reuseExistingServer: false,
  },
})
