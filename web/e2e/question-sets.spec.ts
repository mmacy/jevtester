import { expect, test } from '@playwright/test'

import { fixture } from './fixtures.ts'

interface Detail {
  question_set: { name: string; version: string }
  checks: { question: string; message: string }[]
}

const detail = fixture<Detail>('get_question-sets_{name}.json')
const rejected = fixture<{ error: { details: { message: string }[] } }>(
  'put_question-sets_{name}.422.json',
)

test('the list links to each question set', async ({ page }) => {
  await page.goto('/question-sets')
  const row = page.getByRole('row', { name: /^parley/ })
  await expect(row).toContainText(detail.question_set.version.slice(0, 12))
  await row.getByRole('link', { name: 'parley' }).click()
  await expect(page).toHaveURL(/\/question-sets\/parley$/)
})

test('a question set shows its questions, wording checks, and versions', async ({ page }) => {
  await page.goto('/question-sets/parley')
  const questions = page.getByRole('region', { name: 'Questions', exact: true })
  await expect(questions.getByLabel('Question id')).toHaveCount(3)
  for (const check of detail.checks) {
    await expect(
      questions.getByRole('list', { name: `Wording checks for ${check.question}` }),
    ).toContainText(check.message)
  }
  await expect(page.getByRole('button', { name: 'Save version' })).toBeDisabled()
  const versions = page.getByRole('region', { name: 'Versions' })
  await expect(versions).toContainText('Current')
})

test('an edit saves a new version', async ({ page }) => {
  await page.goto('/question-sets/parley')
  const questions = page.getByRole('region', { name: 'Questions', exact: true })
  const intent = questions.getByRole('region', { name: 'Question intent' })
  await intent.getByRole('button', { name: 'Add option' }).click()
  await intent.getByLabel('Option 5 name').fill('cannot_tell')
  await intent.getByLabel('Option 5 description').fill('The player is unclear')

  const put = page.waitForRequest(
    (r) => r.method() === 'PUT' && r.url().endsWith('/api/question-sets/parley'),
  )
  await page.getByRole('button', { name: 'Save version' }).click()
  const body = (await put).postDataJSON() as {
    questions: Record<string, { criteria: Record<string, string> }>
  }
  expect(Object.keys(body.questions)).toEqual(['intent', 'bribe', 'reaction'])
  expect(body.questions.intent.criteria.cannot_tell).toBe('The player is unclear')
})

test('a rejected save shows each error on its question', async ({ page }) => {
  await page.route('**/api/question-sets/parley', (route) =>
    route.request().method() === 'PUT'
      ? route.continue({ headers: { ...route.request().headers(), 'x-fixture': '422' } })
      : route.continue(),
  )
  await page.goto('/question-sets/parley')
  const questions = page.getByRole('region', { name: 'Questions', exact: true })
  await questions
    .getByRole('region', { name: 'Question bribe' })
    .getByLabel('Question', { exact: true })
    .fill('Bribe?')
  await page.getByRole('button', { name: 'Save version' }).click()
  await expect(questions.getByRole('region', { name: 'Question reaction' })).toContainText(
    rejected.error.details[0].message,
  )
})

test('two versions compare word by word', async ({ page }) => {
  await page.goto('/question-sets/parley')
  await page.getByRole('button', { name: 'Compare with current' }).click()
  await expect(page).toHaveURL(/\/question-sets\/parley\/diff\?from=.+&to=.+/)
  const intent = page.getByRole('region', { name: 'Question intent' })
  await expect(intent).toContainText('Changed')
  await expect(intent.getByRole('row', { name: /^wait/ })).toContainText('Added')
  await expect(page.getByRole('heading', { name: /^parley/ })).toContainText('changed')
})
