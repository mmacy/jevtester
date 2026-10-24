import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type {
  AnswerValue,
  CaseCreated,
  QuestionOutput,
  SuiteDetail,
  SuiteSummary,
} from '../api/types'
import { buildCase, nextCaseId, parseTags, unmatchedQuestions } from '../lib/case'
import type { Asked } from '../store/compare'
import { ApiErrorState } from './api-error'
import { Button } from './button'
import { FieldErrors, FieldLabel, TextInput } from './fields'
import { EmptyState, Spinner } from './states'

interface SaveCaseDialogProps {
  asked: Asked
  expected: Readonly<Record<string, AnswerValue>>
  tolerance: Readonly<Record<string, number>>
  onClose: () => void
}

const SELECT =
  'w-full rounded border border-line bg-bg px-2 py-1.5 text-sm focus:border-pick focus:outline-none disabled:opacity-50'

/** An expected answer as a select value, and back. */
function toOption(answer: AnswerValue | undefined): string {
  return answer === undefined ? '' : JSON.stringify(answer)
}

function fromOption(value: string): AnswerValue | null {
  return value === '' ? null : (JSON.parse(value) as AnswerValue)
}

function ExpectedField({
  id,
  question,
  value,
  tolerance,
  disabled,
  onChange,
  onTolerance,
}: {
  id: string
  question: QuestionOutput
  value: AnswerValue | undefined
  tolerance: number
  disabled: boolean
  onChange: (value: AnswerValue | null) => void
  onTolerance: (tolerance: number) => void
}) {
  const choices: [string, string][] =
    question.type === 'noul'
      ? [
          ['true', 'Yes'],
          ['false', 'No'],
        ]
      : question.type === 'choice'
        ? Object.keys(question.criteria).map((o) => [JSON.stringify(o), o])
        : question.criteria.map((level, i) => [String(i), `${i}  ${level}`])
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)_auto] items-center gap-2">
      <label htmlFor={`expected-${id}`} className="truncate font-mono text-sm text-pick">
        {id}
      </label>
      <select
        id={`expected-${id}`}
        className={SELECT}
        disabled={disabled}
        value={disabled ? '' : toOption(value)}
        onChange={(e) => onChange(fromOption(e.target.value))}
      >
        <option value="">None</option>
        {choices.map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
      {question.type === 'score' ? (
        <label className="flex items-center gap-1.5 text-sm text-dim">
          Tolerance
          <input
            type="number"
            min={0}
            max={question.criteria.length - 1}
            value={tolerance}
            disabled={disabled}
            onChange={(e) => onTolerance(Math.max(0, Number(e.target.value) || 0))}
            className="w-14 rounded border border-line bg-bg px-1.5 py-1 text-sm"
          />
        </label>
      ) : (
        <span />
      )}
    </div>
  )
}

