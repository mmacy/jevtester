import { describe, expect, it } from 'vitest'

import type { TargetList } from '../api/types'
import { fixture } from '../test/fixtures'
import { healthSummary } from './health'

describe('healthSummary', () => {
  it('counts ready targets, warnings included', () => {
    // Foundry is ready and the three Workers AI targets have warnings.
    expect(healthSummary(fixture<TargetList>('get_targets.json').targets)).toBe(
      '4 of 8 targets ready',
    )
  })

  it('says when no target has been checked', () => {
    expect(healthSummary(fixture<TargetList>('get_targets.unchecked.json').targets)).toBe(
      'Targets not checked',
    )
  })

  it('says when there are no targets', () => {
    expect(healthSummary([])).toBe('No targets')
  })
})
