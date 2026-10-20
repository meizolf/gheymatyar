import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { summaryFixture } from '../test/fixtures'
import { WorkflowProvider, useWorkflow } from './WorkflowContext'

vi.mock('../api/client', () => ({
  api: {
    getSession: vi.fn(),
    createSession: vi.fn(),
  },
}))

import { api } from '../api/client'

function Probe() {
  const { restoring, summary, matchedDone, restoreError, step } = useWorkflow()
  if (restoring) return <div>restoring</div>
  if (restoreError) return <div>{restoreError}</div>
  return (
    <div>
      <span data-testid="step">{step}</span>
      <span data-testid="matched">{matchedDone ? 'yes' : 'no'}</span>
      <span data-testid="file">{summary?.pioneers_filename ?? 'none'}</span>
    </div>
  )
}

describe('WorkflowProvider restore', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('restores summary and progress from stored session id', async () => {
    sessionStorage.setItem('gheymatyar.sessionId', 'sess-1')
    sessionStorage.setItem('gheymatyar.wizardStep', '3')
    vi.mocked(api.getSession).mockResolvedValue({
      ...summaryFixture,
      matched_count: 5,
      unmatched_count: 1,
      ambiguous_count: 0,
    })
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <WorkflowProvider>
          <Probe />
        </WorkflowProvider>
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('file')).toHaveTextContent('pioneers.xlsx')
    })
    expect(screen.getByTestId('matched')).toHaveTextContent('yes')
    expect(screen.getByTestId('step')).toHaveTextContent('3')
  })

  it('completes restoration under StrictMode remount/cancel', async () => {
    sessionStorage.setItem('gheymatyar.sessionId', 'sess-strict')
    sessionStorage.setItem('gheymatyar.wizardStep', '2')
    let resolveGet!: (value: typeof summaryFixture) => void
    vi.mocked(api.getSession).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve
        }),
    )
    const client = new QueryClient()
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <WorkflowProvider>
            <Probe />
          </WorkflowProvider>
        </QueryClientProvider>
      </StrictMode>,
    )
    expect(await screen.findByText('restoring')).toBeInTheDocument()
    // StrictMode may have cancelled the first call; resolve the latest one.
    await waitFor(() => {
      expect(api.getSession).toHaveBeenCalled()
    })
    resolveGet({
      ...summaryFixture,
      session_id: 'sess-strict',
      matched_count: 2,
      unmatched_count: 0,
      ambiguous_count: 0,
    })
    await waitFor(() => {
      expect(screen.getByTestId('file')).toHaveTextContent('pioneers.xlsx')
    })
    expect(screen.queryByText('restoring')).not.toBeInTheDocument()
    expect(screen.getByTestId('matched')).toHaveTextContent('yes')
  })

  it('explains expiration when stored session is gone', async () => {
    sessionStorage.setItem('gheymatyar.sessionId', 'gone')
    vi.mocked(api.getSession).mockRejectedValue(
      new ApiError(404, 'session not found'),
    )
    const client = new QueryClient()
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <WorkflowProvider>
            <Probe />
          </WorkflowProvider>
        </QueryClientProvider>
      </StrictMode>,
    )
    expect(await screen.findByText(/منقضی/)).toBeInTheDocument()
  })
})
