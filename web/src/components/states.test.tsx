// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  EmptyState,
  ErrorState,
  LoadingRows,
  NotReadyCell,
  ServerUnreachable,
  SHOW_ELAPSED_AFTER_S,
  Spinner,
} from './states'

function inRow(node: React.ReactNode) {
  return (
    <table>
      <tbody>
        <tr>{node}</tr>
      </tbody>
    </table>
  )
}

describe('Spinner', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the elapsed time only after a long wait', () => {
    vi.useFakeTimers()
    render(<Spinner label="Asking targets" />)
    expect(screen.getByRole('status')).toHaveTextContent(/^Asking targets$/)
    act(() => {
      vi.advanceTimersByTime((SHOW_ELAPSED_AFTER_S - 1) * 1000)
    })
    expect(screen.queryByText(/ s$/)).not.toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.getByText(`${SHOW_ELAPSED_AFTER_S + 2} s`)).toBeInTheDocument()
  })
})

describe('LoadingRows', () => {
  it('fills the grid frame with placeholder cells', () => {
    render(
      <table>
        <tbody>
          <LoadingRows rows={3} columns={4} />
        </tbody>
      </table>,
    )
    const rows = screen.getAllByTestId('loading-row')
    expect(rows).toHaveLength(3)
    expect(rows[0].querySelectorAll('td')).toHaveLength(4)
  })
})

describe('EmptyState', () => {
  it('shows its label and action', () => {
    render(<EmptyState label="No runs" action={<button>Start run</button>} />)
    expect(screen.getByText('No runs')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start run' })).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('shows the code, the message, and each detail', () => {
    render(
      <ErrorState
        code="invalid_request"
        message="The request isn't valid."
        details={[
          { field: 'questions.intent.criteria', message: 'Needs at least 2 options', line: null },
          { field: 'state', message: 'Required', line: null },
          { field: null, message: 'Mapping values are not allowed here', line: 12 },
        ]}
      />,
    )
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('invalid_request')
    expect(alert).toHaveTextContent("The request isn't valid.")
    expect(alert).toHaveTextContent('questions.intent.criteria Needs at least 2 options')
    expect(alert).toHaveTextContent('state Required')
    expect(alert).toHaveTextContent('Line 12 Mapping values are not allowed here')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('retries', async () => {
    const onRetry = vi.fn()
    render(<ErrorState code="internal" message="Boom" onRetry={onRetry} />)
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('NotReadyCell', () => {
  it('marks the cell as not ready', () => {
    render(inRow(<NotReadyCell label="Not running" />))
    const cell = screen.getByRole('cell')
    expect(cell).toHaveAttribute('data-not-ready')
    expect(cell).toHaveTextContent('Not running')
  })
})

describe('ServerUnreachable', () => {
  it('names the server and retries', async () => {
    const onRetry = vi.fn()
    render(<ServerUnreachable onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toHaveTextContent(
      "Can't reach the jevtester server at 127.0.0.1:8640",
    )
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