/** Saves the asked state as a case in a suite, with its expected answers. */
export function SaveCaseDialog({ asked, expected, tolerance, onClose }: SaveCaseDialogProps) {
  const titleId = useId()
  const [suites, setSuites] = useState<SuiteSummary[] | null>(null)
  const [suiteName, setSuiteName] = useState('')
  const [loaded, setLoaded] = useState<SuiteDetail | null>(null)
  const [caseId, setCaseId] = useState('')
  // The id follows the suite until the person edits it.
  const idEdited = useRef(false)
  const [tagsText, setTagsText] = useState('')
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({ ...expected })
  const [slack, setSlack] = useState<Record<string, number>>({ ...tolerance })
  const [error, setError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<CaseCreated | null>(null)

  useEffect(() => {
    api
      .listSuites()
      .then((list) => {
        setSuites(list.suites)
        setSuiteName((current) => current || (list.suites[0]?.name ?? ''))
      })
      .catch(setError)
  }, [])

  useEffect(() => {
    if (!suiteName) return
    let live = true
    api
      .getSuite(suiteName)
      .then((d) => {
        if (!live) return
        setLoaded(d)
        if (!idEdited.current) setCaseId(nextCaseId(d.suite.cases.map((c) => c.id)))
      })
      .catch((e: unknown) => {
        if (live) setError(e)
      })
    return () => {
      live = false
    }
  }, [suiteName])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const detail = loaded?.suite.name === suiteName ? loaded : null
  const skip = detail ? unmatchedQuestions(asked.request, detail.question_set) : []
  const idErrors =
    error instanceof ApiError
      ? error.details.filter((d) => d.field === 'id').map((d) => d.message)
      : []
  const otherError = error && idErrors.length === 0 ? error : null

  const save = async () => {
    if (!detail) return
    setSaving(true)
    setError(null)
    try {
      const body = buildCase({
        id: caseId,
        state: asked.body.state,
        tags: parseTags(tagsText),
        expected: answers,
        tolerance: slack,
        skip,
      })
      setSaved(await api.addCase(detail.suite.name, body))
    } catch (e) {
      setError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-20 flex items-start justify-center overflow-y-auto bg-black/50 p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="mt-16 w-full max-w-[560px] rounded border border-line bg-surface p-5"
      >
        <h2
          id={titleId}
          className="m-0 mb-3.5 font-display text-[22px] font-bold [font-stretch:75%]"
        >
          Save as case
        </h2>
        {saved ? (
          <div>
            <p className="m-0 text-ok">
              Saved {saved.case.id} to {saved.suite}, {saved.case_count} cases
            </p>
            <div className="mt-4 flex gap-2.5">
              <Link to={`/suites/${encodeURIComponent(saved.suite)}`} className="no-underline">
                <Button primary>Open suite</Button>
              </Link>
              <Button onClick={onClose}>Close</Button>
            </div>
          </div>
        ) : suites && suites.length === 0 ? (
          <>
            <EmptyState label="No suites" />
            <div className="mt-4">
              <Button onClick={onClose}>Close</Button>
            </div>
          </>
        ) : (
          <div className="space-y-3">
            {otherError ? <ApiErrorState error={otherError} /> : null}
            <div>
              <FieldLabel htmlFor="case-suite">Suite</FieldLabel>
              <select
                id="case-suite"
                className={SELECT}
                value={suiteName}
                onChange={(e) => setSuiteName(e.target.value)}
                disabled={!suites}
              >
                {(suites ?? []).map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel htmlFor="case-id">Case id</FieldLabel>
              <TextInput
                id="case-id"
                autoFocus
                className="font-mono text-sm"
                value={caseId}
                onChange={(e) => {
                  idEdited.current = true
                  setCaseId(e.target.value)
                }}
              />
              <FieldErrors errors={idErrors} />
            </div>
            <div>
              <FieldLabel htmlFor="case-tags">Tags</FieldLabel>
              <TextInput
                id="case-tags"
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
              />
            </div>
            <fieldset className="m-0 space-y-1.5 border-0 p-0">
              <legend className="mb-1 text-sm text-dim">Expected answers</legend>
              {Object.entries(asked.request.questions).map(([id, question]) => (
                <ExpectedField
                  key={id}
                  id={id}
                  question={question}
                  value={answers[id]}
                  tolerance={slack[id] ?? 0}
                  disabled={skip.includes(id)}
                  onChange={(value) =>
                    setAnswers((current) => {
                      const next = { ...current }
                      if (value === null) delete next[id]
                      else next[id] = value
                      return next
                    })
                  }
                  onTolerance={(t) => setSlack((current) => ({ ...current, [id]: t }))}
                />
              ))}
              {skip.length > 0 && detail ? (
                <p className="m-0 text-sm text-warn">
                  Not in {detail.question_set.name}: {skip.join(', ')}
                </p>
              ) : null}
            </fieldset>
            <div className="flex items-center gap-2.5 pt-1">
              <Button
                primary
                onClick={() => void save()}
                disabled={!detail || saving || caseId.trim() === ''}
              >
                Save case
              </Button>
              <Button onClick={onClose}>Cancel</Button>
              {!detail || saving ? <Spinner label={saving ? 'Saving' : 'Loading suite'} /> : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
