// @vitest-environment jsdom
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useServer } from '../api/server-store'
import type { TargetList } from '../api/types'
import { useTargets } from '../store/targets'
import { fixture } from '../test/fixtures'
import { stubApi } from '../test/stub-api'
import { TargetsView } from './targets-view'

const checked = fixture<TargetList>('get_targets.json')
const unchecked = fixture<TargetList>('get_targets.unchecked.json')

function resetStores() {
  useTargets.setState({
    targets: null,
    checkedAt: null,
    loading: false,
    checking: false,
    error: null,
  })
  useServer.setState({ unreachable: false })
}

describe('TargetsView', () => {
  beforeEach(resetStores)
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows placeholder rows while loading', () => {
    useTargets.setState({ loading: true })
    render(<TargetsView />)
    expect(screen.getAllByTestId('loading-row').length).toBeGreaterThan(0)
  })

  it('shows a column per target and a row per capability', async () => {
    stubApi({ 'GET /api/targets': { body: checked } })
    await useTargets.getState().load()
    render(<TargetsView />)
    for (const target of checked.targets) {
      expect(
        screen.getByRole('columnheader', { name: new RegExp(target.name) }),
      ).toBeInTheDocument()
    }
    const status = screen.getByRole('row', { name: /^Status/ })
    expect(within(status).getByText("clef-flash isn't pulled")).toBeInTheDocument()
    expect(within(status).getByText('Run ollama pull clef-flash (11-12 GB)')).toBeInTheDocument()
    expect(screen.getByText(/4 of 8 ready$/)).toBeInTheDocument()
  })

  it('says not checked, then runs every health check', async () => {
    const fetchMock = stubApi({
      'GET /api/targets': { body: unchecked },
      'POST /api/targets/check': { body: checked },
    })
    await useTargets.getState().load()
    render(<TargetsView />)
    expect(screen.getByText('Not checked', { selector: 'small' })).toBeInTheDocument()
    expect(
      within(screen.getByRole('row', { name: /^Status/ })).getAllByText('Not checked'),
    ).toHaveLength(unchecked.targets.length)

    await userEvent.click(screen.getByRole('button', { name: 'Check all targets' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/targets/check', expect.anything())
    expect(await screen.findByText(/4 of 8 ready$/)).toBeInTheDocument()
  })

  it('shows an API error with a retry', async () => {
    stubApi({
      'GET /api/targets': {
        status: 500,
        body: {
          error: { code: 'internal', message: 'Config unreadable', field: null, details: [] },
        },
      },
    })
    await useTargets.getState().load()
    render(<TargetsView />)
    expect(screen.getByRole('alert')).toHaveTextContent('Config unreadable')

    stubApi({ 'GET /api/targets': { body: checked } })
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/4 of 8 ready$/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('leaves an unreachable server to the bar', async () => {
    stubApi({ 'GET /api/targets': () => Promise.reject(new TypeError('Failed to fetch')) })
    await useTargets.getState().load()
    render(<TargetsView />)
    expect(useServer.getState().unreachable).toBe(true)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says when there are no targets', async () => {
    stubApi({ 'GET /api/targets': { body: { targets: [], checked_at: null } } })
    await useTargets.getState().load()
    render(<TargetsView />)
    expect(screen.getByText('No targets in jevtester.toml')).toBeInTheDocument()
  })
})
