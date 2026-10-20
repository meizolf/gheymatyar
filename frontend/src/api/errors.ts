/** Centralized API error type. */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly sessionExpired: boolean

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.sessionExpired = status === 404 && /session not found/i.test(detail)
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}
