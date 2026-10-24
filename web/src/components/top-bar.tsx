import { NavLink } from 'react-router-dom'

import { useTargets } from '../store/targets'
import { VIEWS } from '../nav'
import { HealthStrip } from './health-strip'
import { Mark } from './mark'

export function TopBar() {
  const targets = useTargets((s) => s.targets)
  return (
    <header className="sticky top-0 z-10 flex h-topbar items-center gap-7 border-b border-line bg-surface px-6">
      <Mark />
      <nav aria-label="Views" className="flex h-full gap-1">
        {VIEWS.map((view) => (
          <NavLink
            key={view.path}
            to={view.path}
            className={({ isActive }) =>
              `flex items-center border-b-[3px] px-3.5 font-display text-[16px] font-semibold [font-stretch:80%] hover:text-text ${
                isActive ? 'border-pick text-text' : 'border-transparent text-dim'
              }`
            }
          >
            {view.label}
          </NavLink>
        ))}
      </nav>
      <div className="flex-1" />
      {targets ? <HealthStrip targets={targets} /> : null}
    </header>
  )
}
