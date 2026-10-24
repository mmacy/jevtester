import { useMemo, useState } from 'react'

import type { TargetInfo } from '../api/types'

import { AnswerMatrix } from '../components/answer-matrix'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { FieldErrors, FieldLabel, TextArea, TextInput } from '../components/fields'
import { HeatKey } from '../components/heat-key'
import { PanelHeading } from '../components/panel-heading'
import { QuestionCard } from '../components/question-card'
import { Segmented } from '../components/segmented'
import { EmptyState } from '../components/states'
import { TargetPicker } from '../components/target-picker'
import { formatClock } from '../lib/format'
import { buildMatrix } from '../lib/matrix'
import {
  fitsQuickTest,
  hasErrors,
  newQuestion,
  nextQuestionId,
  validateDraft,
  type DraftErrors,
  type StateMode,
} from '../lib/request'
import { useCompare } from '../store/compare'
import { useTargets } from '../store/targets'

const NO_TARGETS: readonly TargetInfo[] = []

const STATE_MODES: readonly { value: StateMode; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'json', label: 'JSON' },
]

function askLabel(count: number): string {
  return `Ask ${count} ${count === 1 ? 'target' : 'targets'}`
}

function QuickForm({ errors, onAsk }: { errors: DraftErrors | null; onAsk: () => void }) {
  const { draft, updateDraft, setMode, asking } = useCompare()
  const defaults = useTargets((s) => s.defaultTargets)
  const question = draft.questions[0]
  return (
    <div>
      <FieldLabel htmlFor="quick-state">State</FieldLabel>
      <TextArea
        id="quick-state"
        rows={5}
        value={draft.stateText}
        onChange={(e) => updateDraft((d) => ({ ...d, stateText: e.target.value }))}
      />
      <FieldErrors errors={errors?.state ? [errors.state] : undefined} />
      <div className="mt-3">
        <FieldLabel htmlFor="quick-question">Question</FieldLabel>
        <TextInput
          id="quick-question"
          value={question.instructions}
          onChange={(e) =>
            updateDraft((d) => ({
              ...d,
              questions: [{ ...d.questions[0], instructions: e.target.value }],
            }))
          }
          onKeyDown={(e) => {
            if (e.key === 'Enter') onAsk()
          }}
        />
        <FieldErrors errors={errors?.questions[question.key]} />
      </div>
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
        <Button primary onClick={onAsk} disabled={asking || defaults.length === 0}>
          Ask
        </Button>
        <span className="text-sm text-faint">
          {defaults.length > 0 ? `Yes or no, on ${defaults.join(', ')}` : 'No default targets'}
        </span>
      </div>
      <button
        type="button"
        onClick={() => setMode('full')}
        className="mt-[18px] w-full cursor-pointer rounded border border-dashed border-faint px-2.5 py-2.5 text-left font-semibold hover:border-dim"
      >
        Full request
      </button>
    </div>
  )
}

function FullForm({ errors, onAsk }: { errors: DraftErrors | null; onAsk: () => void }) {
  const { draft, updateDraft, targets: selected, setTargets, setMode, asking } = useCompare()
  const targets = useTargets((s) => s.targets) ?? NO_TARGETS
  const quick = fitsQuickTest(draft, selected.length)
  return (
    <div>
      <div className="flex items-center justify-between">
        <FieldLabel htmlFor="full-state">State</FieldLabel>
        <Segmented
          label="State format"
          options={STATE_MODES}
          value={draft.stateMode}
          onChange={(stateMode) => updateDraft((d) => ({ ...d, stateMode }))}
        />
      </div>
      <TextArea
        id="full-state"
        rows={6}
        className={draft.stateMode === 'json' ? 'font-mono text-sm' : ''}
        value={draft.stateText}
        onChange={(e) => updateDraft((d) => ({ ...d, stateText: e.target.value }))}
      />
      <FieldErrors errors={errors?.state ? [errors.state] : undefined} />

      <span className="mt-3.5 block text-sm text-dim">Targets</span>
      <TargetPicker targets={targets} selected={selected} onChange={setTargets} />

      <span className="mt-3.5 block text-sm text-dim">Questions</span>
      {draft.questions.map((question) => (
        <QuestionCard
          key={question.key}
          question={question}
          errors={errors?.questions[question.key]}
          onChange={(next) =>
            updateDraft((d) => ({
              ...d,
              questions: d.questions.map((q) => (q.key === next.key ? next : q)),
            }))
          }
          onRemove={
            draft.questions.length > 1
              ? () =>
                  updateDraft((d) => ({
                    ...d,
                    questions: d.questions.filter((q) => q.key !== question.key),
                  }))
              : undefined
          }
        />
      ))}
      <FieldErrors errors={errors?.questions['']} />

      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
        <Button primary onClick={onAsk} disabled={asking || selected.length === 0}>
          {askLabel(selected.length)}
        </Button>
        <Button
          onClick={() =>
            updateDraft((d) => ({
              ...d,
              questions: [...d.questions, newQuestion(nextQuestionId(d.questions))],
            }))
          }
        >
          Add question
        </Button>
        {quick ? <Button onClick={() => setMode('quick')}>Quick test</Button> : null}
      </div>
    </div>
  )
}

export function CompareView() {
  const { mode, draft, asked, askError, ask } = useCompare()
  const targets = useTargets((s) => s.targets) ?? NO_TARGETS
  const [showErrors, setShowErrors] = useState(false)
  const errors = useMemo(() => validateDraft(draft), [draft])

  const onAsk = () => {
    setShowErrors(true)
    if (hasErrors(errors)) return
    void ask()
  }

  const local = useMemo(() => new Set(targets.filter((t) => t.local).map((t) => t.name)), [targets])
  const rows = useMemo(
    () => (asked ? buildMatrix(asked.request, asked.columns, (t) => local.has(t)) : []),
    [asked, local],
  )
  const shown = showErrors ? errors : null

  return (
    <div className="grid min-h-[calc(100vh-var(--spacing-topbar))] grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside
        aria-label="Request"
        className="border-b border-line bg-surface p-5 xl:border-r xl:border-b-0"
      >
        <PanelHeading>Request</PanelHeading>
        {mode === 'quick' ? (
          <QuickForm errors={shown} onAsk={onAsk} />
        ) : (
          <FullForm errors={shown} onAsk={onAsk} />
        )}
      </aside>
      <section aria-label="Answers" className="min-w-0 px-6 pt-5 pb-10">
        <div className="mb-3 flex flex-wrap items-baseline gap-4">
          <h2 className="m-0 font-display text-[22px] font-bold [font-stretch:75%]">Answers</h2>
          {asked?.askedAt ? (
            <p className="m-0 text-[13px] text-dim">Asked {formatClock(asked.askedAt)}</p>
          ) : null}
          <div className="ml-auto">
            <HeatKey label="Probability" showPick />
          </div>
        </div>
        {askError ? (
          <div className="mb-4">
            <ApiErrorState error={askError} />
          </div>
        ) : null}
        {asked ? (
          <AnswerMatrix columns={asked.columns} rows={rows} targets={targets} />
        ) : (
          <EmptyState label="No answers" />
        )}
      </section>
    </div>
  )
}
