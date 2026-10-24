import { expect, test, type Page } from '@playwright/test'

import { fixture } from './fixtures.ts'

const conflict = fixture<{ error: { details: { message: string }[] } }>(
  'post_suites_{name}_cases.409.json',
)
const saved = fixture<{ suite: string; case: { id: string }; case_count: number }>(
  'post_suites_{name}_cases.json',
)

const STATE = JSON.stringify({
  party: 'Three adventurers, torches lit',
  monsters: 'Six goblins, weapons drawn, 40 feet away',
  player_says: 'We come in peace. Take this sack of silver and let us pass to the stairs.',
})

const OPTIONS: [string, string][] = [
  ['parley', 'Talk, bargain, bribe, or negotiate'],
  ['evade', 'Run away or avoid the monsters'],
  ['fight', 'Attack the monsters'],
  ['wait', 'Hold position and watch'],
]

const LEVELS = [
  'Attack at once',
  'Hostile, may attack',
  'Uncertain, hold and posture',
  'Indifferent, may let them pass',
  'Friendly, accept the offer',
]

const request = (page: Page) => page.getByRole('complementary', { name: 'Request' })
const answers = (page: Page) => page.getByRole('region', { name: 'Answers' })

/** Builds the plan's parley request, which the decide fixtures answer. */
async function fillParleyRequest(page: Page) {
  const form = request(page)
  await form.getByRole('button', { name: 'Full request' }).click()
  await form
    .getByRole('group', { name: 'State format' })
    .getByRole('button', { name: 'JSON' })
    .click()
  await form.getByLabel('State', { exact: true }).fill(STATE)

  const first = form.getByRole('region', { name: /^Question/ }).first()
  await first.getByLabel('Question id').fill('intent')
  await first.getByRole('button', { name: 'Choice' }).click()
  await first.getByLabel('Question', { exact: true }).fill('What is the player trying to do?')
  for (const [i, [name, description]] of OPTIONS.entries()) {
    await first.getByRole('button', { name: 'Add option' }).click()
    await first.getByLabel(`Option ${i + 1} name`).fill(name)
    await first.getByLabel(`Option ${i + 1} description`).fill(description)
  }

  await form.getByRole('button', { name: 'Add question' }).click()
  const bribe = form.getByRole('region', { name: /^Question/ }).nth(1)
  await bribe.getByLabel('Question id').fill('bribe')
  await bribe
    .getByLabel('Question', { exact: true })
    .fill('Does the player offer the monsters something of value?')

  await form.getByRole('button', { name: 'Add question' }).click()
  const reaction = form.getByRole('region', { name: /^Question/ }).nth(2)
  await reaction.getByLabel('Question id').fill('reaction')
  await reaction.getByRole('button', { name: 'Score' }).click()
  await reaction
    .getByLabel('Question', { exact: true })
    .fill('How are goblins likely to react to this offer?')
  for (const [i, level] of LEVELS.entries()) {
    await reaction.getByRole('button', { name: 'Add level' }).click()
    await reaction.getByLabel(`Level ${i}`).fill(level)
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto('/compare')
  await expect(page.getByRole('link', { name: /^Target status/ })).toBeVisible()
})

test('a quick test asks the default target', async ({ page }) => {
  const form = request(page)
  await expect(form).toContainText('Yes or no, on decision-1@foundry')
  await form.getByLabel('State', { exact: true }).fill('Six goblins block the stairs.')
  await form.getByLabel('Question').fill('Are the goblins hostile?')
  await form.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(
    answers(page).getByRole('columnheader', { name: /decision-1@foundry/ }),
  ).toBeVisible()
  await expect(answers(page)).toContainText('Are the goblins hostile?')
})

test('a quick test grows into a full request without losing input', async ({ page }) => {
  const form = request(page)
  await form.getByLabel('State', { exact: true }).fill('Six goblins block the stairs.')
  await form.getByLabel('Question').fill('Are the goblins hostile?')
  await form.getByRole('button', { name: 'Full request' }).click()

  await expect(form.getByLabel('State', { exact: true })).toHaveValue(
    'Six goblins block the stairs.',
  )
  await expect(form.getByLabel('Question', { exact: true })).toHaveValue('Are the goblins hostile?')
  await expect(form.getByRole('checkbox', { name: 'decision-1@foundry' })).toBeChecked()
  await expect(form.getByRole('checkbox', { name: /clef-flash@ollama/ })).toBeDisabled()

  await form.getByRole('button', { name: 'Quick test' }).click()
  await expect(form.getByLabel('Question')).toHaveValue('Are the goblins hostile?')
})

