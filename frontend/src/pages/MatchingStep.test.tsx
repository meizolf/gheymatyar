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
    ignoreCandidate: vi.fn(),
    restoreCandidate: vi.fn(),
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
    await user.click(screen.getByRole('tab', { name: /بدون تطابق/ }))
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

  it('rejects a Pioneers product held by another supplier product (409)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.confirmMapping).mockRejectedValue(
      new ApiError(
        409,
        'Pioneers product 11489 is already mapped to supplier product «اذین لوله 25»; change or delete that mapping first',
        {
          code: 'duplicate_mapping_target',
          pioneers_code: '11489',
          pioneers_name: 'اذین لوله سه لایه 25',
          conflicts: [{ supplier_name: 'اذین لوله 25', source: 'saved_mapping' }],
        },
      ),
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
    const message = await screen.findByText(/قبلاً به کالای «اذین لوله 25» نگاشت شده است/)
    expect(message).toHaveTextContent('11489')
    expect(message).toHaveTextContent('اذین لوله سه لایه 25')
    expect(message).toHaveTextContent('ابتدا نگاشت قبلی را اصلاح یا حذف کنید')
    expect(screen.queryByText(/نگاشت ذخیره شد/)).not.toBeInTheDocument()
  })

  it('disables search results already held by another supplier product', async () => {
    const user = userEvent.setup()
    vi.mocked(api.searchProducts).mockResolvedValue({
      results: [
        { row_number: 7, code: '11489', name: 'اذین لوله سه لایه 25', assigned_to: 'اذین لوله 25' },
        { row_number: 8, code: '11490', name: 'اذین لوله سه لایه 32', assigned_to: null },
      ],
    })
    renderMatching()
    await screen.findByText('محصول ج تأمین')
    const table = screen.getByRole('table')
    const unmatchedRow = within(table)
      .getAllByRole('row')
      .find((r) => within(r).queryByText('محصول ج تأمین'))!
    await user.click(within(unmatchedRow).getByRole('button', { name: /تطابق دستی/ }))
    await user.type(screen.getByRole('searchbox', { name: /جستجوی محصول پایونیرز/ }), 'اذین{enter}')
    const held = await screen.findByRole('button', { name: /11489/ })
    expect(held).toBeDisabled()
    expect(held).toHaveTextContent('قبلاً به «اذین لوله 25» نگاشت شده است')
    expect(screen.getByRole('button', { name: /11490/ })).toBeEnabled()
    expect(api.searchProducts).toHaveBeenCalledWith('sess-1', 'اذین', 25, 'c3')
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
    expect(
      await screen.findByText(/نگاشت ذخیره شد/),
    ).toBeInTheDocument()
  })

  it('asks before deleting and moves a matched product to the deleted tab', async () => {
    const user = userEvent.setup()
    const afterDelete = structuredClone(candidatesResponseFixture)
    afterDelete.candidates = afterDelete.candidates.map((candidate) =>
      candidate.candidate_id === 'c1'
        ? {
            ...candidate,
            status: 'IGNORED',
            review_decision: 'EXCLUDE',
            exportable: false,
          }
        : candidate,
    )
    afterDelete.matched_count = 1
    afterDelete.ignored_count = 1
    let ignored = false
    vi.mocked(api.listCandidates).mockImplementation(async () =>
      structuredClone(ignored ? afterDelete : candidatesResponseFixture),
    )
    vi.mocked(api.ignoreCandidate).mockImplementation(async () => {
      ignored = true
      return afterDelete.candidates[0]
    })

    renderMatching()
    await screen.findByText('محصول الف تأمین')
    const table = screen.getByRole('table')
    const matchedRow = within(table)
      .getAllByRole('row')
      .find((row) => within(row).queryByText('محصول الف تأمین'))!
    expect(within(matchedRow).getByRole('button', { name: 'اصلاح' })).toBeInTheDocument()
    await user.click(within(matchedRow).getByRole('button', { name: 'حذف' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/قابل بازگردانی/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'حذف' }))

    expect(
      await screen.findByText(/فقط در تب حذف‌شده/),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(api.ignoreCandidate).toHaveBeenCalledWith('sess-1', 'c1')
    })
    await user.click(screen.getByRole('tab', { name: /حذف‌شده/ }))
    expect(within(screen.getByRole('table')).getByText('محصول الف تأمین')).toBeInTheDocument()
    expect(
      within(screen.getByRole('table')).getByRole('button', { name: 'بازگردانی' }),
    ).toBeInTheDocument()
  })

  it('does not show a successful delete when the request fails', async () => {
    const user = userEvent.setup()
    vi.mocked(api.ignoreCandidate).mockRejectedValue(
      new ApiError(500, 'database is locked'),
    )
    renderMatching()
    await screen.findByText('محصول ج تأمین')
    const table = screen.getByRole('table')
    const unmatchedRow = within(table)
      .getAllByRole('row')
      .find((row) => within(row).queryByText('محصول ج تأمین'))!
    expect(
      within(unmatchedRow).getByRole('button', { name: 'حذف' }),
    ).toBeInTheDocument()
    await user.click(within(unmatchedRow).getByRole('button', { name: 'حذف' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'حذف' }))
    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    expect(screen.queryByText(/محصول حذف شد/)).not.toBeInTheDocument()
    expect(screen.getByText('محصول ج تأمین')).toBeInTheDocument()
  })

  it('restores a deleted product through the API', async () => {
    const user = userEvent.setup()
    const ignored = structuredClone(candidatesResponseFixture)
    ignored.candidates = [
      ...ignored.candidates,
      {
        ...ignored.candidates[2],
        candidate_id: 'c-ignored',
        supplier_name: 'محصول حذف‌شده',
        status: 'IGNORED',
        review_decision: 'EXCLUDE',
        exportable: false,
      },
    ]
    const restored = structuredClone(ignored)
    restored.candidates = restored.candidates.map((candidate) =>
      candidate.candidate_id === 'c-ignored'
        ? { ...candidate, status: 'UNMATCHED' }
        : candidate,
    )
    let didRestore = false
    vi.mocked(api.listCandidates).mockImplementation(async () =>
      structuredClone(didRestore ? restored : ignored),
    )
    vi.mocked(api.restoreCandidate).mockImplementation(async () => {
      didRestore = true
      return restored.candidates.find((row) => row.candidate_id === 'c-ignored')!
    })

    renderMatching()
    await screen.findByText('محصول الف تأمین')
    await user.click(screen.getByRole('tab', { name: /حذف‌شده/ }))
    await user.click(screen.getByRole('button', { name: 'بازگردانی' }))
    expect(await screen.findByText(/بازگردانی شد/)).toBeInTheDocument()
    await waitFor(() => {
      expect(api.restoreCandidate).toHaveBeenCalledWith('sess-1', 'c-ignored')
    })
  })
})
