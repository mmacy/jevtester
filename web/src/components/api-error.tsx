import { ApiError, ServerUnreachableError } from '../api/client'
import { ErrorState } from './states'

/** Shows a failed call. An unreachable server shows in the bar under the top bar instead. */
export function ApiErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ServerUnreachableError) return null
  if (error instanceof ApiError) {
    return (
      <ErrorState
        code={error.code}
        message={error.message}
        details={error.details}
        onRetry={onRetry}
      />
    )
  }
  return <ErrorState code="internal" message={String(error)} onRetry={onRetry} />
}
