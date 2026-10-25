import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { fixture } from '../e2e/fixtures.ts'

// Each test saves one PNG in docs/images/. docs/images/README.md lists them.
const IMAGES = new URL('../../docs/images/', import.meta.url)
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const NOW = new Date('2026-10-24T14:30:00Z')

interface Summary {
  id: string
  status: string
  counts: { jobs: number; done: number }
}

const run = fixture<Summary>('get_runs_{id}.json')
const probeRuns = fixture<{ runs: Summary[] }>('get_runs.json').runs
const probeReport = fixture<{ run_id: string }>('get_runs_{id}_probes.json')
const report = fixture<{ markdown: string }>('get_runs_{id}_report.json')

function imagePath(name: string): string {
  return fileURLToPath(new URL(name, IMAGES))
}

async function shoot(page: Page, name: string, fullPage = false) {
  // Park the pointer and drop focus, so no hover style or caret shows.
  await page.mouse.move(0, 899)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: imagePath(name), fullPage, animations: 'disabled' })
}

/** The run's event stream as [type, data] pairs, from the SSE fixture. */
function runEvents(): [string, string][] {
  const url = new URL('../../tests/fixtures/api/get_runs_{id}_events.sse', import.meta.url)
  return readFileSync(url, 'utf8')
    .split('\n\n')
    .filter((block) => block.trim())
    .map((block) => {
      const field = (name: string) =>
        block
          .split('\n')
          .find((line) => line.startsWith(`${name}: `))
          ?.slice(name.length + 2) ?? ''
      return [field('event'), field('data')]
    })
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW)
})

test('compare', async ({ page }) => {
  await page.goto('/suites/parley')
  await page.getByRole('button', { name: 'Open goblin-bribe in compare' }).click()
  const form = page.getByRole('complementary', { name: 'Request' })
  await form.getByRole('button', { name: 'Ask 2 targets' }).click()
  const grid = page.getByRole('region', { name: 'Answers' })
  await expect(grid.getByRole('columnheader', { name: /clef-flash@workers-ai/ })).toBeVisible()
  await expect(grid.getByRole('row', { name: /^parley/ })).toContainText('Expected')
  // Clicking Ask scrolls the request panel to its foot. Show both panels from the top.
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    document.querySelectorAll('*').forEach((el) => {
      el.scrollTop = 0
    })
  })
  await shoot(page, 'compare.png')
})

test('targets', async ({ page }) => {
  await page.goto('/targets')
  await expect(page.getByRole('heading', { name: /^Targets/ })).toContainText('4 of 8 ready')
  await shoot(page, 'targets.png')
})

test('suite', async ({ page }) => {
  await page.goto('/suites/parley')
  await expect(page.getByRole('row', { name: /^goblin-bribe/ })).toBeVisible()
  await shoot(page, 'suite.png')
})

test('runs', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('link', { name: run.id, exact: true })).toBeVisible()
  await shoot(page, 'runs.png')
})

test('run in progress', async ({ page }) => {
  // Stop the event stream partway: a stand-in EventSource sends the fixture's
  // events up to the eighth finished job, then stays open.
  const events = runEvents()
  const cut = events.findIndex(([, data]) => JSON.parse(data).counts?.done >= 8)
  await page.addInitScript(
    (sent: [string, string][]) => {
      class HeldEventSource extends EventTarget {
        static readonly CONNECTING = 0
        static readonly OPEN = 1
        static readonly CLOSED = 2
        readyState = 1
        onerror: (() => void) | null = null
        constructor() {
          super()
          setTimeout(() => {
            for (const [type, data] of sent) this.dispatchEvent(new MessageEvent(type, { data }))
          }, 0)
        }
        close() {
          this.readyState = 2
        }
      }
      Object.defineProperty(window, 'EventSource', { value: HeldEventSource })
    },
    events.slice(0, cut + 1),
  )
  await page.route(`**/api/runs/${run.id}`, (route) =>
    route.fulfill({
      json: { ...run, status: 'running', finished_at: null, counts: { ...run.counts, done: 0 } },
    }),
  )
  await page.goto(`/runs/${run.id}`)
  await expect(page.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
    'aria-valuenow',
    '8',
  )
  await shoot(page, 'run-in-progress.png')
})

