import { ApiError } from '../api/client'

/**
 * Field errors from the API, keyed by question id. A path like
 * `questions.intent.choice.criteria` goes to the question whose id it starts
 * with, matched against the ids in the editor so an id with a dot still
 * matches. Anything else goes under `''`.
 */
export function serverErrors(error: unknown, ids: readonly string[]): Record<string, string[]> {
  const byQuestion: Record<string, string[]> = {}
  if (!(error instanceof ApiError)) return byQuestion
  const longestFirst = [...ids].sort((a, b) => b.length - a.length)
  for (const detail of error.details) {
    const field = detail.field ?? ''
    const id =
      longestFirst.find((q) => field === `questions.${q}` || field.startsWith(`questions.${q}.`)) ??
      ''
    ;(byQuestion[id] ??= []).push(detail.message)
  }
  return byQuestion
}
