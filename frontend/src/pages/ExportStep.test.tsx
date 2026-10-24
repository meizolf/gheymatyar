import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { summaryFixture } from '../test/fixtures'
import { WorkflowProvider, useWorkflow } from '../workflow/WorkflowContext'
import { ExportStep } from './ExportStep'

vi.mock('../api/client', () => ({
  api: {
    getSession: vi.fn(),
    exportExcel: vi.fn(),
    downloadExcel: vi.fn(),
    createSession: vi.fn(),
  },
}))

import { api } from '../api/client'

function Seed({ children }: { children: ReactNode }) {
  const { setSessionId } = useWorkflow()
  useEffect(() => {
    setSessionId('sess-1')
  }, [setSessionId])
  return children
}

function renderExport() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <WorkflowProvider>
        <Seed>
          <ExportStep />
        </Seed>
      </WorkflowProvider>
    </QueryClientProvider>,
  )
}

describe('ExportStep', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.mocked(api.getSession).mockResolvedValue(summaryFixture)
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:mock'),
      revokeObjectURL: vi.fn(),
    })
  })

  it('disables export while running and downloads on success', async () => {
    const user = userEvent.setup()
    let resolveExport!: (v: unknown) => void
    vi.mocked(api.exportExcel).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveExport = resolve
        }) as never,
    )
    vi.mocked(api.downloadExcel).mockResolvedValue(new Blob(['xlsx']))
    renderExport()
    const btn = await screen.findByRole('button', {
      name: /تولید و دانلود اکسل/,
    })
    await user.click(btn)
    expect(await screen.findByRole('button', { name: /در حال تولید/ })).toBeDisabled()
    resolveExport({
      session_id: 'sess-1',
      output_filename: 'out.xlsx',
      updated_count: 3,
      exported_row_count: 3,
      download_path: '/api/sessions/sess-1/download',
    })
    await waitFor(() => {
      expect(api.downloadExcel).toHaveBeenCalled()
    })
    expect(await screen.findByText(/3 ردیف محصول/)).toBeInTheDocument()
  })

  it('does not show success when the exported row count disagrees', async () => {
    const user = userEvent.setup()
    vi.mocked(api.exportExcel).mockResolvedValue({
      session_id: 'sess-1',
      output_filename: 'out.xlsx',
      updated_count: 9,
      exported_row_count: 6700,
      download_path: '/api/sessions/sess-1/download',
    })
    renderExport()
    await user.click(
      await screen.findByRole('button', { name: /تولید و دانلود اکسل/ }),
    )
    expect(
      await screen.findByText(/با انتخاب تأییدشده یکی نیست/),
    ).toBeInTheDocument()
    expect(api.downloadExcel).not.toHaveBeenCalled()
    expect(screen.queryByText(/ردیف محصول/)).not.toBeInTheDocument()
  })

  it('shows API failure messages', async () => {
    const user = userEvent.setup()
    vi.mocked(api.exportExcel).mockRejectedValue(
      new ApiError(400, 'no exportable candidates'),
    )
    renderExport()
    await user.click(
      await screen.findByRole('button', { name: /تولید و دانلود اکسل/ }),
    )
    expect(
      await screen.findByText(/هیچ ردیف قابل خروجی وجود ندارد/),
    ).toBeInTheDocument()
  })

  it('states only main sale price is updated', async () => {
    renderExport()
    expect(await screen.findByRole('heading', { name: 'تولید فایل اکسل' })).toBeInTheDocument()
    expect(screen.getAllByText(/نرخ فروش اصلی/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/دست‌نخورده/).length).toBeGreaterThan(0)
  })
})