test('a full request compares targets side by side', async ({ page }) => {
  await fillParleyRequest(page)
  const form = request(page)
  await form.getByRole('checkbox', { name: 'clef-flash@workers-ai' }).check()
  await form.getByRole('button', { name: 'Ask 2 targets' }).click()

  const grid = answers(page)
  await expect(grid.getByRole('columnheader', { name: /decision-1@foundry/ })).toContainText(
    'Answered',
  )
  await expect(grid.getByRole('columnheader', { name: /clef-flash@workers-ai/ })).toContainText(
    'May truncate state',
  )
  const parley = grid.getByRole('row', { name: /^parley/ })
  await expect(parley.locator('[data-picked]')).toHaveCount(2)
  await expect(grid.getByRole('row', { name: /^Score/ })).toContainText('2.21')
  await expect(grid.getByRole('row', { name: /^Latency/ })).toContainText('1,550 ms')
  await expect(page.getByText(/^Asked \d\d:\d\d$/)).toBeVisible()
})

test('an incomplete request shows what is missing', async ({ page }) => {
  const form = request(page)
  await form.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(form).toContainText('State is empty')
  await expect(form).toContainText('Question is empty')
  await expect(answers(page)).toContainText('No answers')
})

test('a target the server rejects fails its own column', async ({ page }) => {
  await page.route('**/api/decide', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-fixture': '422' } }),
  )
  const form = request(page)
  await form.getByLabel('State', { exact: true }).fill('Six goblins block the stairs.')
  await form.getByLabel('Question').fill('Are the goblins hostile?')
  await form.getByRole('button', { name: 'Ask', exact: true }).click()
  const column = answers(page).getByRole('columnheader', { name: /decision-1@foundry/ })
  await expect(column).toContainText('Unknown target: clef@nowhere')
  await expect(answers(page).getByRole('alert')).toHaveCount(0)
})

async function askParley(page: Page) {
  await fillParleyRequest(page)
  await request(page).getByRole('button', { name: 'Ask 1 target' }).click()
  await expect(
    answers(page).getByRole('columnheader', { name: /decision-1@foundry/ }),
  ).toContainText('Answered')
}

test('marking expected answers tags their rows', async ({ page }) => {
  await askParley(page)
  const grid = answers(page)
  await page.getByRole('button', { name: 'Mark expected answers' }).click()
  await grid.getByRole('button', { name: 'Expect parley for intent' }).click()
  await grid.getByRole('button', { name: 'Expect No for bribe' }).click()
  await grid.getByRole('button', { name: 'Expect 3 for reaction' }).click()
  await expect(grid.getByRole('button', { name: 'Expect parley for intent' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.getByRole('button', { name: 'Done marking' }).click()
  await expect(grid.getByText('Expected', { exact: true })).toHaveCount(2)
  await expect(grid.getByRole('row', { name: /^Yes/ })).toContainText('Expected no')
  await expect(grid.getByRole('row', { name: /^No/ })).toHaveCount(0)
})

test('a request saves as a case with its expected answers', async ({ page }) => {
  await askParley(page)
  await page.getByRole('button', { name: 'Mark expected answers' }).click()
  await answers(page).getByRole('button', { name: 'Expect parley for intent' }).click()

  let posted: unknown = null
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/api/suites/parley/cases')) {
      posted = r.postDataJSON()
    }
  })
  await page.getByRole('button', { name: 'Save as case' }).click()
  const dialog = page.getByRole('dialog', { name: 'Save as case' })
  await expect(dialog.getByLabel('Suite')).toHaveValue('parley')
  await expect(dialog.getByLabel('Case id')).toHaveValue('case-6')
  await expect(dialog.getByLabel('intent')).toHaveValue('"parley"')
  await dialog.getByLabel('Case id').fill('goblin-silver')
  await dialog.getByLabel('Tags').fill('bribe, goblins')
  await dialog.getByLabel('reaction').selectOption('3')
  await dialog.getByRole('button', { name: 'Save case' }).click()

  await expect(dialog).toContainText(
    `Saved ${saved.case.id} to ${saved.suite}, ${saved.case_count} cases`,
  )
  expect(posted).toMatchObject({
    id: 'goblin-silver',
    tags: ['bribe', 'goblins'],
    provenance: 'human',
    expected: { intent: { answer: 'parley' }, reaction: { answer: 3, tolerance: 0 } },
  })
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toBeHidden()
})

test('a case id the suite has shows on the id field', async ({ page }) => {
  await page.route('**/api/suites/parley/cases', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-fixture': '409' } }),
  )
  await askParley(page)
  await page.getByRole('button', { name: 'Save as case' }).click()
  const dialog = page.getByRole('dialog', { name: 'Save as case' })
  await expect(dialog.getByLabel('Case id')).toHaveValue('case-6')
  await dialog.getByRole('button', { name: 'Save case' }).click()
  await expect(dialog).toContainText(conflict.error.details[0].message)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('the request copies as a CLI command', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await askParley(page)
  await page.getByRole('button', { name: 'Copy as CLI command' }).click()
  await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible()
  const command = await page.evaluate(() => navigator.clipboard.readText())
  expect(command).toMatch(
    /^uv run jevtester decide --request - --target decision-1@foundry --format json <<'JSON'\n/,
  )
  expect(command).toContain('"player_says"')
})
