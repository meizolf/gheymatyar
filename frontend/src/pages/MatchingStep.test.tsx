import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { candidatesResponseFixture, summaryFixture } from '../test/fixtures'
import { WorkflowProvider, useWorkflow } from '../workflow/WorkflowContext'
import { MatchingStep } from './MatchingStep'

vi.mock('../api/client', () => ({
  api: {
    listCandidates: vi.fn(),
    confirmMapping: vi.fn(),
    getSession: vi.fn(),
    searchProducts: vi.fn(),
    createSession: vi.fn(),
  },
}))

import { api } from '../api/client'

function SeedSession({ children }: { children: ReactNode }) {
  const { setSessionId, setMatchedDone } = useWorkflow()
  useEffect(() => {
    setSessionId('sess-1')
    setMatchedDone(true)
  }, [setSessionId, setMatchedDone])
  return children
}

function renderMatching() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <WorkflowProvider>
        <SeedSession>
          <MatchingStep />
        </SeedSession>
      </WorkflowProvider>
    </QueryClientProvider>,
  )
}

describe('MatchingStep', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.mocked(api.listCandidates).mockResolvedValue(
      structuredClone(candidatesResponseFixture),
    )
    vi.mocked(api.searchProducts).mockResolvedValue({ results: [] })
    vi.mocked(api.getSession).mockResolvedValue(summaryFixture)
  })

  it('shows matched unmatched and ambiguous groups', async () => {
    renderMatching()
    expect(await screen.findByText('محصول الف تأمین')).toBeInTheDocument()
    expect(screen.getAllByText('محصول ج تأمین').length).toBeGreaterThan(0)
    expect(screen.getAllByText('محصول د مبهم').length).toBeGreaterThan(0)
    expect(screen.getByText(/حل‌نشده/)).toBeInTheDocument()
  })

  it('filters by unmatched tab', async () => {
    const user = userEvent.setup()
    renderMatching()
    await screen.findByText('محصول الف تأمین')
    await user.click(screen.getByRole('tab', { name: 'بدون تطابق' }))
    const table = screen.getByRole('table')
    expect(within(table).getByText('محصول ج تأمین')).toBeInTheDocument()
    expect(within(table).queryByText('محصول الف تأمین')).not.toBeInTheDocument()
    expect(within(table).queryByText('محصول د مبهم')).not.toBeInTheDocument()
  })

  it('shows confirm-mapping API errors', async () => {
    const user = userEvent.setup()
    vi.mocked(api.confirmMapping).mockRejectedValue(
      new ApiError(400, 'no Pioneers product at row 99'),
    )
    renderMatching()
    await screen.findByText('محصول ج تأمین')
    const table = screen.getByRole('table')
    const unmatchedRow = within(table)
      .getAllByRole('row')
      .find((r) => within(r).queryByText('محصول ج تأمین'))!
    await user.click(within(unmatchedRow).getByRole('button', { name: /تطابق دستی/ }))
    await user.click(screen.getByRole('button', { name: /محصول ج پیشنهادی/ }))
    await user.click(screen.getByRole('button', { name: /تأیید و ذخیره نگاشت/ }))
    expect(
      await screen.findByText(/محصول پایونیرز در ردیف 99/),
    ).toBeInTheDocument()
  })

  it('saves manual mapping via API', async () => {
    const user = userEvent.setup()
    vi.mocked(api.confirmMapping).mockResolvedValue(
      candidatesResponseFixture.candidates[0],
    )
    vi.mocked(api.getSession).mockResolvedValue(summaryFixture)
    renderMatching()
    await screen.findByText('محصول ج تأمین')
    const table = screen.getByRole('table')
    const unmatchedRow = within(table)
      .getAllByRole('row')
      .find((r) => within(r).queryByText('محصول ج تأمین'))!
    await user.click(within(unmatchedRow).getByRole('button', { name: /تطابق دستی/ }))
    await user.click(screen.getByRole('button', { name: /محصول ج پیشنهادی/ }))
    await user.click(screen.getByRole('button', { name: /تأیید و ذخیره نگاشت/ }))
    await waitFor(() => {
      expect(api.confirmMapping).toHaveBeenCalledWith('sess-1', 'c3', 20, true)
    })
  })
})
