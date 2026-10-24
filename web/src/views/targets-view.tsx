import type { TargetInfo } from '../api/types'
import { ApiErrorState } from '../components/api-error'
import { Button } from '../components/button'
import { PanelHeading } from '../components/panel-heading'
import { EmptyState, LoadingRows, Spinner } from '../components/states'
import { CAPABILITY_ROWS, type CellTone } from '../lib/capabilities'
import { formatClock } from '../lib/format'
import { isReady, useTargets } from '../store/targets'

const TONE: Record<Exclude<CellTone, null>, string> = {
  ok: 'bg-ok-bg font-semibold text-ok',
  warn: 'bg-warn-bg text-warn',
  err: 'bg-err-bg text-err-ink',
  faint: 'text-faint',
}

function heading(targets: TargetInfo[] | null, checkedAt: string | null): string | undefined {
  if (!targets) return undefined
  if (!checkedAt) return 'Not checked'
  return `Checked ${formatClock(checkedAt)}, ${targets.filter(isReady).length} of ${targets.length} ready`
}

/** A target name that can break after its `@`, so a narrow column shows all of it. */
function TargetName({ name }: { name: string }) {
  const at = name.indexOf('@')
  if (at === -1) return name
  return (
    <>
      {name.slice(0, at + 1)}
      <wbr />
      {name.slice(at + 1)}
    </>
  )
}

export function TargetsView() {
  const { targets, checkedAt, loading, checking, error, load, check } = useTargets()
  const columns = targets?.length ?? 5

  return (
    <section className="max-w-[1440px] px-6 pt-5 pb-12">
      <PanelHeading note={heading(targets, checkedAt)}>Targets</PanelHeading>
      {error ? (
        <div className="mb-4">
          <ApiErrorState error={error} onRetry={targets ? check : load} />
        </div>
      ) : null}
      {targets && targets.length === 0 ? (
        <EmptyState label="No targets in jevtester.toml" />
      ) : (
        <div className="overflow-x-auto">
          <table className="mt-2 w-full min-w-[960px] table-fixed border-separate border-spacing-0.5">
            <thead>
              <tr>
                <th className="w-[210px]" />
                {targets?.map((target) => (
                  <th key={target.name} className="px-2.5 pb-2 text-left align-bottom font-normal">
                    <span
                      className="block font-display text-[17px] leading-tight font-bold [font-stretch:62.5%]"
                      title={target.name}
                    >
                      <TargetName name={target.name} />
                    </span>
                    <span className="block truncate text-xs text-dim">{target.label}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {targets ? (
                CAPABILITY_ROWS.map((row) => (
                  <tr key={row.label}>
                    <th scope="row" className="px-2.5 text-left text-[13px] font-medium text-dim">
                      {row.label}
                    </th>
                    {targets.map((target) => {
                      const cell = row.cell(target)
                      return (
                        <td
                          key={target.name}
                          data-tone={cell.tone ?? undefined}
                          className={`h-[42px] rounded-[2px] bg-surface px-2.5 py-1.5 text-[13.5px] leading-snug ${
                            cell.tone ? TONE[cell.tone] : ''
                          }`}
                        >
                          {cell.tone === 'err' ? (
                            <b className="block font-semibold text-err">{cell.text}</b>
                          ) : (
                            cell.text
                          )}
                          {cell.detail ? (
                            <span className="block text-xs font-normal opacity-90">
                              {cell.detail}
                            </span>
                          ) : null}
                        </td>
                      )
                    })}
                  </tr>
                ))
              ) : loading ? (
                <LoadingRows rows={CAPABILITY_ROWS.length} columns={columns + 1} />
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-5 flex items-center gap-2.5">
        <Button primary onClick={() => void check()} disabled={checking || loading}>
          Check all targets
        </Button>
        {checking ? <Spinner label="Checking targets" /> : null}
      </div>
    </section>
  )
}
