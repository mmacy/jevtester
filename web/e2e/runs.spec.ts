import { expect, test, type Page } from '@playwright/test'

import { fixture } from './fixtures.ts'

interface Summary {
  id: string
  status: string
  baseline: string | null
  counts: { jobs: number; done: number }
}

const runs = fixture<{ runs: Summary[] }>('get_runs.json').runs
const run = fixture<Summary>('get_runs_{id}.json')
const created = fixture<{ id: string }>('post_runs.json')
const changes = fixture<{ changes: { case_id: string }[] }>('get_runs_{id}_changes.json').changes
const regressions = fixture<{ regressions: unknown[] }>('get_runs_{id}_compare.json').regressions

/** Serves the run as if it were still running, so the page follows its event stream. */
async function serveRunning(page: Page) {
  await page.route(`**/api/runs/${run.id}`, (route) =>
    route.fulfill({
      json: { ...run, status: 'running', finished_at: null, counts: { ...run.counts, done: 0 } },
    }),
  )
}

test('the run list shows each run and its progress', async ({ page }) => {
  await page.goto('/runs')
  for (const r of runs) {
    await expect(page.getByRole('row', { name: new RegExp(`^${r.id}`) })).toContainText(
      `${r.counts.done}/${r.counts.jobs}`,
    )
  }
  await page.getByRole('link', { name: run.id, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/runs/${run.id}$`))
})

test('a finished run shows its metrics, confusion matrix, calibration, and changes', async ({
  page,
}) => {
  await page.goto(`/runs/${run.id}`)
  await expect(page.getByRole('heading', { name: `Run ${run.id}` })).toBeVisible()
  await expect(page.getByTestId('run-status')).toContainText('Finished')
  await expect(page.getByRole('button', { name: 'Rerun without cache' })).toBeVisible()

  const metrics = page.getByRole('region', { name: 'Metrics' })
  const grid = metrics.getByRole('table').first()
  await expect(grid.getByRole('columnheader', { name: 'Accuracy', exact: true })).toBeVisible()
  await expect(grid.getByRole('row', { name: /^decision-1@foundry/ })).toBeVisible()
  await metrics.getByRole('button', { name: 'bribe' }).click()
  await expect(grid.getByRole('columnheader', { name: 'Brier score' })).toBeVisible()

  const confusion = page.getByRole('region', { name: 'Confusion matrix' })
  await expect(confusion).toContainText('correct')
  await expect(confusion).toContainText('Lowest recall')

  const calibration = page.getByRole('region', { name: 'Calibration' })
  await expect(calibration).toContainText('Expected calibration error')

  const changed = page.getByRole('region', { name: 'Changed answers' })
  await expect(changed.getByLabel('Baseline')).toHaveValue(run.baseline ?? '')
  await expect(changed).toContainText('Fixed')
  await expect(changed).toContainText(regressions.length ? 'Regression' : 'No regressions')
})

test('a running run follows its events to the end', async ({ page }) => {
  await serveRunning(page)
  await page.goto(`/runs/${run.id}`)
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible()
  await expect(page.getByTestId('run-status')).toContainText('Finished', { timeout: 15_000 })
  await expect(page.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
    'aria-valuenow',
    String(run.counts.jobs),
  )
})

test('a running run cancels', async ({ page }) => {
  await serveRunning(page)
  await page.goto(`/runs/${run.id}`)
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByTestId('run-status')).toContainText('Cancelled')
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeHidden()
})

test('a rerun without cache starts a new run', async ({ page }) => {
  await page.goto(`/runs/${run.id}`)
  const posted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/runs'))
  await page.getByRole('button', { name: 'Rerun without cache' }).click()
  expect((await posted).postDataJSON()).toMatchObject({ no_cache: true, baseline: run.baseline })
  await expect(page).toHaveURL(new RegExp(`/runs/${created.id}$`))
})

test('stepping through changes shows each case in both runs', async ({ page }) => {
  await page.goto(`/runs/${run.id}`)
  await page.getByRole('link', { name: 'Step through changes' }).click()
  const first = changes[0].case_id
  await expect(page.getByRole('heading', { name: new RegExp(`^${first}`) })).toBeVisible()
  await expect(
    page.getByRole('columnheader', { name: new RegExp(`Run ${run.baseline}`) }).first(),
  ).toBeVisible()
  await expect(
    page.getByRole('columnheader', { name: new RegExp(`Run ${run.id}`) }).first(),
  ).toBeVisible()
  const ids = [...new Set(changes.map((c) => c.case_id))]
  if (ids.length > 1) {
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('heading', { name: new RegExp(`^${ids[1]}`) })).toBeVisible()
    await page.getByRole('button', { name: 'Previous' }).click()
    await expect(page.getByRole('heading', { name: new RegExp(`^${first}`) })).toBeVisible()
  }
})

test('an unknown run shows the error', async ({ page }) => {
  await page.route('**/api/runs/9999', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-fixture': '404' } }),
  )
  await page.goto('/runs/9999')
  await expect(page.getByRole('alert')).toContainText('not_found')
})

test('a regression shows above the changed answers', async ({ page }) => {
  const comparison = fixture<Record<string, unknown>>('get_runs_{id}_compare.json')
  await page.route(`**/api/runs/${run.id}/compare?*`, (route) =>
    route.fulfill({
      json: {
        ...comparison,
        regressions: [
          {
            target: 'decision-1@foundry',
            question: 'intent',
            metric: 'accuracy',
            baseline: 1,
            value: 0.75,
            drop: 0.25,
          },
        ],
      },
    }),
  )
  await page.goto(`/runs/${run.id}`)
  await expect(page.getByRole('list', { name: 'Regressions' })).toContainText(
    'Regression decision-1@foundry, intent accuracy 1.000 to 0.750, down 0.250',
  )
})
