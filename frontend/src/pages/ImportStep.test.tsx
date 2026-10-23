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
    detectSupplierPdf: vi.fn(),
    confirmSupplierPdf: vi.fn(),
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

function emptySummary(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'sess-1',
    supplier_key: null,
    supplier_display_name: null,
    supplier_confirmed: false,
    detection: null,
    pioneers_filename: null,
    pdf_filename: null,
    product_count: 0,
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
    ...overrides,
  }
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

  it('loads suppliers into the select after PDF detection', async () => {
    vi.mocked(api.detectSupplierPdf).mockResolvedValue({
      session_id: 'sess-1',
      pdf_filename: 'list.pdf',
      supplier_confirmed: false,
      detection: {
        detected_supplier_id: 'azin_pipe',
        detected_supplier_name: 'آذین لوله',
        confidence: 'HIGH',
        evidence: ['آذین'],
        requires_confirmation: true,
      },
      summary: emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        pdf_filename: 'list.pdf',
        detection: {
          detected_supplier_id: 'azin_pipe',
          detected_supplier_name: 'آذین لوله',
          confidence: 'HIGH',
          evidence: ['آذین'],
          requires_confirmation: true,
        },
      }),
    })
    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    expect(
      await screen.findByRole('option', { name: 'آذین لوله' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/پیشنهاد سامانه/)).toBeInTheDocument()
  })

  it('rejects xlsm excel files client-side', async () => {
    renderImport()
    await screen.findByLabelText(/اکسل پایونیرز/)
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

  it('detects supplier on pdf upload without requiring prior selection', async () => {
    vi.mocked(api.detectSupplierPdf).mockResolvedValue({
      session_id: 'sess-1',
      pdf_filename: 'list.pdf',
      supplier_confirmed: false,
      detection: {
        detected_supplier_id: 'azin_pipe',
        detected_supplier_name: 'آذین لوله',
        confidence: 'HIGH',
        evidence: ['آذین'],
        requires_confirmation: true,
      },
      summary: emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        pdf_filename: 'list.pdf',
      }),
    })
    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    await waitFor(() => {
      expect(api.detectSupplierPdf).toHaveBeenCalled()
    })
    expect(api.uploadSupplierPdf).not.toHaveBeenCalled()
    expect(api.confirmSupplierPdf).not.toHaveBeenCalled()
    expect(
      await screen.findByRole('button', { name: 'تأیید شرکت' }),
    ).toBeInTheDocument()
  })

  it('does not continue until supplier is confirmed', async () => {
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
      }),
    )
    vi.mocked(api.detectSupplierPdf).mockResolvedValue({
      session_id: 'sess-1',
      pdf_filename: 'list.pdf',
      supplier_confirmed: false,
      detection: {
        detected_supplier_id: 'azin_pipe',
        detected_supplier_name: 'آذین لوله',
        confidence: 'HIGH',
        evidence: ['آذین'],
        requires_confirmation: true,
      },
      summary: emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        pdf_filename: 'list.pdf',
        supplier_item_count: 0,
        supplier_confirmed: false,
      }),
    })
    renderImport()
    const inputs = document.querySelectorAll('input[type="file"]')
    setFileInput(
      inputs[0] as HTMLInputElement,
      new File(['x'], 'ok.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await screen.findByText(/42/)
    setFileInput(
      inputs[1] as HTMLInputElement,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    await screen.findByRole('button', { name: 'تأیید شرکت' })
    expect(
      screen.getByRole('button', { name: 'شروع تطابق و ادامه' }),
    ).toBeDisabled()
  })

  it('confirms detected supplier then enables matching', async () => {
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
      }),
    )
    vi.mocked(api.detectSupplierPdf).mockResolvedValue({
      session_id: 'sess-1',
      pdf_filename: 'list.pdf',
      supplier_confirmed: false,
      detection: {
        detected_supplier_id: 'azin_pipe',
        detected_supplier_name: 'آذین لوله',
        confidence: 'HIGH',
        evidence: ['آذین'],
        requires_confirmation: true,
      },
      summary: emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        pdf_filename: 'list.pdf',
      }),
    })
    vi.mocked(api.confirmSupplierPdf).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        supplier_confirmed: true,
        pdf_filename: 'list.pdf',
        supplier_item_count: 50,
      }),
    )
    renderImport()
    const inputs = document.querySelectorAll('input[type="file"]')
    setFileInput(
      inputs[0] as HTMLInputElement,
      new File(['x'], 'ok.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await screen.findByText(/42/)
    setFileInput(
      inputs[1] as HTMLInputElement,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    const confirmBtn = await screen.findByRole('button', { name: 'تأیید شرکت' })
    fireEvent.click(confirmBtn)
    await waitFor(() => {
      expect(api.confirmSupplierPdf).toHaveBeenCalledWith('sess-1', 'azin_pipe')
    })
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'شروع تطابق و ادامه' }),
      ).not.toBeDisabled()
    })
  })

  it('allows manual override via تغییر شرکت', async () => {
    vi.mocked(api.listSuppliers).mockResolvedValue([
      { key: 'azin_pipe', display_name: 'آذین لوله' },
      { key: 'newpipe', display_name: 'نیوپایپ' },
    ])
    vi.mocked(api.detectSupplierPdf).mockResolvedValue({
      session_id: 'sess-1',
      pdf_filename: 'list.pdf',
      supplier_confirmed: false,
      detection: {
        detected_supplier_id: 'azin_pipe',
        detected_supplier_name: 'آذین لوله',
        confidence: 'HIGH',
        evidence: ['آذین'],
        requires_confirmation: true,
      },
      summary: emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        pdf_filename: 'list.pdf',
      }),
    })
    vi.mocked(api.confirmSupplierPdf).mockResolvedValue(
      emptySummary({
        supplier_key: 'newpipe',
        supplier_display_name: 'نیوپایپ',
        supplier_confirmed: true,
        pdf_filename: 'list.pdf',
        supplier_item_count: 10,
      }),
    )
    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }),
    )
    expect(await screen.findByText(/پیشنهاد سامانه/)).toBeInTheDocument()
    await screen.findByRole('button', { name: 'تغییر شرکت' })
    fireEvent.click(screen.getByRole('button', { name: 'تغییر شرکت' }))
    const select = screen.getByLabelText('تأمین‌کننده') as HTMLSelectElement
    expect(select.disabled).toBe(false)
    fireEvent.change(select, { target: { value: 'newpipe' } })
    expect(
      screen.getByText(/آیا این لیست قیمت متعلق به شرکت/),
    ).toBeInTheDocument()
    // Question uses the currently selected supplier, not the original suggestion.
    const question = screen.getByText(/آیا این لیست قیمت متعلق به شرکت/)
    expect(question.textContent).toContain('نیوپایپ')
    expect(question.textContent).not.toMatch(/آذین لوله\s*است/)
    expect(screen.getByText(/پیشنهاد سامانه/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'تأیید شرکت' }))
    await waitFor(() => {
      expect(api.confirmSupplierPdf).toHaveBeenCalledWith('sess-1', 'newpipe')
    })
  })

  it('shows confirmation controls for manual recovery after detection error', async () => {
    vi.mocked(api.listSuppliers).mockResolvedValue(suppliersFixture)
    vi.mocked(api.detectSupplierPdf).mockRejectedValue(
      new ApiError(400, 'detection failed'),
    )
    vi.mocked(api.uploadSupplierPdf).mockResolvedValue(
      emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        supplier_confirmed: true,
        pdf_filename: 'list.pdf',
        supplier_item_count: 12,
      }),
    )
    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    const file = new File(['%PDF'], 'list.pdf', { type: 'application/pdf' })
    setFileInput(pdfInput, file)
    const select = await screen.findByLabelText('تأمین‌کننده')
    expect(select).not.toBeDisabled()
    expect(
      await screen.findByRole('button', { name: 'تأیید شرکت' }),
    ).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'azin_pipe' } })
    fireEvent.click(screen.getByRole('button', { name: 'تأیید شرکت' }))
    await waitFor(() => {
      expect(api.uploadSupplierPdf).toHaveBeenCalledWith(
        'sess-1',
        'azin_pipe',
        file,
      )
    })
    expect(api.confirmSupplierPdf).not.toHaveBeenCalled()
  })

  async function clickConfirmWhenEnabled() {
    const button = await screen.findByRole('button', { name: 'تأیید شرکت' })
    await waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)
  }

  it('uploads replacement PDF B after failed detection over confirmed PDF A', async () => {
    vi.mocked(api.listSuppliers).mockResolvedValue([
      { key: 'azin_pipe', display_name: 'آذین لوله' },
      { key: 'newpipe', display_name: 'نیوپایپ' },
    ])
    vi.mocked(api.detectSupplierPdf)
      .mockResolvedValueOnce({
        session_id: 'sess-1',
        pdf_filename: 'a.pdf',
        supplier_confirmed: false,
        detection: {
          detected_supplier_id: 'azin_pipe',
          detected_supplier_name: 'آذین لوله',
          confidence: 'HIGH',
          evidence: ['آذین'],
          requires_confirmation: true,
        },
        summary: emptySummary({
          supplier_key: 'azin_pipe',
          supplier_display_name: 'آذین لوله',
          pdf_filename: 'a.pdf',
        }),
      })
      .mockRejectedValueOnce(new ApiError(400, 'detection failed'))
    vi.mocked(api.confirmSupplierPdf).mockResolvedValue(
      emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        supplier_confirmed: true,
        pdf_filename: 'a.pdf',
        supplier_item_count: 20,
      }),
    )
    const fileB = new File(['%PDF-B'], 'b.pdf', { type: 'application/pdf' })
    vi.mocked(api.uploadSupplierPdf).mockResolvedValue(
      emptySummary({
        supplier_key: 'newpipe',
        supplier_display_name: 'نیوپایپ',
        supplier_confirmed: true,
        pdf_filename: 'b.pdf',
        supplier_item_count: 15,
      }),
    )

    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement

    // Confirm PDF A first.
    setFileInput(
      pdfInput,
      new File(['%PDF-A'], 'a.pdf', { type: 'application/pdf' }),
    )
    await clickConfirmWhenEnabled()
    await waitFor(() => {
      expect(api.confirmSupplierPdf).toHaveBeenCalledWith('sess-1', 'azin_pipe')
    })
    await waitFor(() => {
      expect(screen.getAllByText(/a\.pdf/).length).toBeGreaterThan(0)
    })

    // Replacement B fails detection; prior a.pdf remains in summary.
    setFileInput(pdfInput, fileB)
    const select = await screen.findByLabelText('تأمین‌کننده')
    await screen.findByRole('button', { name: 'تأیید شرکت' })
    fireEvent.change(select, { target: { value: 'newpipe' } })
    await clickConfirmWhenEnabled()

    await waitFor(() => {
      expect(api.uploadSupplierPdf).toHaveBeenCalledWith(
        'sess-1',
        'newpipe',
        fileB,
      )
    })
    // Must not re-confirm stale PDF A on the server.
    expect(api.confirmSupplierPdf).toHaveBeenCalledTimes(1)
  })

  it('resets confirmation when a new PDF is selected', async () => {
    vi.mocked(api.detectSupplierPdf)
      .mockResolvedValueOnce({
        session_id: 'sess-1',
        pdf_filename: 'a.pdf',
        supplier_confirmed: false,
        detection: {
          detected_supplier_id: 'azin_pipe',
          detected_supplier_name: 'آذین لوله',
          confidence: 'HIGH',
          evidence: ['آذین'],
          requires_confirmation: true,
        },
        summary: emptySummary({
          supplier_key: 'azin_pipe',
          supplier_display_name: 'آذین لوله',
          pdf_filename: 'a.pdf',
        }),
      })
      .mockResolvedValueOnce({
        session_id: 'sess-1',
        pdf_filename: 'b.pdf',
        supplier_confirmed: false,
        detection: {
          detected_supplier_id: 'newpipe',
          detected_supplier_name: 'نیوپایپ',
          confidence: 'HIGH',
          evidence: ['نیوپایپ'],
          requires_confirmation: true,
        },
        summary: emptySummary({
          supplier_key: 'newpipe',
          supplier_display_name: 'نیوپایپ',
          pdf_filename: 'b.pdf',
        }),
      })
    vi.mocked(api.confirmSupplierPdf).mockResolvedValue(
      emptySummary({
        supplier_key: 'azin_pipe',
        supplier_display_name: 'آذین لوله',
        supplier_confirmed: true,
        pdf_filename: 'a.pdf',
        supplier_item_count: 20,
      }),
    )
    vi.mocked(api.listSuppliers).mockResolvedValue([
      { key: 'azin_pipe', display_name: 'آذین لوله' },
      { key: 'newpipe', display_name: 'نیوپایپ' },
    ])
    renderImport()
    const pdfInput = document.querySelectorAll(
      'input[type="file"]',
    )[1] as HTMLInputElement
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'a.pdf', { type: 'application/pdf' }),
    )
    await clickConfirmWhenEnabled()
    await waitFor(() => expect(api.confirmSupplierPdf).toHaveBeenCalled())
    setFileInput(
      pdfInput,
      new File(['%PDF'], 'b.pdf', { type: 'application/pdf' }),
    )
    await waitFor(() => {
      expect(api.detectSupplierPdf).toHaveBeenCalledTimes(2)
    })
    expect(
      screen.getByRole('button', { name: 'تأیید شرکت' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/در انتظار تأیید/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'شروع تطابق و ادامه' }),
    ).toBeDisabled()
  })

  it('uploads excel after validation', async () => {
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'ok.xlsx',
        product_count: 42,
      }),
    )
    renderImport()
    await screen.findByLabelText(/اکسل پایونیرز/)
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
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'گزارش.xls',
        product_count: 12,
      }),
    )
    renderImport()
    await screen.findByLabelText(/اکسل پایونیرز/)
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
      .mockResolvedValueOnce(
        emptySummary({
          pioneers_filename: 'good.xlsx',
          product_count: 10,
        }),
      )
      .mockRejectedValueOnce(
        new ApiError(400, 'expected an .xlsx or .xls Excel upload'),
      )

    renderImport()
    await screen.findByLabelText(/اکسل پایونیرز/)
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
    vi.mocked(api.uploadPioneersExcel).mockResolvedValue(
      emptySummary({
        pioneers_filename: 'a.xlsx',
        product_count: 1,
      }),
    )
    renderImport()
    await screen.findByLabelText(/اکسل پایونیرز/)
    const excelInput = document.querySelectorAll(
      'input[type="file"]',
    )[0] as HTMLInputElement
    setFileInput(
      excelInput,
      new File(['x'], 'a.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await waitFor(() => expect(api.createSession).toHaveBeenCalledTimes(1))
    resolveCreate({ session_id: 'shared' })
    await waitFor(() => expect(api.uploadPioneersExcel).toHaveBeenCalled())
  })
})
