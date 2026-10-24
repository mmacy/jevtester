import type { QuestionDraft, QuestionType } from '../lib/request'
import { FieldErrors, IconButton, TextInput } from './fields'
import { Segmented } from './segmented'

const TYPES: readonly { value: QuestionType; label: string }[] = [
  { value: 'noul', label: 'Yes or no' },
  { value: 'choice', label: 'Choice' },
  { value: 'score', label: 'Score' },
]

interface QuestionCardProps {
  question: QuestionDraft
  errors?: readonly string[]
  onChange: (question: QuestionDraft) => void
  onRemove?: () => void
}

function move<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

function RowActions({
  index,
  count,
  noun,
  onMove,
  onRemove,
}: {
  index: number
  count: number
  noun: string
  onMove: (to: number) => void
  onRemove: () => void
}) {
  return (
    <>
      <IconButton
        label={`Move ${noun} up`}
        disabled={index === 0}
        onClick={() => onMove(index - 1)}
      >
        ↑
      </IconButton>
      <IconButton
        label={`Move ${noun} down`}
        disabled={index === count - 1}
        onClick={() => onMove(index + 1)}
      >
        ↓
      </IconButton>
      <IconButton label={`Remove ${noun}`} onClick={onRemove}>
        ✕
      </IconButton>
    </>
  )
}

/** One question in the full request: its id, type, wording, and options or levels. */
export function QuestionCard({ question, errors, onChange, onRemove }: QuestionCardProps) {
  const update = (patch: Partial<QuestionDraft>) => onChange({ ...question, ...patch })
  return (
    <section
      aria-label={`Question ${question.id}`}
      className="mt-2.5 rounded border border-line bg-bg"
    >
      <header className="flex items-center gap-2 border-b border-line-soft px-2.5 py-1.5">
        <input
          aria-label="Question id"
          value={question.id}
          onChange={(e) => update({ id: e.target.value })}
          className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 font-mono text-sm text-pick hover:border-line focus:border-pick focus:outline-none"
        />
        <Segmented
          label="Type"
          options={TYPES}
          value={question.type}
          onChange={(type) => update({ type })}
        />
        {onRemove ? (
          <IconButton label="Remove question" onClick={onRemove}>
            ✕
          </IconButton>
        ) : null}
      </header>
      <div className="px-2.5 py-2">
        <TextInput
          aria-label="Question"
          value={question.instructions}
          onChange={(e) => update({ instructions: e.target.value })}
        />
        {question.type === 'choice' ? (
          <ol className="m-0 mt-2 list-none space-y-1 p-0">
            {question.options.map((option, i) => (
              <li
                key={i}
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-1 rounded border border-line-soft p-1"
              >
                <TextInput
                  aria-label={`Option ${i + 1} name`}
                  value={option.name}
                  className="py-1 font-mono text-sm"
                  onChange={(e) =>
                    update({
                      options: question.options.map((o, j) =>
                        j === i ? { ...o, name: e.target.value } : o,
                      ),
                    })
                  }
                />
                <span className="flex gap-1">
                  <RowActions
                    index={i}
                    count={question.options.length}
                    noun="option"
                    onMove={(to) => update({ options: move(question.options, i, to) })}
                    onRemove={() => update({ options: question.options.filter((_, j) => j !== i) })}
                  />
                </span>
                <TextInput
                  aria-label={`Option ${i + 1} description`}
                  value={option.description}
                  className="col-span-2 py-1 text-sm"
                  onChange={(e) =>
                    update({
                      options: question.options.map((o, j) =>
                        j === i ? { ...o, description: e.target.value } : o,
                      ),
                    })
                  }
                />
              </li>
            ))}
            <li>
              <button
                type="button"
                className="cursor-pointer text-sm text-dim hover:text-text"
                onClick={() =>
                  update({ options: [...question.options, { name: '', description: '' }] })
                }
              >
                Add option
              </button>
            </li>
          </ol>
        ) : null}
        {question.type === 'score' ? (
          <ol className="m-0 mt-2 list-none space-y-1 p-0">
            {question.levels.map((level, i) => (
              <li key={i} className="flex items-center gap-1">
                <span className="w-5 shrink-0 text-right font-mono text-sm text-faint">{i}</span>
                <TextInput
                  aria-label={`Level ${i}`}
                  value={level}
                  className="py-1 text-sm"
                  onChange={(e) =>
                    update({
                      levels: question.levels.map((l, j) => (j === i ? e.target.value : l)),
                    })
                  }
                />
                <RowActions
                  index={i}
                  count={question.levels.length}
                  noun="level"
                  onMove={(to) => update({ levels: move(question.levels, i, to) })}
                  onRemove={() => update({ levels: question.levels.filter((_, j) => j !== i) })}
                />
              </li>
            ))}
            <li>
              <button
                type="button"
                className="cursor-pointer text-sm text-dim hover:text-text"
                onClick={() => update({ levels: [...question.levels, ''] })}
              >
                Add level
              </button>
            </li>
          </ol>
        ) : null}
        <FieldErrors errors={errors} />
      </div>
    </section>
  )
}
