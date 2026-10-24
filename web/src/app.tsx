import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useServer } from './api/server-store'
import { PanelHeading } from './components/panel-heading'
import { ServerUnreachable } from './components/states'
import { TopBar } from './components/top-bar'
import { useTargets } from './store/targets'
import { CompareView } from './views/compare-view'
import { ProbesView } from './views/probes-view'
import { RunsView } from './views/runs-view'
import { PoliciesView } from './views/policies-view'
import { QuestionSetsView } from './views/question-sets-view'
import { SuitesView } from './views/suites-view'
import { TargetsView } from './views/targets-view'
import { VIEWS } from './nav'

const BUILT: Record<string, () => React.JSX.Element> = {
  '/compare': CompareView,
  '/suites': SuitesView,
  '/runs': RunsView,
  '/question-sets': QuestionSetsView,
  '/policies': PoliciesView,
  '/probes': ProbesView,
  '/targets': TargetsView,
}

export default function App() {
  const loadTargets = useTargets((s) => s.load)
  const unreachable = useServer((s) => s.unreachable)

  useEffect(() => {
    void loadTargets()
  }, [loadTargets])

  return (
    <>
      <TopBar />
      {unreachable ? <ServerUnreachable onRetry={() => void loadTargets()} /> : null}
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/compare" replace />} />
          {VIEWS.map((view) => {
            const View = BUILT[view.path]
            return (
              <Route
                key={view.path}
                path={`${view.path}/*`}
                element={
                  View ? (
                    <View />
                  ) : (
                    <section className="px-6 pt-5 pb-12">
                      <PanelHeading>{view.label}</PanelHeading>
                    </section>
                  )
                }
              />
            )
          })}
          <Route path="*" element={<Navigate to="/compare" replace />} />
        </Routes>
      </main>
    </>
  )
}
