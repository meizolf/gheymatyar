/** Centralized API error type. */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly sessionExpired: boolean
  /** Structured error body, e.g. a 409 duplicate-mapping conflict. */
  readonly data?: Record<string, unknown>

  constructor(status: number, detail: string, data?: Record<string, unknown>) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
    this.sessionExpired = status === 404 && /session not found/i.test(detail)
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}
