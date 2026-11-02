import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
  },
}))

import { api } from '../api/client'

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  for (const key of ['preview', 'session', 'candidates']) {
    client.setQueryData([key, 'open-session'], { candidates: [] })
  }
  const view = render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
  return { client, ...view }
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.mocked(api.getSettings).mockResolvedValue({
      settings: {
        price_increase_warning_percent: '30',
        price_decrease_warning_percent: '10',
      },
    })
  })

  it('saves both thresholds and refetches the open price review', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateSettings).mockResolvedValue({
      settings: {
        price_increase_warning_percent: '25',
        price_decrease_warning_percent: '5',
      },
    })
    const { client } = renderSettings()
    const increase = await screen.findByLabelText(/آستانه هشدار افزایش/)
    const decrease = screen.getByLabelText(/آستانه هشدار کاهش/)
    expect(increase).toHaveValue('30')
    expect(decrease).toHaveValue('10')
    expect(screen.queryByLabelText(/ارز نرخ فروش/)).not.toBeInTheDocument()
    await user.clear(increase)
    await user.type(increase, '25')
    await user.clear(decrease)
    await user.type(decrease, '5')
    await user.click(screen.getByRole('button', { name: 'ذخیره' }))
    await waitFor(() => {
      expect(api.updateSettings).toHaveBeenCalledWith({
        price_increase_warning_percent: '25',
        price_decrease_warning_percent: '5',
      })
    })
    expect(await screen.findByText(/تنظیمات ذخیره شد/)).toBeInTheDocument()
    await waitFor(() => {
      for (const key of ['preview', 'session', 'candidates']) {
        expect(client.getQueryState([key, 'open-session'])?.isInvalidated).toBe(true)
      }
    })
  })

  it('keeps the price review as it was when the save fails', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateSettings).mockRejectedValue(new Error('offline'))
    const { client } = renderSettings()
    await user.click(await screen.findByRole('button', { name: 'ذخیره' }))
    expect(await screen.findByText('خطا در ذخیره')).toBeInTheDocument()
    expect(screen.queryByText(/تنظیمات ذخیره شد/)).not.toBeInTheDocument()
    expect(client.getQueryState(['preview', 'open-session'])?.isInvalidated).toBe(false)
  })
})
