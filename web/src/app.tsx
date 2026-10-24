import { Navigate, Route, Routes } from 'react-router-dom'

import { PanelHeading } from './components/panel-heading'
import { TopBar } from './components/top-bar'
import { VIEWS } from './views'

export default function App() {
  return (
    <>
      <TopBar />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/compare" replace />} />
          {VIEWS.map((view) => (
            <Route
              key={view.path}
              path={`${view.path}/*`}
              element={
                <section className="px-6 pt-5 pb-12">
                  <PanelHeading>{view.label}</PanelHeading>
                </section>
              }
            />
          ))}
          <Route path="*" element={<Navigate to="/compare" replace />} />
        </Routes>
      </main>
    </>
  )
}
