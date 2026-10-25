// Labels for the contract's warning and error codes.
import type { components } from '../api/generated'

type WarningCode = components['schemas']['WarningCode']
type ErrorCode = components['schemas']['ErrorCode']

export const WARNING_LABELS: Record<WarningCode, string> = {
  missing_answer: 'Missing answer',
  invalid_answer: 'Invalid answer',
  unknown_option: 'Unknown option',
  missing_probability: 'Missing probability',
  unexpected_answer: 'Unexpected answer',
  strict_parse_failed: 'Strict parse failed',
  truncation_on: 'Truncation on',
  state_may_truncate: 'May truncate state',
}

export const ERROR_LABELS: Record<ErrorCode, string> = {
  not_ready: 'Not ready',
  preflight: 'Failed preflight',
  auth: 'Sign-in failed',
  rate_limited: 'Rate limited',
  bad_request: 'Bad request',
  request_too_large: 'Request too large',
  server_error: 'Server error',
  timeout: 'Timed out',
  connection: 'No connection',
  invalid_response: 'Invalid response',
}

/** The label for a code, or the code itself when it isn't one the contract lists. */
export function codeLabel(labels: Record<string, string>, code: string): string {
  return labels[code] ?? code
}
