import { expect, test } from '@playwright/test'

import { fixture } from './fixtures.ts'

interface Report {
  run_id: string
  variants: string[]
  cells: { case_id: string; target: string; variant: string; changed: number; instances: number }[]
}

const report = fixture<Report>('get_runs_{id}_probes.json')
const created = fixture<{ id: string }>('post_probes.json')
const runs = fixture<{ runs: { id: string; kind: string; status: string }[] }>('get_runs.json').runs

const LABELS: Record<string, string> = {
  option_order: 'Option order',
  key_order: 'JSON key order',
  bare_levels: 'Bare-number levels',
  pad_state: 'State padding',
}

test('probes start with the chosen variants and open their run', async ({ page }) => {
  await page.goto('/probes')
  const form = page.getByRole('form', { name: 'Probe' })
  await expect(form.getByLabel('Suite')).toHaveValue('parley')
  await expect(form.getByRole('checkbox', { name: 'Paraphrase' })).toBeDisabled()
  await form.getByRole('checkbox', { name: 'State padding' }).check()
  await form.getByRole('checkbox', { name: 'JSON key order' }).uncheck()

  const posted = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/api/probes'),
  )
  await form.getByRole('button', { name: 'Start probes' }).click()
  expect((await posted).postDataJSON()).toMatchObject({
    suite: 'parley',
    variants: ['option_order', 'bare_levels', 'pad_state'],
    no_cache: false,
  })
  await expect(page).toHaveURL(new RegExp(`/runs/${created.id}$`))
})

test('the probe runs list links to each probe run', async ({ page }) => {
  await page.goto('/probes')
  for (const r of runs.filter((r) => r.kind === 'probe')) {
    await expect(page.getByRole('link', { name: r.id, exact: true })).toBeVisible()
  }
})

test('a probe run shows each case under each variant', async ({ page }) => {
  // Fixture mode has one run summary, a suite run, so serve the probe run's
  // summary from the run list, as finished so the page doesn't follow events.
  const summary = runs.find((r) => r.id === report.run_id)
  await page.route(`**/api/runs/${report.run_id}`, (route) =>
    route.fulfill({ json: { ...summary, status: 'finished' } }),
  )
  await page.goto(`/runs/${report.run_id}`)
  const probes = page.getByRole('region', { name: 'Probes' })
  for (const v of report.variants) {
    await expect(probes.getByRole('columnheader', { name: LABELS[v] }).first()).toBeVisible()
  }
  const first = report.cells[0]
  const row = probes.getByRole('row', { name: new RegExp(`^${first.case_id}`) })
  await expect(row).toContainText(`${first.changed} of ${first.instances}`)
  await expect(probes.getByRole('row', { name: /^Change rate/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Metrics' })).toHaveCount(0)

  await row.getByRole('button').first().click()
  await expect(page.getByRole('region', { name: 'Variants' })).toContainText(first.case_id)
})
