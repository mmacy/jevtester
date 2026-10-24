import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { AnswerValue, CaseOutput, SuiteDetail } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { PanelHeading } from '../components/panel-heading'
import { StartRunDialog } from '../components/start-run-dialog'
import { EmptyState, LoadingRows } from '../components/states'
import { useLoad } from '../hooks/use-load'
import { shortVersion, stateSummary } from '../lib/format'
import { draftFor } from '../lib/request'
import { useCompare } from '../store/compare'

const TH = 'px-2 pb-1.5 text-left text-sm font-medium text-dim'
const TD = 'h-11 rounded-[2px] bg-surface px-2 text-[13.5px]'

function SuiteList() {
  const suites = useLoad(() => api.listSuites(), 'suites')
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading>Suites</PanelHeading>
      {suites.error ? <ApiErrorState error={suites.error} onRetry={suites.reload} /> : null}
      {suites.data && suites.data.suites.length === 0 ? (
        <EmptyState label="No suites in suites/" />
      ) : null}
      {!suites.error && (suites.loading || suites.data?.suites.length) ? (
        <table className="w-full table-fixed border-separate border-spacing-0.5">
          <thead>
            <tr>
              <th className={`${TH} w-48`}>Suite</th>
              <th className={TH}>Question set</th>
              <th className={`${TH} w-28`}>Cases</th>
              <th className={`${TH} w-40`}>Policy</th>
              <th className={TH}>Default targets</th>
            </tr>
          </thead>
          <tbody>
            {suites.data ? (
              suites.data.suites.map((suite) => (
                <tr key={suite.name}>
                  <td className={TD}>
                    <Link
                      to={`/suites/${encodeURIComponent(suite.name)}`}
                      className="font-mono text-sm text-pick no-underline hover:underline"
                    >
                      {suite.name}
                    </Link>
                  </td>
                  <td className={TD}>
                    {suite.question_set}{' '}
                    {suite.question_set_version ? (
                      <span className="font-mono text-xs text-dim">
                        {shortVersion(suite.question_set_version)}
                      </span>
                    ) : null}
                  </td>
                  <td className={TD}>
                    {suite.case_count}
                    {suite.draft_count > 0 ? (
                      <span className="ml-1.5 text-xs text-faint">{suite.draft_count} draft</span>
                    ) : null}
                  </td>
                  <td className={TD}>{suite.policy ?? <span className="text-faint">None</span>}</td>
                  <td className={`${TD} truncate`}>{suite.targets.join(', ')}</td>
                </tr>
              ))
            ) : (
              <LoadingRows rows={3} columns={5} />
            )}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

function expectedText(answer: AnswerValue | null): string {
  if (answer === null) return ''
  if (typeof answer === 'boolean') return answer ? 'Yes' : 'No'
  return String(answer)
}

function CaseRow({ detail, kase }: { detail: SuiteDetail; kase: CaseOutput }) {
  const navigate = useNavigate()
  const openCase = useCompare((s) => s.openCase)
  const draft = kase.provenance === 'claude-draft'
  const open = () => {
    const expected: Record<string, AnswerValue> = {}
    const tolerance: Record<string, number> = {}
    for (const [id, e] of Object.entries(kase.expected)) {
      if (e.answer !== null) expected[id] = e.answer
      tolerance[id] = e.tolerance
    }
    openCase(
      draftFor(kase.state, detail.question_set.questions),
      detail.suite.targets,
      expected,
      tolerance,
    )
    navigate('/compare')
  }
  const questions = Object.entries(detail.question_set.questions)
  return (
    <tr className={draft ? 'opacity-70' : undefined}>
      <td className={`${TD} font-mono text-sm text-pick`}>
        {kase.id}
        {draft ? (
          <span className="ml-1.5 rounded-[2px] bg-warn-bg px-1 font-sans text-xs text-warn">
            Draft
          </span>
        ) : null}
      </td>
      <td className={`${TD} truncate text-dim`} title={stateSummary(kase.state)}>
        {stateSummary(kase.state)}
      </td>
      <td className={`${TD} truncate text-sm text-dim`}>{kase.tags.join(', ')}</td>
      {questions.map(([id, question]) => {
        const e = kase.expected[id]
        return (
          <td key={id} className={`${TD} truncate text-sm`}>
            {e ? (
              <>
                {expectedText(e.answer)}
                {e.tolerance > 0 ? (
                  <span className="ml-1 text-xs text-faint">±{e.tolerance}</span>
                ) : null}
                {question.type === 'score' && typeof e.answer === 'number' ? (
                  <small className="block truncate text-xs text-faint">
                    {question.criteria[e.answer]}
                  </small>
                ) : null}
              </>
            ) : (
              <span className="text-faint">None</span>
            )}
          </td>
        )
      })}
      <td className="px-1">
        <Button
          className="px-2.5 py-1 text-sm"
          onClick={open}
          aria-label={`Open ${kase.id} in compare`}
        >
          Open in compare
        </Button>
      </td>
    </tr>
  )
}

function SuitePage() {
  const { name = '' } = useParams()
  const suite = useLoad(() => api.getSuite(name), name)
  const [running, setRunning] = useState(false)
  const detail = suite.data
  const questions = detail ? Object.keys(detail.question_set.questions) : []
  const counted = detail
    ? detail.suite.cases.filter((c) => c.provenance !== 'claude-draft').length
    : 0
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading
        note={
          detail
            ? `${detail.question_set.name} ${shortVersion(detail.question_set.version)}, ${counted} cases${
                detail.suite.policy ? `, policy ${detail.suite.policy}` : ''
              }`
            : undefined
        }
      >
        {name}
      </PanelHeading>
      {suite.error ? <ApiErrorState error={suite.error} onRetry={suite.reload} /> : null}
      {detail ? (
        <div className="mb-4 flex items-center gap-2.5">
          <Button primary onClick={() => setRunning(true)}>
            Start run
          </Button>
          <span className="text-sm text-dim">
            Default targets: {detail.suite.targets.join(', ') || 'none'}
          </span>
        </div>
      ) : null}
      {detail && detail.suite.cases.length === 0 ? (
        <EmptyState
          label="No cases"
          action={
            <Link to="/compare" className="no-underline">
              <Button>Open compare</Button>
            </Link>
          }
        />
      ) : !suite.error ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] table-fixed border-separate border-spacing-0.5">
            <thead>
              <tr>
                <th className={`${TH} w-44`}>Case</th>
                <th className={TH}>State</th>
                <th className={`${TH} w-28`}>Tags</th>
                {questions.map((id) => (
                  <th key={id} className={`${TH} w-40 font-mono text-pick`}>
                    {id}
                  </th>
                ))}
                <th className="w-40" />
              </tr>
            </thead>
            <tbody>
              {detail ? (
                detail.suite.cases.map((kase) => (
                  <CaseRow key={kase.id} detail={detail} kase={kase} />
                ))
              ) : (
                <LoadingRows rows={4} columns={6} />
              )}
            </tbody>
          </table>
        </div>
      ) : null}
      {running && detail ? (
        <StartRunDialog suite={detail.suite} onClose={() => setRunning(false)} />
      ) : null}
    </section>
  )
}

export function SuitesView() {
  return (
    <Routes>
      <Route index element={<SuiteList />} />
      <Route path=":name" element={<SuitePage />} />
    </Routes>
  )
}
