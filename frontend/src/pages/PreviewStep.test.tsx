import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { candidatesResponseFixture, summaryFixture } from '../test/fixtures'
import { WorkflowProvider, useWorkflow } from '../workflow/WorkflowContext'
import { PreviewStep } from './PreviewStep'

vi.mock('../api/client', () => ({
  api: {
    preview: vi.fn(),
    getSession: vi.fn(),
    setReview: vi.fn(),
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

function renderPreview() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <WorkflowProvider>
        <Seed>
          <PreviewStep />
        </Seed>
      </WorkflowProvider>
    </QueryClientProvider>,
  )
}

describe('PreviewStep', () => {
  beforeEach(() => {
    sessionStorage.clear()
    const matched = {
      ...candidatesResponseFixture,
      candidates: candidatesResponseFixture.candidates.filter(
        (c) => c.status === 'MATCHED',
      ),
    }
    vi.mocked(api.preview).mockResolvedValue(structuredClone(matched))
    vi.mocked(api.getSession).mockResolvedValue({ ...summaryFixture })
  })

  it('shows old new prices and warnings', async () => {
    renderPreview()
    expect(await screen.findByText('محصول الف')).toBeInTheDocument()
    expect(screen.getByText(/تغییر قیمت|price change/)).toBeInTheDocument()
    expect(screen.getByText('نیاز به تأیید هشدار')).toBeInTheDocument()
  })

  it('labels warning approval explicitly for excluded warned rows', async () => {
    const matched = {
      ...candidatesResponseFixture,
      candidates: [
        {
          ...candidatesResponseFixture.candidates[1],
          review_decision: 'EXCLUDE',
          exportable: false,
        },
      ],
    }
    vi.mocked(api.preview).mockResolvedValue(matched as never)
    renderPreview()
    expect(
      await screen.findByRole('button', { name: 'تأیید هشدار و شامل کردن' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'شامل کردن' })).not.toBeInTheDocument()
  })

  it('distinguishes detected price diffs from exportable updates', async () => {
    renderPreview()
    await screen.findByText('محصول الف')
    expect(screen.getByText(/اختلاف قیمت/)).toBeInTheDocument()
    expect(screen.getByText(/به‌روزرسانی خروجی/)).toBeInTheDocument()
  })

  it('approves warned updates', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setReview).mockResolvedValue({
      ...candidatesResponseFixture.candidates[1],
      review_decision: 'APPROVE',
      exportable: true,
    })
    renderPreview()
    await screen.findByText('محصول ب')
    await user.click(screen.getByRole('button', { name: 'تأیید هشدار' }))
    await waitFor(() => {
      expect(api.setReview).toHaveBeenCalledWith('sess-1', 'c2', 'APPROVE')
    })
  })

  it('blocks continue to export while exclusion is pending', async () => {
    const user = userEvent.setup()
    let resolveExclude!: (v: unknown) => void
    vi.mocked(api.setReview).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveExclude = resolve
        }) as never,
    )
    renderPreview()
    const row = (await screen.findAllByRole('row')).find((r) =>
      within(r).queryByText('محصول الف'),
    )!
    await user.click(within(row).getByRole('button', { name: 'حذف از خروجی' }))
    const continueBtn = await screen.findByRole('button', {
      name: /در انتظار ثبت تصمیم/,
    })
    expect(continueBtn).toBeDisabled()
    resolveExclude({
      ...candidatesResponseFixture.candidates[0],
      review_decision: 'EXCLUDE',
      exportable: false,
    })
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /ادامه به خروجی/ }),
      ).toBeInTheDocument()
    })
  })

  it('excludes an update', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setReview).mockResolvedValue({
      ...candidatesResponseFixture.candidates[0],
      review_decision: 'EXCLUDE',
      exportable: false,
    })
    renderPreview()
    const row = (await screen.findAllByRole('row')).find((r) =>
      within(r).queryByText('محصول الف'),
    )!
    await user.click(within(row).getByRole('button', { name: 'حذف از خروجی' }))
    await waitFor(() => {
      expect(api.setReview).toHaveBeenCalledWith('sess-1', 'c1', 'EXCLUDE')
    })
  })
})
