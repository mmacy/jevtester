// Short names for the generated API types. Never a hand-written copy of a
// backend shape: a schema that disappears from the contract fails tsc here.
import type { components } from './generated'

type Schemas = components['schemas']

export type ApiErrorBody = Schemas['ApiErrorBody']
export type ApiErrorCode = Schemas['ApiErrorCode']
export type Capabilities = Schemas['Capabilities']
export type DecideBody = Schemas['DecideBody']
export type DecideResponse = Schemas['DecideResponse']
export type ErrorDetail = Schemas['ErrorDetail']
export type ResultWarning = Schemas['ResultWarning']
export type TargetInfo = Schemas['TargetInfo']
export type TargetList = Schemas['TargetList']
export type TargetResult = Schemas['TargetResult']
export type TargetStatus = Schemas['TargetStatus']
