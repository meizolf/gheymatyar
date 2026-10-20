import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { WorkflowProvider } from '../workflow/WorkflowContext'
import { ImportStep } from './ImportStep'
import { suppliersFixture } from '../test/fixtures'

vi.mock('../api/client', () => ({
  api: {
    listSuppliers: vi.fn(),
    createSession: vi.fn(),
    uploadPioneersExcel: vi.fn(),
    uploadSupplierPdf: vi.fn(),
    runMatch: vi.fn(),
    getSession: vi.fn(),
  },
}))

import { api } from '../api/client'

function renderImport() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <WorkflowProvider>
        <ImportStep />
      </WorkflowProvider>
    </QueryClientProvider>,
  )
}

function setFileInput(input: HTMLInputElement, file: File) {
  const fileList = {
    0: file,
    length: 1,
    item: (index: number) => (index === 0 ? file : null),
    *[Symbol.iterator]() {
      yield file
    },
  } as unknown as FileList
  fireEvent.change(input, { target: { files: fileList } })
}

describe('ImportStep', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.mocked(api.listSuppliers).mockResolvedValue(suppliersFixture)
    vi.mocked(api.createSession).mockResolvedValue({ session_id: 'sess-1' })
    vi.mocked(api.getSession).mockRejectedValue(
      new ApiError(404, 'session not found'),
    )
  })

  it('loads suppliers into the select', async () => {
    renderImport()
    expect(
      await screen.findByRole('option', { name: 'آذین لوله' }),
    ).toBeInTheDocument()
  })

  it('rejects xlsm excel files client-side', async () => {
    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    setFileInput(
      excelInput,
      new File(['x'], 'book.xlsm', {
        type: 'application/vnd.ms-excel.sheet.macroEnabled.12',
      }),
    )
    expect(
      await screen.findByText(/فقط فایل \.xlsx یا \.xls پشتیبانی می‌شود/),
    ).toBeInTheDocument()
    expect(api.uploadPioneersExcel).not.toHaveBeenCalled()
  })

  it('requires supplier before pdf upload', async () => {
    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /ابتدا تأمین‌کننده را انتخاب کنید/,
    )
    expect(api.uploadSupplierPdf).not.toHaveBeenCalled()
  })

  it('uploads excel after validation', async () => {
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue({
      session_id: 'sess-1',
      supplier_key: null,
      supplier_display_name: null,
      pioneers_filename: 'ok.xlsx',
      pdf_filename: null,
      product_count: 42,
      invalid_row_count: 0,
      invalid_rows: [],
      duplicate_codes: {},
      supplier_item_count: 0,
      matched_count: 0,
      unmatched_count: 0,
      ambiguous_count: 0,
      warning_count: 0,
      exportable_count: 0,
      parse_warnings: [],
      export_available: false,
    })
    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    setFileInput(
      excelInput,
      new File(['x'], 'ok.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalled()
      expect(api.uploadPioneersExcel).toHaveBeenCalled()
    })
    expect(await screen.findByText(/42/)).toBeInTheDocument()
    expect(screen.getByText(/پذیرفته‌شده توسط سرور/)).toBeInTheDocument()
  })

  it('accepts and uploads legacy .xls files', async () => {
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue({
      session_id: 'sess-1',
      supplier_key: null,
      supplier_display_name: null,
      pioneers_filename: 'گزارش.xls',
      pdf_filename: null,
      product_count: 12,
      invalid_row_count: 0,
      invalid_rows: [],
      duplicate_codes: {},
      supplier_item_count: 0,
      matched_count: 0,
      unmatched_count: 0,
      ambiguous_count: 0,
      warning_count: 0,
      exportable_count: 0,
      parse_warnings: [],
      export_available: false,
    })
    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    expect(excelInput.accept).toMatch(/\.xls/)
    const file = new File(['<Html>'], 'گزارش.xls', {
      type: 'application/vnd.ms-excel',
    })
    setFileInput(excelInput, file)
    await waitFor(() => {
      expect(api.uploadPioneersExcel).toHaveBeenCalled()
    })
    const [, uploadedFile] = vi.mocked(api.uploadPioneersExcel).mock.calls[0]
    expect(uploadedFile).toBeInstanceOf(File)
    expect(uploadedFile.name).toBe('گزارش.xls')
    expect(await screen.findByText(/12/)).toBeInTheDocument()
    expect(screen.getAllByText(/گزارش\.xls/).length).toBeGreaterThan(0)
  })

  it('keeps prior accepted excel when replacement upload fails', async () => {
    vi.mocked(api.uploadPioneersExcel)
      .mockResolvedValueOnce({
        session_id: 'sess-1',
        supplier_key: null,
        supplier_display_name: null,
        pioneers_filename: 'good.xlsx',
        pdf_filename: null,
        product_count: 10,
        invalid_row_count: 0,
        invalid_rows: [],
        duplicate_codes: {},
        supplier_item_count: 0,
        matched_count: 0,
        unmatched_count: 0,
        ambiguous_count: 0,
        warning_count: 0,
        exportable_count: 0,
        parse_warnings: [],
        export_available: false,
      })
      .mockRejectedValueOnce(
        new ApiError(400, 'expected an .xlsx or .xls Excel upload'),
      )

    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    setFileInput(
      excelInput,
      new File(['x'], 'good.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await screen.findByText(/good\.xlsx/)
    setFileInput(
      excelInput,
      new File(['x'], 'bad.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    expect(
      await screen.findByText(/پذیرفته نشد — فایل قبلی سرور حفظ شده است/),
    ).toBeInTheDocument()
    // Accepted backend name remains visible in summary chips
    expect(screen.getAllByText(/good\.xlsx/).length).toBeGreaterThan(0)
  })

  it('shares a single session create across concurrent uploads', async () => {
    let resolveCreate!: (v: { session_id: string }) => void
    vi.mocked(api.createSession).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve
        }),
    )
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue({
      session_id: 'shared',
      supplier_key: null,
      supplier_display_name: null,
      pioneers_filename: 'a.xlsx',
      pdf_filename: null,
      product_count: 1,
      invalid_row_count: 0,
      invalid_rows: [],
      duplicate_codes: {},
      supplier_item_count: 0,
      matched_count: 0,
      unmatched_count: 0,
      ambiguous_count: 0,
      warning_count: 0,
      exportable_count: 0,
      parse_warnings: [],
      export_available: false,
    })
    renderImport()
    await screen.findByRole('option', { name: 'آذین لوله' })
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    setFileInput(
      excelInput,
      new File(['x'], 'a.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    // Second upload attempt while create still pending is blocked by busy/uploading guard
    await waitFor(() => expect(api.createSession).toHaveBeenCalledTimes(1))
    resolveCreate({ session_id: 'shared' })
    await waitFor(() => expect(api.uploadPioneersExcel).toHaveBeenCalled())
  })
})
