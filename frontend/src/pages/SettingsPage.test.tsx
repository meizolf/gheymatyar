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
  client.setQueryData(['preview', 'open-session'], { candidates: [] })
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
        suspicious_percent_threshold: '30',
      },
    })
  })

  it('loads and saves threshold', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateSettings).mockResolvedValue({
      settings: {
        suspicious_percent_threshold: '25',
      },
    })
    const { client } = renderSettings()
    const input = await screen.findByLabelText(/آستانه هشدار/)
    expect(input).toHaveValue('30')
    expect(screen.queryByLabelText(/ارز نرخ فروش/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/مبنای نرخ فروش/)).not.toBeInTheDocument()
    await user.clear(input)
    await user.type(input, '25')
    await user.click(screen.getByRole('button', { name: 'ذخیره' }))
    await waitFor(() => {
      expect(api.updateSettings).toHaveBeenCalledWith({
        suspicious_percent_threshold: '25',
      })
    })
    expect(await screen.findByText(/تنظیمات ذخیره شد/)).toBeInTheDocument()
    await waitFor(() => {
      expect(client.getQueryState(['preview', 'open-session'])?.isInvalidated).toBe(
        true,
      )
    })
  })
})
