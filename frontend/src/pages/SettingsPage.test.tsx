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
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.mocked(api.getSettings).mockResolvedValue({
      settings: { suspicious_percent_threshold: '30' },
    })
  })

  it('loads and saves threshold', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateSettings).mockResolvedValue({
      settings: { suspicious_percent_threshold: '25' },
    })
    renderSettings()
    const input = await screen.findByLabelText(/آستانه هشدار/)
    expect(input).toHaveValue('30')
    await user.clear(input)
    await user.type(input, '25')
    await user.click(screen.getByRole('button', { name: 'ذخیره' }))
    await waitFor(() => {
      expect(api.updateSettings).toHaveBeenCalledWith({
        suspicious_percent_threshold: '25',
      })
    })
    expect(await screen.findByText(/تنظیمات ذخیره شد/)).toBeInTheDocument()
  })
})
