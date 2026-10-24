import { ApiError } from './errors'
import type {
  Candidate,
  CandidatesResponse,
  DetectSupplierResponse,
  ExcelDownload,
  ExportResponse,
  Mapping,
  MappingsListResponse,
  ProductSearchResponse,
  SessionCreateResponse,
  SessionSummary,
  SettingsResponse,
  SupplierInfo,
} from './types'

const API_BASE = '/api'

async function parseError(response: Response): Promise<ApiError> {
  let detail = `خطای سرور (${response.status})`
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'string'
    ) {
      detail = (body as { detail: string }).detail
    }
  } catch {
    /* ignore JSON parse failures */
  }
  return new ApiError(response.status, detail)
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    throw await parseError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export type HealthResponse = {
  status: string
  app: string
  version: string
  control_token: string
}

export const api = {
  health: () => requestJson<HealthResponse>('/health'),

  shutdown: (controlToken: string) =>
    requestJson<{ status: string }>('/shutdown', {
      method: 'POST',
      headers: { 'X-GheymatYar-Token': controlToken },
    }),


  listSuppliers: () => requestJson<SupplierInfo[]>('/suppliers'),

  getSettings: () => requestJson<SettingsResponse>('/settings'),

  updateSettings: (settings: Record<string, string>) =>
    requestJson<SettingsResponse>('/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings }),
    }),

  listMappings: (supplierKey: string) =>
    requestJson<MappingsListResponse>(
      `/suppliers/${encodeURIComponent(supplierKey)}/mappings`,
    ),

  updateMapping: (
    supplierKey: string,
    mappingId: number,
    body: { pioneers_name_raw: string; pioneers_code?: string | null },
  ) =>
    requestJson<Mapping>(
      `/suppliers/${encodeURIComponent(supplierKey)}/mappings/${mappingId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),

  deleteMapping: (supplierKey: string, mappingId: number) =>
    requestJson<void>(
      `/suppliers/${encodeURIComponent(supplierKey)}/mappings/${mappingId}`,
      { method: 'DELETE' },
    ),

  createSession: () =>
    requestJson<SessionCreateResponse>('/sessions', { method: 'POST' }),

  getSession: (sessionId: string) =>
    requestJson<SessionSummary>(`/sessions/${encodeURIComponent(sessionId)}`),

  uploadPioneersExcel: (sessionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<SessionSummary>(
      `/sessions/${encodeURIComponent(sessionId)}/pioneers-excel`,
      { method: 'POST', body: form },
    )
  },

  detectSupplierPdf: (sessionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<DetectSupplierResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/supplier-pdf/detect`,
      { method: 'POST', body: form },
    )
  },

  confirmSupplierPdf: (sessionId: string, supplierKey: string) =>
    requestJson<SessionSummary>(
      `/sessions/${encodeURIComponent(sessionId)}/supplier-pdf/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ supplier_key: supplierKey }),
      },
    ),

  uploadSupplierPdf: (sessionId: string, supplierKey: string, file: File) => {
    const form = new FormData()
    form.append('supplier_key', supplierKey)
    form.append('file', file)
    return requestJson<SessionSummary>(
      `/sessions/${encodeURIComponent(sessionId)}/supplier-pdf`,
      { method: 'POST', body: form },
    )
  },

  runMatch: (sessionId: string, suspiciousPercentThreshold?: string) =>
    requestJson<CandidatesResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/match`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          suspiciousPercentThreshold
            ? { suspicious_percent_threshold: suspiciousPercentThreshold }
            : {},
        ),
      },
    ),

  listCandidates: (sessionId: string, status?: string) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : ''
    return requestJson<CandidatesResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/candidates${qs}`,
    )
  },

  preview: (sessionId: string) =>
    requestJson<CandidatesResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/preview`,
    ),

  searchProducts: (sessionId: string, q: string, limit = 25) =>
    requestJson<ProductSearchResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/pioneers-products/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  confirmMapping: (
    sessionId: string,
    candidateId: string,
    pioneersRowNumber: number,
    save = true,
  ) =>
    requestJson<Candidate>(
      `/sessions/${encodeURIComponent(sessionId)}/candidates/${encodeURIComponent(candidateId)}/confirm-mapping`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pioneers_row_number: pioneersRowNumber,
          save,
        }),
      },
    ),

  ignoreCandidate: (sessionId: string, candidateId: string) =>
    requestJson<Candidate>(
      `/sessions/${encodeURIComponent(sessionId)}/candidates/${encodeURIComponent(candidateId)}/ignore`,
      { method: 'POST' },
    ),

  restoreCandidate: (sessionId: string, candidateId: string) =>
    requestJson<Candidate>(
      `/sessions/${encodeURIComponent(sessionId)}/candidates/${encodeURIComponent(candidateId)}/restore`,
      { method: 'POST' },
    ),

  setReview: (
    sessionId: string,
    candidateId: string,
    decision: 'INCLUDE' | 'EXCLUDE' | 'APPROVE',
  ) =>
    requestJson<Candidate>(
      `/sessions/${encodeURIComponent(sessionId)}/candidates/${encodeURIComponent(candidateId)}/review`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      },
    ),

  exportExcel: (sessionId: string) =>
    requestJson<ExportResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/export`,
      { method: 'POST' },
    ),

  downloadExcel: async (sessionId: string): Promise<ExcelDownload> => {
    const response = await fetch(
      `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/download`,
    )
    if (!response.ok) {
      throw await parseError(response)
    }
    const exportedRowCount = Number(response.headers.get('X-Exported-Row-Count'))
    const contentSha256 = response.headers.get('X-Export-Content-Sha256') ?? ''
    if (!Number.isInteger(exportedRowCount) || exportedRowCount < 1 || !contentSha256) {
      throw new ApiError(
        response.status,
        'تعداد ردیف‌های فایل خروجی با انتخاب تأییدشده یکی نیست. فایل دانلود نشد.',
      )
    }
    return {
      blob: await response.blob(),
      exportedRowCount,
      contentSha256,
    }
  },
}
