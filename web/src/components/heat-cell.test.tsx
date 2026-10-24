// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { heat } from '../lib/heat'
import { HeatCell } from './heat-cell'
import { HeatKey } from './heat-key'

function renderCell(node: React.ReactNode) {
  return render(
    <table>
      <tbody>
        <tr>{node}</tr>
      </tbody>
    </table>,
  )
}

describe('HeatCell', () => {
  it('shows the value at the given precision on its ramp color', () => {
    renderCell(<HeatCell value={0.9996} digits={3} />)
    const cell = screen.getByRole('cell')
    expect(cell).toHaveTextContent('1.000')
    expect(cell).toHaveStyle({ backgroundColor: heat(0.9996) })
    expect(cell).not.toHaveAttribute('data-picked')
  })

  it('marks a chosen answer', () => {
    renderCell(<HeatCell value={0.458} picked />)
    expect(screen.getByRole('cell')).toHaveAttribute('data-picked', 'true')
  })
})

describe('HeatKey', () => {
  it('labels the ramp and its ends', () => {
    render(<HeatKey label="Probability" showPick />)
    expect(screen.getByText('Probability')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('Chosen answer')).toBeInTheDocument()
    expect(screen.getByTestId('heat-ramp').style.background).toContain('linear-gradient')
  })
})
