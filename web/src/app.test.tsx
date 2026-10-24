// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import App from './app'
import { VIEWS } from './views'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App', () => {
  it('opens Compare from the root', () => {
    renderAt('/')
    expect(screen.getByRole('heading', { name: 'Compare' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Compare' })).toHaveAttribute('aria-current', 'page')
  })

  it('has a tab for every view, in sentence case', () => {
    renderAt('/')
    const labels = screen.getAllByRole('link').map((link) => link.textContent)
    expect(labels).toEqual(VIEWS.map((view) => view.label))
    for (const label of labels) {
      expect(label).toMatch(/^[A-Z][a-z ]*$/)
    }
  })

  it('switches views from the tabs', async () => {
    renderAt('/')
    await userEvent.click(screen.getByRole('link', { name: 'Targets' }))
    expect(screen.getByRole('heading', { name: 'Targets' })).toBeInTheDocument()
  })

  it('sends an unknown path to Compare', () => {
    renderAt('/no-such-view')
    expect(screen.getByRole('heading', { name: 'Compare' })).toBeInTheDocument()
  })
})
