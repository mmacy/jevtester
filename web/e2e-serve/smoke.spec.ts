import { expect, test } from '@playwright/test'

const VIEWS: [string, RegExp][] = [
  ['/compare', /Request/],
  ['/suites', /Suites/],
  ['/runs', /Runs/],
  ['/question-sets', /Question sets/],
  ['/policies', /Policies/],
  ['/probes', /Probe a suite/],
  ['/targets', /Check all targets/],
]

test('every view loads from the built UI, with nothing fetched from elsewhere', async ({
  page,
}) => {
  const problems: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push(`console: ${m.text()}`)
  })
  page.on('pageerror', (e) => problems.push(`page: ${e.message}`))
  page.on('request', (r) => {
    const url = new URL(r.url())
    if (url.hostname !== '127.0.0.1') problems.push(`external: ${r.url()}`)
  })
  for (const [path, text] of VIEWS) {
    await page.goto(path)
    await expect(page.locator('main')).toContainText(text)
  }
  expect(problems).toEqual([])
})

test('a deep link loads its view', async ({ page }) => {
  const suites = (await page.request.get('/api/suites').then((r) => r.json())) as {
    suites: { name: string }[]
  }
  test.skip(suites.suites.length === 0, 'No suites in suites/')
  const name = suites.suites[0].name
  await page.goto(`/suites/${name}`)
  await expect(page.getByRole('heading', { name: new RegExp(`^${name}`) })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start run' })).toBeVisible()
})
