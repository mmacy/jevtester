// The `jevtester decide` command that sends the same request from a shell.
import type { RequestBody } from './request'

/** Quotes a value for a POSIX shell. */
export function shellQuote(value: string): string {
  if (/^[\w@%+=:,./-]+$/.test(value)) return value
  return `'${value.replaceAll("'", `'\\''`)}'`
}

function targetFlags(targets: readonly string[]): string[] {
  return targets.map((t) => `--target ${shellQuote(t)}`)
}

/**
 * The command for a request. A text state with one question uses flags.
 * Anything else sends the request as JSON on stdin.
 */
export function cliCommand(body: RequestBody, targets: readonly string[]): string {
  const entries = Object.entries(body.questions)
  if (typeof body.state === 'string' && entries.length === 1) {
    const [id, question] = entries[0]
    const flags = [
      `--state ${shellQuote(body.state)}`,
      `--question ${shellQuote(question.instructions)}`,
    ]
    // The CLI names a lone question `question` unless told otherwise.
    if (id !== 'question') flags.push(`--id ${shellQuote(id)}`)
    if (question.type === 'choice') {
      for (const [name, description] of Object.entries(question.criteria)) {
        flags.push(`--option ${shellQuote(`${name}=${description}`)}`)
      }
    }
    if (question.type === 'score') {
      for (const level of question.criteria) flags.push(`--level ${shellQuote(level)}`)
    }
    flags.push(...targetFlags(targets), '--format json')
    return ['uv run jevtester decide', ...flags].join(' \\\n  ')
  }
  const flags = ['--request -', ...targetFlags(targets), '--format json']
  const json = JSON.stringify({ state: body.state, questions: body.questions }, null, 2)
  return `uv run jevtester decide ${flags.join(' ')} <<'JSON'\n${json}\nJSON`
}
