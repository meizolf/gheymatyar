import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { ApiError } from './errors'

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists suppliers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [{ key: 'azin_pipe', display_name: 'آذین لوله' }],
      }),
    )
    const list = await api.listSuppliers()
    expect(list[0].key).toBe('azin_pipe')
  })

  it('maps session-not-found to ApiError.sessionExpired', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'session not found' }),
      }),
    )
    await expect(api.getSession('gone')).rejects.toSatisfy((err: unknown) => {
      return err instanceof ApiError && err.sessionExpired
    })
  })

  it('uploads pioneers excel as multipart', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 's1',
        product_count: 10,
        pioneers_filename: 'a.xlsx',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['x'], 'a.xlsx')
    await api.uploadPioneersExcel('s1', file)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/s1/pioneers-excel',
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    )
  })

  it('sends local control token on shutdown', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'shutting_down' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.shutdown('test-token-value')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/shutdown',
      expect.objectContaining({
        method: 'POST',
        headers: { 'X-GheymatYar-Token': 'test-token-value' },
      }),
    )
  })

  it('keeps the structured body of a 409 duplicate-mapping error', async () => {
    const detail = {
      code: 'duplicate_mapping_target',
      message: 'Pioneers product 11489 is already mapped to supplier product «الف»',
      pioneers_code: '11489',
      pioneers_name: 'کالا',
      conflicts: [{ supplier_name: 'الف' }],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail }) }),
    )
    await expect(api.confirmMapping('s1', 'c1', 7, true)).rejects.toSatisfy(
      (err: unknown) =>
        err instanceof ApiError &&
        err.status === 409 &&
        err.detail === detail.message &&
        err.data?.pioneers_code === '11489',
    )
  })

  it('prevents duplicate export by returning a promise the UI awaits', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 's1',
        format: 'xls',
        output_filename: 'out.xls',
        updated_count: 1,
        exported_row_count: 1,
        download_path: '/api/sessions/s1/download',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await api.exportExcel('s1')
    expect(result.updated_count).toBe(1)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/s1/export',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
