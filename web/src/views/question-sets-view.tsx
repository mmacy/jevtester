import { useMemo, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type { QuestionDiff, QuestionOutput, QuestionSetDetail, WordingCheck } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { FieldErrors } from '../components/fields'
import { PanelHeading } from '../components/panel-heading'
import { QuestionCard } from '../components/question-card'
import { EmptyState, LoadingRows, Spinner } from '../components/states'
import { useLoad } from '../hooks/use-load'
import { formatDateTime, shortVersion } from '../lib/format'
import {
  draftsFrom,
  newQuestion,
  nextQuestionId,
  toQuestions,
  validateQuestions,
  type QuestionDraft,
} from '../lib/request'
import { wordDiff } from '../lib/word-diff'

const TH = 'px-2 pb-1.5 text-left text-sm font-medium text-dim'
const TD = 'h-11 rounded-[2px] bg-surface px-2 text-[13.5px]'

function QuestionSetList() {
  const sets = useLoad(() => api.listQuestionSets(), 'question-sets')
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading>Question sets</PanelHeading>
      {sets.error ? <ApiErrorState error={sets.error} onRetry={sets.reload} /> : null}
      {sets.data && sets.data.question_sets.length === 0 ? (
        <EmptyState label="No question sets" />
      ) : null}
      {!sets.error && (sets.loading || sets.data?.question_sets.length) ? (
        <table className="w-full table-fixed border-separate border-spacing-0.5">
          <thead>
            <tr>
              <th className={`${TH} w-48`}>Question set</th>
              <th className={`${TH} w-40`}>Version</th>
              <th className={`${TH} w-28`}>Questions</th>
              <th className={TH}>Suites</th>
              <th className={`${TH} w-40`}>Updated</th>
            </tr>
          </thead>
          <tbody>
            {sets.data ? (
              sets.data.question_sets.map((set) => (
                <tr key={set.name}>
                  <td className={TD}>
                    <Link
                      to={`/question-sets/${encodeURIComponent(set.name)}`}
                      className="font-mono text-sm text-pick no-underline hover:underline"
                    >
                      {set.name}
                    </Link>
                  </td>
                  <td className={`${TD} font-mono text-xs text-dim`}>
                    {shortVersion(set.version)}
                  </td>
                  <td className={TD}>{set.question_count}</td>
                  <td className={TD}>
                    {set.suites.join(', ') || <span className="text-faint">None</span>}
                  </td>
                  <td className={`${TD} text-sm text-dim`}>
                    {set.updated_at ? formatDateTime(set.updated_at) : ''}
                  </td>
                </tr>
              ))
            ) : (
              <LoadingRows rows={2} columns={5} />
            )}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

/** Field errors from the API, keyed by question id, from paths like `questions.intent.choice.criteria`. */
function serverErrors(error: unknown): Record<string, string[]> {
  const byQuestion: Record<string, string[]> = {}
  if (!(error instanceof ApiError)) return byQuestion
  for (const detail of error.details) {
    const parts = (detail.field ?? '').split('.')
    const id = parts[0] === 'questions' && parts[1] ? parts[1] : ''
    ;(byQuestion[id] ??= []).push(detail.message)
  }
  return byQuestion
}

function Versions({ name, version }: { name: string; version: string }) {
  const versions = useLoad(() => api.listVersions(name), `${name}:${version}`)
  const navigate = useNavigate()
  const [from, setFrom] = useState<string | null>(null)
  const list = versions.data?.versions ?? []
  const current = list.find((v) => v.current)?.version ?? null
  const older = from ?? list.find((v) => !v.current)?.version ?? null
  return (
    <section aria-label="Versions">
      <PanelHeading>Versions</PanelHeading>
      {versions.error ? <ApiErrorState error={versions.error} onRetry={versions.reload} /> : null}
      <table className="w-full table-fixed border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className={`${TH} w-10`}>From</th>
            <th className={TH}>Version</th>
            <th className={`${TH} w-36`}>First seen</th>
            <th className={`${TH} w-16`}>Runs</th>
          </tr>
        </thead>
        <tbody>
          {versions.data ? (
            list.map((v) => (
              <tr key={v.version}>
                <td className={`${TD} text-center`}>
                  <input
                    type="radio"
                    name="diff-from"
                    className="accent-pick"
                    aria-label={`Compare from ${shortVersion(v.version)}`}
                    checked={older === v.version}
                    disabled={v.current}
                    onChange={() => setFrom(v.version)}
                  />
                </td>
                <td className={`${TD} font-mono text-sm`}>
                  {shortVersion(v.version)}
                  {v.current ? (
                    <span className="ml-2 font-sans text-xs text-ok">Current</span>
                  ) : null}
                </td>
                <td className={`${TD} text-sm text-dim`}>{formatDateTime(v.first_seen)}</td>
                <td className={TD}>{v.run_count}</td>
              </tr>
            ))
          ) : (
            <LoadingRows rows={2} columns={4} />
          )}
        </tbody>
      </table>
      <div className="mt-3">
        <Button
          disabled={!older || !current}
          onClick={() =>
            older &&
            current &&
            navigate(
              `/question-sets/${encodeURIComponent(name)}/diff?from=${encodeURIComponent(older)}&to=${encodeURIComponent(current)}`,
            )
          }
        >
          Compare with current
        </Button>
      </div>
    </section>
  )
}

function checksFor(checks: readonly WordingCheck[], id: string) {
  return checks.filter((c) => c.question === id)
}

function Editor({
  detail,
  onSaved,
}: {
  detail: QuestionSetDetail
  onSaved: (d: QuestionSetDetail) => void
}) {
  const set = detail.question_set
  const [questions, setQuestions] = useState<QuestionDraft[]>(() => draftsFrom(set.questions))
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const errors = useMemo(() => validateQuestions(questions), [questions])
  const sent = useMemo(() => JSON.stringify(toQuestions(draftsFrom(set.questions))), [set])
  const changed = JSON.stringify(toQuestions(questions)) !== sent
  const fromServer = serverErrors(error)

  const save = async () => {
    setShowErrors(true)
    if (Object.keys(errors).length > 0) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.saveQuestionSet(set.name, toQuestions(questions))
      setQuestions(draftsFrom(saved.question_set.questions))
      setShowErrors(false)
      onSaved(saved)
    } catch (e) {
      setError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-label="Questions">
      <PanelHeading>Questions</PanelHeading>
      {error && !(error instanceof ApiError && error.details.length > 0) ? (
        <ApiErrorState error={error} />
      ) : null}
      {questions.map((question) => {
        const own = checksFor(detail.checks, question.id)
        return (
          <div key={question.key}>
            <QuestionCard
              question={question}
              errors={[
                ...((showErrors && errors[question.key]) || []),
                ...(fromServer[question.id.trim()] ?? []),
              ]}
              onChange={(next) =>
                setQuestions((qs) => qs.map((q) => (q.key === next.key ? next : q)))
              }
              onRemove={
                questions.length > 1
                  ? () => setQuestions((qs) => qs.filter((q) => q.key !== question.key))
                  : undefined
              }
            />
            {own.length > 0 ? (
              <ul
                aria-label={`Wording checks for ${question.id}`}
                className="m-0 mt-1 list-none p-0 text-sm text-warn"
              >
                {own.map((check) => (
                  <li key={check.code}>{check.message}</li>
                ))}
              </ul>
            ) : null}
          </div>
        )
      })}
      <FieldErrors errors={[...((showErrors && errors['']) || []), ...(fromServer[''] ?? [])]} />
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
        <Button primary onClick={() => void save()} disabled={saving || !changed}>
          Save version
        </Button>
        <Button onClick={() => setQuestions((qs) => [...qs, newQuestion(nextQuestionId(qs))])}>
          Add question
        </Button>
        {changed ? (
          <Button onClick={() => setQuestions(draftsFrom(set.questions))} disabled={saving}>
            Discard changes
          </Button>
        ) : null}
        {saving ? <Spinner label="Saving" /> : null}
      </div>
    </section>
  )
}

function QuestionSetPage() {
  const { name = '' } = useParams()
  const loaded = useLoad(() => api.getQuestionSet(name), name)
  const [saved, setSaved] = useState<QuestionSetDetail | null>(null)
  const detail = saved?.question_set.name === name ? saved : loaded.data
  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading
        note={
          detail
            ? `${shortVersion(detail.question_set.version)}${detail.suites.length ? `, used by ${detail.suites.join(', ')}` : ''}`
            : undefined
        }
      >
        {name}
      </PanelHeading>
      {loaded.error ? <ApiErrorState error={loaded.error} onRetry={loaded.reload} /> : null}
      {detail ? (
        <div className="grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
          <Editor key={detail.question_set.version} detail={detail} onSaved={setSaved} />
          <Versions name={name} version={detail.question_set.version} />
        </div>
      ) : loaded.loading ? (
        <Spinner label="Loading question set" />
      ) : null}
    </section>
  )
}

const STATUS_CLASS: Record<string, string> = {
  added: 'bg-fixed-bg text-ok',
  removed: 'bg-broken-bg text-err',
  changed: 'bg-warn-bg text-warn',
  unchanged: 'bg-surface text-dim',
}

function Words({
  before,
  after,
  side,
}: {
  before: string
  after: string
  side: 'before' | 'after'
}) {
  const parts = wordDiff(before, after)
  return (
    <>
      {parts.map((part, i) => {
        if (part.kind === 'same') return <span key={i}>{part.text}</span>
        if (side === 'before' && part.kind === 'removed')
          return (
            <del key={i} className="rounded-[2px] bg-broken-bg text-err-ink">
              {part.text}
            </del>
          )
        if (side === 'after' && part.kind === 'added')
          return (
            <ins key={i} className="rounded-[2px] bg-fixed-bg text-ok no-underline">
              {part.text}
            </ins>
          )
        return null
      })}
    </>
  )
}

function typeName(q: QuestionOutput | null) {
  if (!q) return ''
  return q.type === 'noul'
    ? 'Yes or no'
    : q.type === 'choice'
      ? 'Choice'
      : `Score, ${q.criteria.length} levels`
}

function DiffCard({ diff }: { diff: QuestionDiff }) {
  const before = diff.before
  const after = diff.after
  return (
    <section aria-label={`Question ${diff.id}`} className="mb-4 rounded border border-line">
      <header className="flex items-center gap-2 border-b border-line-soft px-3 py-1.5">
        <b className="font-mono text-sm font-normal text-pick">{diff.id}</b>
        <span className={`rounded-[2px] px-1.5 text-xs ${STATUS_CLASS[diff.status]}`}>
          {diff.status[0].toUpperCase() + diff.status.slice(1)}
        </span>
        {diff.order_changed ? <span className="text-xs text-warn">Order changed</span> : null}
        {diff.changed_fields.includes('type') ? (
          <span className="text-xs text-warn">
            {typeName(before)} to {typeName(after)}
          </span>
        ) : (
          <span className="text-xs text-faint">{typeName(after ?? before)}</span>
        )}
      </header>
      <div className="grid grid-cols-2 gap-px bg-line-soft">
        {(['before', 'after'] as const).map((side) => {
          const q = side === 'before' ? before : after
          return (
            <div key={side} className="bg-bg px-3 py-2 text-[13.5px]">
              {q ? (
                <Words
                  before={before?.instructions ?? ''}
                  after={after?.instructions ?? ''}
                  side={side}
                />
              ) : (
                <span className="text-faint">None</span>
              )}
            </div>
          )
        })}
      </div>
      {diff.options.length > 0 ? (
        <table className="w-full table-fixed border-separate border-spacing-0.5 p-1">
          <tbody>
            {diff.options.map((o) => (
              <tr key={o.key}>
                <th scope="row" className="w-32 px-2 text-left font-mono text-sm font-normal">
                  {o.key}
                </th>
                <td className="w-24">
                  <span className={`rounded-[2px] px-1.5 text-xs ${STATUS_CLASS[o.status]}`}>
                    {o.status[0].toUpperCase() + o.status.slice(1)}
                  </span>
                </td>
                <td className="px-2 text-sm">
                  {o.before === null ? (
                    ''
                  ) : (
                    <Words before={o.before} after={o.after ?? ''} side="before" />
                  )}
                </td>
                <td className="px-2 text-sm">
                  {o.after === null ? (
                    ''
                  ) : (
                    <Words before={o.before ?? ''} after={o.after} side="after" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

function DiffPage() {
  const { name = '' } = useParams()
  const [params] = useSearchParams()
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const diff = useLoad(() => api.getQuestionSetDiff(name, from, to), `${name}:${from}:${to}`)
  const shown = diff.data?.questions ?? []
  const counts = ['added', 'removed', 'changed'].map(
    (status) => `${shown.filter((q) => q.status === status).length} ${status}`,
  )
  return (
    <section className="max-w-[1100px] px-6 pt-5 pb-12">
      <PanelHeading
        note={`${shortVersion(from)} to ${shortVersion(to)}${diff.data ? `, ${counts.join(', ')}` : ''}`}
      >
        {name}
      </PanelHeading>
      <div className="mb-3">
        <Link to={`/question-sets/${encodeURIComponent(name)}`} className="no-underline">
          <Button>Back to {name}</Button>
        </Link>
      </div>
      {diff.error ? <ApiErrorState error={diff.error} onRetry={diff.reload} /> : null}
      {diff.loading ? <Spinner label="Loading diff" /> : null}
      <div className="mb-1 grid grid-cols-2 text-sm text-dim">
        <span className="px-3">{shortVersion(from)}</span>
        <span className="px-3">{shortVersion(to)}</span>
      </div>
      {shown.map((q) => (
        <DiffCard key={q.id} diff={q} />
      ))}
    </section>
  )
}

export function QuestionSetsView() {
  return (
    <Routes>
      <Route index element={<QuestionSetList />} />
      <Route path=":name" element={<QuestionSetPage />} />
      <Route path=":name/diff" element={<DiffPage />} />
    </Routes>
  )
}