test('run report', async ({ page }) => {
  await page.goto(`/runs/${run.id}`)
  await expect(page.getByTestId('run-status')).toContainText('Finished')
  await expect(page.getByRole('region', { name: 'Changed answers' })).toContainText('Fixed')
  await shoot(page, 'run-report.png', true)
})

test('changes', async ({ page }) => {
  await page.goto(`/runs/${run.id}`)
  await page.getByRole('link', { name: 'Step through changes' }).click()
  await expect(page.getByRole('row', { name: /^Action/ })).toBeVisible()
  await shoot(page, 'changes.png')
})

test('question set', async ({ page }) => {
  await page.goto('/question-sets/parley')
  await expect(page.getByRole('region', { name: 'Versions' })).toContainText('Current')
  await shoot(page, 'question-set.png')
})

test('question set diff', async ({ page }) => {
  await page.goto('/question-sets/parley')
  await page.getByRole('button', { name: 'Compare with current' }).click()
  await expect(page.getByRole('region', { name: 'Question intent' })).toContainText('Changed')
  await shoot(page, 'question-set-diff.png')
})

test('policy sweep', async ({ page }) => {
  await page.goto('/policies/parley')
  const panel = page.getByRole('region', { name: 'Sweep' })
  await panel.getByRole('button', { name: 'Sweep', exact: true }).click()
  await expect(panel.getByRole('table', { name: 'Sweep points' })).toBeVisible()
  await expect(panel.getByRole('img', { name: /against goodwill/ })).toBeVisible()
  await shoot(page, 'policy-sweep.png')
})

test('probe report', async ({ page }) => {
  const summary = probeRuns.find((r) => r.id === probeReport.run_id)
  await page.route(`**/api/runs/${probeReport.run_id}`, (route) =>
    route.fulfill({ json: { ...summary, status: 'finished' } }),
  )
  await page.goto(`/runs/${probeReport.run_id}`)
  await expect(page.getByRole('region', { name: 'Probes' })).toBeVisible()
  await shoot(page, 'probe-report.png')
})

// The CLI shots draw a command and its output as a terminal, in the UI's mono font.
const MONO = readFileSync(
  new URL(
    '../node_modules/@fontsource/noto-sans-mono/files/noto-sans-mono-latin-400-normal.woff2',
    import.meta.url,
  ),
).toString('base64')

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

async function shootTerminal(page: Page, name: string, command: string, output: string) {
  await page.setViewportSize({ width: 1100, height: 400 })
  await page.setContent(`<!doctype html>
<style>
  @font-face { font-family: 'Noto Sans Mono'; src: url(data:font/woff2;base64,${MONO}) format('woff2'); }
  body { margin: 0; background: #102029; }
  pre { margin: 0; padding: 20px 24px; font: 14px/1.5 'Noto Sans Mono', monospace; color: #dbe8ef; }
  .prompt { color: #8fd3b0; }
</style>
<pre><span class="prompt">$</span> ${escapeHtml(command)}
${escapeHtml(output.trimEnd())}</pre>`)
  await page.evaluate(() => document.fonts.ready)
  await page
    .locator('pre')
    .screenshot({ path: imagePath(name), animations: 'disabled', omitBackground: false })
}

test('cli targets list', async ({ page }) => {
  // `targets list` reads the config only; it asks no target anything.
  const output = execFileSync(
    'uv',
    ['run', 'jevtester', '--config', 'jevtester.toml', 'targets', 'list'],
    { cwd: ROOT, encoding: 'utf8' },
  )
  await shootTerminal(page, 'cli-targets-list.png', 'jevtester targets list', output)
})

test('cli report', async ({ page }) => {
  // The fixture's markdown is what `jevtester report` prints for run 0002.
  await shootTerminal(page, 'cli-report.png', `jevtester report ${run.id}`, report.markdown)
})
