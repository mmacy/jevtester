import { expect, test } from '@playwright/test'

test('the suite list links to each suite', async ({ page }) => {
  await page.goto('/suites')
  const row = page.getByRole('row', { name: /parley/ })
  await expect(row).toContainText('4')
  await expect(row).toContainText('1 draft')
  await row.getByRole('link', { name: 'parley' }).click()
  await expect(page).toHaveURL(/\/suites\/parley$/)
})

test('a suite shows its cases and their expected answers', async ({ page }) => {
  await page.goto('/suites/parley')
  await expect(page.getByRole('heading', { name: /^parley/ })).toContainText(
    '4 cases, policy parley',
  )
  const bribe = page.getByRole('row', { name: /^goblin-bribe/ })
  await expect(bribe).toContainText('parley')
  await expect(bribe).toContainText('Yes')
  await expect(bribe).toContainText('3±1Indifferent, may let them pass')
  await expect(page.getByRole('row', { name: /^hobgoblin-gold/ })).toContainText('Draft')
})

test('a case opens in compare with its questions and expected answers', async ({ page }) => {
  await page.goto('/suites/parley')
  await page.getByRole('button', { name: 'Open goblin-bribe in compare' }).click()
  await expect(page).toHaveURL(/\/compare$/)
  const form = page.getByRole('complementary', { name: 'Request' })
  await expect(form.getByLabel('State', { exact: true })).toHaveValue(/"player_says"/)
  await expect(form.getByLabel('Question id')).toHaveCount(3)
  await expect(form.getByRole('checkbox', { name: 'clef-flash@workers-ai' })).toBeChecked()

  await form.getByRole('button', { name: 'Ask 2 targets' }).click()
  const grid = page.getByRole('region', { name: 'Answers' })
  await expect(grid.getByRole('row', { name: /^parley/ })).toContainText('Expected')
})

test('a run starts with the chosen targets and version', async ({ page }) => {
  await page.goto('/suites/parley')
  await page.getByRole('button', { name: 'Start run' }).click()
  const dialog = page.getByRole('dialog', { name: 'Run parley' })
  await expect(dialog.getByRole('checkbox', { name: 'decision-1@foundry' })).toBeChecked()
  await expect(dialog.getByRole('checkbox', { name: 'clef-flash@workers-ai' })).toBeChecked()
  await expect(dialog.getByLabel('Question set version')).toHaveValue(/^95e251b7/)
  await dialog.getByRole('checkbox', { name: 'clef-flash@workers-ai' }).uncheck()
  await dialog.getByLabel('Repeats').fill('3')
  await dialog.getByLabel('Use cache').uncheck()

  const posted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/runs'))
  await dialog.getByRole('button', { name: 'Start run' }).click()
  expect((await posted).postDataJSON()).toEqual({
    suite: 'parley',
    targets: ['decision-1@foundry'],
    question_set_version: expect.stringMatching(/^95e251b7/),
    repeats: 3,
    no_cache: true,
  })
  await expect(page).toHaveURL(/\/runs\/0144$/)
})

test('a missing suite shows the error', async ({ page }) => {
  await page.route('**/api/suites/nowhere', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-fixture': '404' } }),
  )
  await page.goto('/suites/nowhere')
  await expect(page.getByRole('alert')).toContainText('not_found')
})
