// @vitest-environment jsdom
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TargetList } from './api/types'
import App from './app'
import { VIEWS } from './nav'
import { fixture } from './test/fixtures'
import { stubApi } from './test/stub-api'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App', () => {
  beforeEach(() => {
    stubApi({ 'GET /api/targets': { body: fixture<TargetList>('get_targets.json') } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads the targets into the health strip', async () => {
    renderAt('/')
    expect(
      await screen.findByRole('link', { name: 'Target status: 4 of 8 targets ready' }),
    ).toBeInTheDocument()
  })

  it('opens Compare from the root', () => {
    renderAt('/')
    expect(screen.getByRole('heading', { name: 'Request' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Compare' })).toHaveAttribute('aria-current', 'page')
  })

  it('has a tab for every view, in sentence case', () => {
    renderAt('/')
    const labels = within(screen.getByRole('navigation', { name: 'Views' }))
      .getAllByRole('link')
      .map((link) => link.textContent)
    expect(labels).toEqual(VIEWS.map((view) => view.label))
    for (const label of labels) {
      expect(label).toMatch(/^[A-Z][a-z ]*$/)
    }
  })

  it('switches views from the tabs', async () => {
    renderAt('/')
    await userEvent.click(screen.getByRole('link', { name: 'Targets' }))
    expect(await screen.findByRole('heading', { name: /^Targets/ })).toBeInTheDocument()
  })

  it('sends an unknown path to Compare', () => {
    renderAt('/no-such-view')
    expect(screen.getByRole('link', { name: 'Compare' })).toHaveAttribute('aria-current', 'page')
  })
})
