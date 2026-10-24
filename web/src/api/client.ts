// The typed client over the jevtester API. Every failed call throws: an
// ApiError when the server answered with its error envelope, or a
// ServerUnreachableError when no answer came back at all.
import type {
  ApiErrorBody,
  CaseCreated,
  CaseInput,
  DecideBody,
  DecideResponse,
  ErrorDetail,
  QuestionSetVersions,
  RunCreate,
  RunCreated,
  SuiteDetail,
  SuiteList,
  TargetList,
} from './types'
import { useServer } from './server-store'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly field: string | null
  readonly details: ErrorDetail[]

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.field = body.field
    this.details = body.details
  }
}

const GATEWAY_STATUSES = new Set([502, 503, 504])

export class ServerUnreachableError extends Error {
  constructor(cause: unknown) {
    super("Can't reach the jevtester server", { cause })
    this.name = 'ServerUnreachableError'
  }
}

function isErrorEnvelope(value: unknown): value is { error: ApiErrorBody } {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error = (value as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}

async function request<T>(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    useServer.getState().setUnreachable(true)
    throw new ServerUnreachableError(error)
  }
  const parsed: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    if (isErrorEnvelope(parsed)) {
      useServer.getState().setUnreachable(false)
      throw new ApiError(response.status, parsed.error)
    }
    // The API never sends these. In development they're the Vite proxy
    // saying nothing answers at 127.0.0.1:8640.
    if (GATEWAY_STATUSES.has(response.status)) {
      useServer.getState().setUnreachable(true)
      throw new ServerUnreachableError(`${method} /api${path} returned ${response.status}`)
    }
    useServer.getState().setUnreachable(false)
    throw new ApiError(response.status, {
      code: 'internal',
      message: `${method} /api${path} returned ${response.status}`,
      field: null,
      details: [],
    })
  }
  useServer.getState().setUnreachable(false)
  if (parsed === undefined) {
    throw new ApiError(response.status, {
      code: 'internal',
      message: `${method} /api${path} returned a body that isn't JSON`,
      field: null,
      details: [],
    })
  }
  return parsed as T
}

export const api = {
  listTargets: () => request<TargetList>('GET', '/targets'),
  checkTargets: () => request<TargetList>('POST', '/targets/check'),
  decide: (body: DecideBody, signal?: AbortSignal) =>
    request<DecideResponse>('POST', '/decide', body, signal),
  listSuites: () => request<SuiteList>('GET', '/suites'),
  getSuite: (name: string) => request<SuiteDetail>('GET', `/suites/${encodeURIComponent(name)}`),
  addCase: (suite: string, body: CaseInput) =>
    request<CaseCreated>('POST', `/suites/${encodeURIComponent(suite)}/cases`, body),
  listVersions: (questionSet: string) =>
    request<QuestionSetVersions>(
      'GET',
      `/question-sets/${encodeURIComponent(questionSet)}/versions`,
    ),
  startRun: (body: RunCreate) => request<RunCreated>('POST', '/runs', body),
}
