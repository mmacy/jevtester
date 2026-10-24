// The panels on a run's page: metrics, confusion matrix, calibration, and
// changed answers against a baseline.
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { AnswerValue, RunMetrics, RunSummary } from '../api/types'
import { useLoad } from '../hooks/use-load'
import { heat, ink } from '../lib/heat'
import { metricColumns, rankShade } from '../lib/run'
import { ApiErrorState } from './api-error'
import { HeatKey } from './heat-key'
import { PanelHeading } from './panel-heading'
import { EmptyState, LoadingRows } from './states'
import { Subtabs } from './subtabs'

function questionType(metrics: RunMetrics, question: string) {
  for (const target of metrics.targets) {
    const found = target.questions.find((q) => q.question === question)
    if (found) return found.type
  }
  return null
}

function answered(metrics: RunMetrics) {
  return metrics.targets.filter((t) => t.results > 0).map((t) => t.target)
}

export function MetricsPanel({ run, metrics }: { run: RunSummary; metrics: RunMetrics }) {
  const [picked, setPicked] = useState<string | null>(null)
  const question = picked ?? metrics.questions[0] ?? null
  const type = question ? questionType(metrics, question) : null
  if (!question || !type) return <EmptyState label="No metrics" />
  const columns = metricColumns(type, metrics.targets, question)
  const skipReason = new Map(run.counts.targets.map((t) => [t.target, t.skip_reason]))
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Subtabs
          label="Question"
          options={metrics.questions}
          value={question}
          onChange={setPicked}
        />
        <HeatKey label="Rank among targets" low="Worse" high="Better" />
      </div>
      <table className="w-full table-fixed border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="w-[170px] px-2 py-1 text-left align-bottom text-sm font-medium text-dim">
              Target
            </th>
            {columns.map((c) => (
              <th
                key={c.label}
                className="px-2 py-1 text-right align-bottom text-sm leading-tight font-medium text-dim"
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.targets.map((target) => {
            const q = target.questions.find((m) => m.question === question)
            if (target.results === 0) {
              return (
                <tr key={target.target}>
                  <td className="truncate font-display text-[15px] font-[650] [font-stretch:75%]">
                    {target.target}
                  </td>
                  <td
                    colSpan={columns.length}
                    className="hatch h-10 rounded-[2px] px-2 text-[13px] text-err"
                  >
                    Skipped
                    {skipReason.get(target.target) ? `, ${skipReason.get(target.target)}` : ''}
                  </td>
                </tr>
              )
            }
            return (
              <tr key={target.target}>
                <td
                  className="truncate font-display text-[15px] font-[650] [font-stretch:75%]"
                  title={target.target}
                >
                  {target.target}
                </td>
                {columns.map((c) => {
                  const value = c.value(target, q)
                  const all = metrics.targets
                    .filter((t) => t.results > 0)
                    .map((t) =>
                      c.value(
                        t,
                        t.questions.find((m) => m.question === question),
                      ),
                    )
                  const shade = rankShade(all, value, c.higherBetter)
                  if (value === null || shade === null) {
                    return (
                      <td
                        key={c.label}
                        className="h-10 rounded-[2px] bg-surface px-2 text-right text-faint"
                      >
                        {c.missing}
                      </td>
                    )
                  }
                  return (
                    <td
                      key={c.label}
                      className="h-10 rounded-[2px] px-2 text-right whitespace-nowrap"
                      style={{ background: heat(shade), color: ink(shade) }}
                    >
                      {c.format(value)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function ConfusionPanel({
  runId,
  metrics,
  version,
}: {
  runId: string
  metrics: RunMetrics
  version: string
}) {
  const choices = metrics.questions.filter((q) => questionType(metrics, q) === 'choice')
  const targets = answered(metrics)
  const [question, setQuestion] = useState<string | null>(null)
  const [target, setTarget] = useState<string | null>(null)
  const q = question ?? choices[0] ?? null
  const t = target ?? targets[0] ?? null
  const matrix = useLoad(
    () => (q && t ? api.getConfusion(runId, q, t) : Promise.resolve(null)),
    `${runId}:${version}:${q}:${t}`,
  )
  if (!q || !t) return <EmptyState label="No choice questions" />
  const m = matrix.data
  const lowest = m
    ? m.recall.reduce<{ option: string; recall: number } | null>(
        (worst, recall, i) =>
          recall !== null && (worst === null || recall < worst.recall)
            ? { option: m.options[i], recall }
            : worst,
        null,
      )
    : null
  return (
    <div>
      {choices.length > 1 ? (
        <Subtabs label="Question" options={choices} value={q} onChange={setQuestion} />
      ) : null}
      <Subtabs label="Target" options={targets} value={t} onChange={setTarget} />
      {matrix.error ? <ApiErrorState error={matrix.error} onRetry={matrix.reload} /> : null}
      {m ? (
        <div className="flex flex-wrap items-start gap-5">
          <table className="border-separate border-spacing-[3px]">
            <thead>
              <tr>
                <td />
                <th
                  colSpan={m.options.length}
                  className="font-display text-[13px] font-semibold text-faint [font-stretch:80%]"
                >
                  Answered
                </th>
              </tr>
              <tr>
                <th className="px-2 text-right font-display text-[13px] font-semibold text-faint [font-stretch:80%]">
                  Expected
                </th>
                {m.options.map((o) => (
                  <th key={o} scope="col" className="px-2 text-sm font-medium text-dim">
                    {o}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.counts.map((row, i) => {
                const total = row.reduce((a, b) => a + b, 0)
                return (
                  <tr key={m.options[i]}>
                    <th scope="row" className="px-2 text-right text-sm font-medium text-dim">
                      {m.options[i]}
                    </th>
                    {row.map((count, j) => {
                      if (i === j) {
                        const v = 0.3 + (total ? count / total : 0) * 0.7
                        return (
                          <td
                            key={j}
                            className="h-[50px] w-16 rounded-[3px] text-center text-[16px] font-semibold"
                            style={{ background: heat(v), color: ink(v) }}
                          >
                            {count}
                          </td>
                        )
                      }
                      return count ? (
                        <td
                          key={j}
                          className="h-[50px] w-16 rounded-[3px] bg-broken-bg text-center text-[16px] font-semibold text-err-ink"
                        >
                          {count}
                        </td>
                      ) : (
                        <td
                          key={j}
                          className="h-[50px] w-16 rounded-[3px] bg-surface text-center text-[16px] font-semibold text-faint"
                        >
                          0
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="max-w-[220px] text-[13px] text-dim">
            <b className="block font-display text-[26px] leading-tight font-extrabold text-text [font-stretch:70%]">
              {m.correct} of {m.total}
            </b>
            correct
            {lowest ? (
              <p className="mt-4 mb-0">
                Lowest recall: <strong className="text-text">{lowest.option}</strong>,{' '}
                {Math.round(lowest.recall * 100)}%
              </p>
            ) : null}
          </div>
        </div>
      ) : matrix.loading ? (
        <table>
          <tbody>
            <LoadingRows rows={4} columns={5} />
          </tbody>
        </table>
      ) : null}
    </div>
  )
}

export function CalibrationPanel({
  runId,
  metrics,
  version,
}: {
  runId: string
  metrics: RunMetrics
  version: string
}) {
  const questions = metrics.questions.filter((q) => questionType(metrics, q) !== 'score')
  const targets = metrics.targets
    .filter((t) => t.results > 0 && t.probabilities)
    .map((t) => t.target)
  const [question, setQuestion] = useState<string | null>(null)
  const [target, setTarget] = useState<string | null>(null)
  const q = question ?? questions[0] ?? null
  const t = target ?? targets[0] ?? null
  const table = useLoad(
    () => (q && t ? api.getCalibration(runId, q, t) : Promise.resolve(null)),
    `${runId}:${version}:${q}:${t}`,
  )
  if (!q || !t) return <EmptyState label="No targets with probabilities" />
  const c = table.data
  return (
    <div>
      <Subtabs label="Question" options={questions} value={q} onChange={setQuestion} />
      <Subtabs label="Target" options={targets} value={t} onChange={setTarget} />
      {table.error ? <ApiErrorState error={table.error} onRetry={table.reload} /> : null}
      {c ? (
        <>
          <table className="w-full table-fixed border-separate border-spacing-0.5">
            <thead>
              <tr>
                {['Probability', 'Cases', 'Predicted', 'Observed'].map((h) => (
                  <th
                    key={h}
                    className="px-2 py-1 text-right text-sm font-medium text-dim first:text-left"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {c.bins.map((bin) => (
                <tr key={bin.lower}>
                  <th
                    scope="row"
                    className="h-8 rounded-[2px] bg-surface px-2 text-left text-sm font-normal"
                  >
                    {bin.lower.toFixed(1)} to {bin.upper.toFixed(1)}
                  </th>
                  <td className="rounded-[2px] bg-surface px-2 text-right">{bin.count}</td>
                  {[bin.mean_predicted, bin.observed_rate].map((v, i) =>
                    v === null ? (
                      <td key={i} className="rounded-[2px] bg-surface px-2 text-right text-faint">
                        None
                      </td>
                    ) : (
                      <td
                        key={i}
                        className="rounded-[2px] px-2 text-right"
                        style={{ background: heat(v), color: ink(v) }}
                      >
                        {v.toFixed(3)}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 mb-0 text-[13px] text-dim">
            Expected calibration error{' '}
            <b className="text-text">{c.ece === null ? 'None' : c.ece.toFixed(3)}</b>, {c.n} answers
          </p>
        </>
      ) : null}
    </div>
  )
}

function answerText(value: AnswerValue | null) {
  if (value === null) return 'None'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function AnswerCell({
  answer,
  probability,
}: {
  answer: AnswerValue | null
  probability: number | null
}) {
  if (probability === null) {
    return (
      <td className="h-11 rounded-[2px] bg-surface px-2 font-semibold">{answerText(answer)}</td>
    )
  }
  return (
    <td
      className="h-11 rounded-[2px] px-2"
      style={{ background: heat(probability), color: ink(probability) }}
    >
      <b className="font-semibold">{answerText(answer)}</b> {probability.toFixed(2)}
    </td>
  )
}

const RESULT: Record<string, { label: string; className: string }> = {
  fixed: { label: 'Fixed', className: 'bg-fixed-bg text-ok' },
  broken: { label: 'Broken', className: 'bg-broken-bg text-err' },
  changed: { label: 'Changed', className: 'bg-surface text-dim' },
}

export function ChangesPanel({ run, baselines }: { run: RunSummary; baselines: string[] }) {
  const [picked, setPicked] = useState<string | null>(null)
  const baseline = picked ?? run.baseline ?? baselines[0] ?? null
  const changes = useLoad(
    () => (baseline ? api.getChanges(run.id, baseline) : Promise.resolve(null)),
    `${run.id}:${run.status}:${baseline}`,
  )
  const options =
    run.baseline && !baselines.includes(run.baseline) ? [run.baseline, ...baselines] : baselines
  if (!baseline) return <EmptyState label="No earlier run of this suite" />
  const data = changes.data
  const first = data?.changes[0]?.case_id
  return (
    <div>
      <label className="mb-2.5 flex items-center gap-2 text-sm text-dim">
        Baseline
        <select
          value={baseline}
          onChange={(e) => setPicked(e.target.value)}
          className="rounded border border-line bg-bg px-2 py-1 text-sm text-text"
        >
          {options.map((id) => (
            <option key={id} value={id}>
              Run {id}
            </option>
          ))}
        </select>
      </label>
      {changes.error ? <ApiErrorState error={changes.error} onRetry={changes.reload} /> : null}
      {data && data.changes.length === 0 ? <EmptyState label="No changed answers" /> : null}
      {data && data.changes.length > 0 ? (
        <>
          <table className="w-full table-fixed border-separate border-spacing-0.5">
            <thead>
              <tr>
                {[
                  'Case',
                  'Target',
                  'Question',
                  `Run ${data.baseline}`,
                  `Run ${run.id}`,
                  'Expected',
                  'Result',
                ].map((h) => (
                  <th key={h} className="px-2 py-1 text-left text-sm font-medium text-dim">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.changes.map((change) => {
                const result = RESULT[change.status] ?? RESULT.changed
                return (
                  <tr key={`${change.case_id}:${change.target}:${change.question}`}>
                    <td className="h-11 truncate rounded-[2px] bg-surface px-2 font-mono text-sm text-pick">
                      <Link
                        to={`/runs/${encodeURIComponent(run.id)}/changes/${encodeURIComponent(change.case_id)}?baseline=${encodeURIComponent(data.baseline)}`}
                        className="text-pick no-underline hover:underline"
                      >
                        {change.case_id}
                      </Link>
                    </td>
                    <td
                      className="truncate rounded-[2px] bg-surface px-2 text-sm text-dim"
                      title={change.target}
                    >
                      {change.target}
                    </td>
                    <td className="rounded-[2px] bg-surface px-2 font-mono text-sm">
                      {change.question}
                    </td>
                    <AnswerCell
                      answer={change.baseline_answer}
                      probability={change.baseline_probability}
                    />
                    <AnswerCell answer={change.answer} probability={change.probability} />
                    <td className="rounded-[2px] bg-surface px-2">{answerText(change.expected)}</td>
                    <td className={`rounded-[2px] px-2 text-center font-[650] ${result.className}`}>
                      {result.label}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-center gap-6 text-[13px] text-dim">
            {data.summary.map((s) => (
              <span key={s.target}>
                {s.target}: <b className="text-text">{s.fixed}</b> fixed,{' '}
                <b className="text-text">{s.broken}</b> broken
                {s.mcnemar_p !== null ? (
                  <>
                    , McNemar&apos;s <b className="text-text">p = {s.mcnemar_p.toFixed(2)}</b>
                  </>
                ) : null}
              </span>
            ))}
            {first ? (
              <Link
                to={`/runs/${encodeURIComponent(run.id)}/changes/${encodeURIComponent(first)}?baseline=${encodeURIComponent(data.baseline)}`}
                className="no-underline"
              >
                <span className="inline-block rounded border border-line bg-raise px-3.5 py-[7px] font-medium text-text hover:border-faint">
                  Step through changes
                </span>
              </Link>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}

export function Panel({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section aria-label={title} className="min-w-0">
      <PanelHeading note={note}>{title}</PanelHeading>
      {children}
    </section>
  )
}
