import { expect, test } from '@playwright/test'

import { fixture } from './fixtures.ts'

const policy = fixture<{ name: string; yaml: string; thresholds: { name: string }[] }>(
  'get_policies_{name}.json',
)
const sweep = fixture<{ points: unknown[]; current: number; threshold: string }>(
  'post_policies_{name}_sweep.json',
)
const rejected = fixture<{ error: { details: { message: string }[] } }>(
  'put_policies_{name}.422.json',
)

test('the list links to each policy', async ({ page }) => {
  await page.goto('/policies')
  await page.getByRole('link', { name: policy.name }).click()
  await expect(page).toHaveURL(new RegExp(`/policies/${policy.name}$`))
})

test('a policy shows its YAML and thresholds', async ({ page }) => {
  await page.goto(`/policies/${policy.name}`)
  await expect(page.getByLabel('Policy YAML')).toHaveValue(policy.yaml)
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  const thresholds = page.getByRole('region', { name: 'Thresholds' })
  for (const t of policy.thresholds) {
    await expect(thresholds.getByRole('row', { name: new RegExp(`^${t.name}`) })).toBeVisible()
  }
})

test('a saved policy sends its YAML text', async ({ page }) => {
  await page.goto(`/policies/${policy.name}`)
  const edited = `${policy.yaml}\n# Tuned for Foundry\n`
  await page.getByLabel('Policy YAML').fill(edited)
  const put = page.waitForRequest(
    (r) => r.method() === 'PUT' && r.url().endsWith(`/api/policies/${policy.name}`),
  )
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  expect((await put).postDataJSON()).toEqual({ yaml: edited })
})

test('a rejected policy lists every error', async ({ page }) => {
  await page.route(`**/api/policies/${policy.name}`, (route) =>
    route.request().method() === 'PUT'
      ? route.continue({ headers: { ...route.request().headers(), 'x-fixture': '422' } })
      : route.continue(),
  )
  await page.goto(`/policies/${policy.name}`)
  await page.getByLabel('Policy YAML').fill('thresholds:\n  goodwill: high\n')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  const errors = page.getByRole('list', { name: 'Policy errors' })
  for (const d of rejected.error.details) await expect(errors).toContainText(d.message)
})

test('a sweep draws the trade-off and lists each point', async ({ page }) => {
  await page.goto(`/policies/${policy.name}`)
  const panel = page.getByRole('region', { name: 'Sweep' })
  await panel.getByLabel('Threshold').selectOption(sweep.threshold)
  const posted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/sweep'))
  await panel.getByRole('button', { name: 'Sweep', exact: true }).click()
  expect((await posted).postDataJSON()).toMatchObject({
    threshold: sweep.threshold,
    start: 0,
    stop: 1,
    step: 0.05,
  })
  await expect(
    panel.getByRole('img', { name: new RegExp(`against ${sweep.threshold}`) }),
  ).toBeVisible()
  await expect(panel.getByRole('table', { name: 'Sweep points' }).getByRole('row')).toHaveCount(
    sweep.points.length + 1,
  )
  await panel.getByTestId('sweep-hit').first().hover()
  await expect(panel.getByRole('tooltip')).toContainText('Decided')
  await expect(panel).toContainText('decision accuracy')
})

test('a run with a policy shows its decisions', async ({ page }) => {
  const run = fixture<{ id: string; policy: string }>('get_runs_{id}.json')
  await page.goto(`/runs/${run.id}`)
  const decisions = page.getByRole('region', { name: 'Decisions' })
  await expect(decisions).toContainText(`policy ${run.policy}`)
  await expect(decisions.getByRole('columnheader', { name: 'Decision accuracy' })).toBeVisible()

  await page.getByRole('link', { name: 'Step through changes' }).click()
  await expect(page.getByRole('row', { name: /^Action/ })).toBeVisible()
  await expect(page.getByRole('row', { name: /^Band/ })).toBeVisible()
})

test('a run decided with an earlier policy version says so', async ({ page }) => {
  const runs = fixture<{
    runs: { id: string; kind: string; status: string; policy_version: string | null }[]
  }>('get_runs.json').runs
  await page.route('**/api/runs', (route) =>
    route.fulfill({
      json: { runs: runs.map((r) => ({ ...r, policy_version: '0123456789abcdef' })) },
    }),
  )
  await page.goto(`/policies/${policy.name}`)
  await expect(page.getByRole('region', { name: 'Sweep' })).toContainText(
    'used policy version 0123456789ab',
  )
})
