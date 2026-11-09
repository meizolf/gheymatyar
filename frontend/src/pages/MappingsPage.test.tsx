import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { MappingImportResponse } from '../api/types'
import { MappingsPage } from './MappingsPage'

vi.mock('../api/client', () => ({
  api: {
    listSuppliers: vi.fn().mockResolvedValue([{ key: 'texa', display_name: 'صنایع شیرسازی تکسا' }]),
    listMappings: vi.fn(),
    exportMappings: vi.fn(),
    previewMappingImport: vi.fn(),
    confirmMappingImport: vi.fn(),
  },
}))

import { api } from '../api/client'

const conflict = {
  supplier_key: 'texa',
  pioneers_code: '5001',
  existing_pioneers_code: '4001',
  existing_pioneers_name: 'شیر قدیمی',
  holder: null,
}
const plan: MappingImportResponse = {
  applied: false,
  total: 5,
  counts: { new: 2, identical: 1, conflict: 2, invalid: 0, replace: 0 },
  items: [
    { ...conflict, index: 1, status: 'conflict', supplier_name: 'تکسا شیر شوفاژ', pioneers_name: 'شیر شوفاژ',
      reason: 'mapped_elsewhere', replaceable: true },
    { ...conflict, index: 3, status: 'conflict', supplier_name: 'تکسا زانو', pioneers_name: 'زانو',
      reason: 'target_taken', holder: 'تکسا زانو شوفاژ', replaceable: false },
  ],
}

describe('MappingsPage import', () => {
  it('previews counts and replaces only the conflicts the user ticks', async () => {
    const user = userEvent.setup()
    vi.mocked(api.previewMappingImport).mockResolvedValue(plan)
    vi.mocked(api.confirmMappingImport).mockResolvedValue({
      ...plan, applied: true, counts: { ...plan.counts, conflict: 1, replace: 1 },
    })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MappingsPage />
      </QueryClientProvider>,
    )
    const file = new File(['{}'], 'gheymatyar-mappings-2026-11-09.json', { type: 'application/json' })
    await user.upload(screen.getByLabelText('فایل نگاشت‌ها'), file)

    expect(await screen.findByText(/نگاشت جدید:/)).toHaveTextContent('2')
    expect(screen.getByText(/نگاشت متعارض:/)).toHaveTextContent('2')
    expect(screen.getByText(/در اختیار «تکسا زانو شوفاژ» است/)).toBeInTheDocument()
    // Only the replaceable conflict offers a choice.
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes).toHaveLength(1)
    await user.click(boxes[0])
    await user.click(screen.getByRole('button', { name: 'تأیید ورود' }))
    await waitFor(() => {
      expect(api.confirmMappingImport).toHaveBeenCalledWith(file, [1])
    })
    expect(await screen.findByText(/ورود انجام شد: 2 نگاشت جدید و 1 جایگزینی/)).toBeInTheDocument()
  })
})
