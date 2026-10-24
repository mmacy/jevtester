import { expect, test } from '@playwright/test'

test('the Targets view shows every target and why any is down', async ({ page }) => {
  await page.goto('/targets')
  await expect(
    page.getByRole('link', { name: 'Target status: 4 of 8 targets ready' }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: /^Targets/ })).toContainText('4 of 8 ready')
  const status = page.getByRole('row', { name: /^Status/ })
  await expect(status.getByText("clef-flash isn't pulled")).toBeVisible()
  await expect(status.locator('[data-tone="err"]')).toHaveCount(4)
  await expect(status.locator('[data-tone="warn"]')).toHaveCount(3)
  await expect(page.getByRole('row', { name: /^Input cost per 1M tokens/ })).toContainText('$0.038')
})

test('targets start unchecked, and Check all targets runs the checks', async ({ page }) => {
  await page.route('**/api/targets', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-fixture': 'unchecked' } }),
  )
  await page.goto('/targets')
  await expect(page.getByRole('link', { name: 'Target status: Targets not checked' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /^Targets/ })).toContainText('Not checked')

  await page.getByRole('button', { name: 'Check all targets' }).click()
  await expect(
    page.getByRole('link', { name: 'Target status: 4 of 8 targets ready' }),
  ).toBeVisible()
  await expect(page.getByRole('row', { name: /^Status/ })).toContainText("clef-flash isn't pulled")
})

test('the health strip opens the Targets view', async ({ page }) => {
  await page.goto('/compare')
  await page.getByRole('link', { name: /^Target status/ }).click()
  await expect(page).toHaveURL(/\/targets$/)
})

test('an unreachable server shows a bar with a retry', async ({ page }) => {
  await page.route('**/api/targets', (route) => route.abort('connectionrefused'))
  await page.goto('/targets')
  const bar = page.getByRole('alert').filter({ hasText: "Can't reach the jevtester server" })
  await expect(bar).toBeVisible()

  await page.unroute('**/api/targets')
  await bar.getByRole('button', { name: 'Retry' }).click()
  await expect(bar).toBeHidden()
  await expect(page.getByRole('heading', { name: /^Targets/ })).toContainText('4 of 8 ready')
})
