import { expect, test } from '@playwright/test'

test('the app opens on Compare with every view in the tabs', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/compare$/)
  await expect(page.getByRole('heading', { name: 'Compare' })).toBeVisible()
  const tabs = page.getByRole('navigation', { name: 'Views' }).getByRole('link')
  await expect(tabs).toHaveText([
    'Compare',
    'Suites',
    'Runs',
    'Question sets',
    'Policies',
    'Probes',
    'Targets',
  ])
})

test('a view reloads from its URL', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('heading', { name: 'Runs' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Runs' })).toHaveAttribute('aria-current', 'page')
})

test('the Noto fonts load from the app', async ({ page }) => {
  const external: string[] = []
  page.on('request', (request) => {
    if (!request.url().startsWith('http://127.0.0.1')) external.push(request.url())
  })
  await page.goto('/')
  const loaded = await page.evaluate(() =>
    Promise.all(
      ['Noto Sans Variable', 'Noto Sans Display Variable', 'Noto Sans Mono'].map(
        async (family) => (await document.fonts.load(`16px "${family}"`)).length > 0,
      ),
    ),
  )
  expect(loaded).toEqual([true, true, true])
  expect(external).toEqual([])
})

test('fixture mode answers an unknown endpoint with the error envelope', async ({ request }) => {
  const response = await request.get('/api/no-such-endpoint')
  expect(response.status()).toBe(404)
  expect(await response.json()).toEqual({
    error: { code: 'not_found', message: 'No fixture for GET /api/no-such-endpoint' },
  })
})
