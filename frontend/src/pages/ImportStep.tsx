import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { FileDropzone } from '../components/FileDropzone'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { translateApiDetail } from '../utils/apiMessages'
import { isExcelFile, isPdfFile } from '../utils/format'
import { invalidateSessionData } from '../workflow/queryKeys'
import { enqueueSessionOp } from '../workflow/sessionQueue'
import { useWorkflow } from '../workflow/WorkflowContext'

export function ImportStep() {
  const {
    sessionId,
    summary,
    setSummary,
    setStep,
    setMatchedDone,
    ensureSession,
    invalidateDownstream,
    reset,
    restoreError,
    clearRestoreError,
    exportInFlight,
    pendingSessionOps,
  } = useWorkflow()
  const queryClient = useQueryClient()

  const [pendingExcel, setPendingExcel] = useState<File | null>(null)
  const [pendingPdf, setPendingPdf] = useState<File | null>(null)
  const [supplierKey, setSupplierKey] = useState(
    () => summary?.supplier_key ?? '',
  )
  const [excelError, setExcelError] = useState<string | null>(null)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const suppliersQuery = useQuery({
    queryKey: ['suppliers'],
    queryFn: api.listSuppliers,
  })

  const busy =
    exportInFlight ||
    pendingSessionOps > 0

  const uploadExcel = useMutation({
    mutationFn: async (file: File) => {
      const sid = await ensureSession()
      return enqueueSessionOp(() => api.uploadPioneersExcel(sid, file))
    },
    onSuccess: async (data) => {
      setSummary(data)
      setPendingExcel(null)
      setExcelError(null)
      setFormError(null)
      clearRestoreError()
      invalidateDownstream()
      await invalidateSessionData(
        queryClient,
        data.session_id,
        data.supplier_key,
      )
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setFormError(translateApiDetail(err.detail))
        return
      }
      // Keep previous accepted filename from summary; clear optimistic pending name on hard fail display
      setExcelError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در بارگذاری اکسل',
        ),
      )
    },
  })

  const uploadPdf = useMutation({
    mutationFn: async ({
      file,
      key,
    }: {
      file: File
      key: string
    }) => {
      const sid = await ensureSession()
      return enqueueSessionOp(() => api.uploadSupplierPdf(sid, key, file))
    },
    onSuccess: async (data) => {
      setSummary(data)
      setPendingPdf(null)
      setPdfError(null)
      setFormError(null)
      clearRestoreError()
      invalidateDownstream()
      await invalidateSessionData(
        queryClient,
        data.session_id,
        data.supplier_key,
      )
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setFormError(translateApiDetail(err.detail))
        return
      }
      setPdfError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در بارگذاری PDF',
        ),
      )
    },
  })

  const matchMutation = useMutation({
    mutationFn: async () => {
      const sid = sessionId
      if (!sid) throw new Error('session missing')
      return enqueueSessionOp(() => api.runMatch(sid))
    },
    onSuccess: async (data) => {
      setMatchedDone(true)
      if (summary) {
        setSummary({
          ...summary,
          matched_count: data.matched_count,
          unmatched_count: data.unmatched_count,
          ambiguous_count: data.ambiguous_count,
        })
      }
      await invalidateSessionData(
        queryClient,
        data.session_id,
        summary?.supplier_key,
      )
      // Seed candidates cache so MatchingStep does not flash empty
      queryClient.setQueryData(['candidates', data.session_id], data)
      setStep(2)
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setFormError(translateApiDetail(err.detail))
        return
      }
      setFormError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در پردازش تطابق',
        ),
      )
    },
  })

  function onExcelSelect(file: File) {
    if (!isExcelFile(file)) {
      setExcelError('فقط فایل .xlsx پشتیبانی می‌شود (.xlsm مجاز نیست)')
      return
    }
    if (uploadExcel.isPending || uploadPdf.isPending || matchMutation.isPending || busy) {
      setExcelError('لطفاً تا پایان عملیات جاری صبر کنید')
      return
    }
    setPendingExcel(file)
    setExcelError(null)
    uploadExcel.mutate(file)
  }

  function onPdfSelect(file: File) {
    if (!isPdfFile(file)) {
      setPdfError('فقط فایل PDF پشتیبانی می‌شود')
      return
    }
    if (!supplierKey) {
      setPdfError('ابتدا تأمین‌کننده را انتخاب کنید')
      return
    }
    if (uploadExcel.isPending || uploadPdf.isPending || matchMutation.isPending || busy) {
      setPdfError('لطفاً تا پایان عملیات جاری صبر کنید')
      return
    }
    setPendingPdf(file)
    setPdfError(null)
    uploadPdf.mutate({ file, key: supplierKey })
  }

  const excelReady = Boolean(summary?.pioneers_filename && summary.product_count > 0)
  const pdfReady = Boolean(summary?.pdf_filename && summary.supplier_item_count > 0)
  const uploading = uploadExcel.isPending || uploadPdf.isPending
  const canContinue =
    excelReady &&
    pdfReady &&
    !uploading &&
    !matchMutation.isPending &&
    !busy &&
    !excelError &&
    !pdfError

  return (
    <section className="panel">
      <h1>بارگذاری فایل‌ها</h1>
      <p className="lede">
        فایل اکسل پایونیرز و لیست قیمت PDF تأمین‌کننده را انتخاب کنید. پردازش روی
        سرور محلی انجام می‌شود.
      </p>

      {restoreError ? (
        <Alert tone="warning">
          {restoreError}
          <div className="step-actions">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                clearRestoreError()
                reset()
                setPendingExcel(null)
                setPendingPdf(null)
                setSupplierKey('')
              }}
            >
              شروع بارگذاری جدید
            </Button>
          </div>
        </Alert>
      ) : null}

      {formError ? <Alert tone="error">{formError}</Alert> : null}

      <div className="form-grid">
        <FileDropzone
          label="اکسل پایونیرز (.xlsx)"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          pendingFile={pendingExcel}
          acceptedFilename={summary?.pioneers_filename}
          uploading={uploadExcel.isPending}
          error={excelError}
          disabled={uploading || matchMutation.isPending || busy}
          onSelect={onExcelSelect}
          hint="فقط نرخ فروش اصلی در خروجی تغییر می‌کند؛ فایل اصلی دست‌نخورده می‌ماند."
        />

        <div className="field">
          <label htmlFor="supplier">تأمین‌کننده</label>
          {suppliersQuery.isLoading ? (
            <Spinner label="در حال دریافت فهرست تأمین‌کنندگان…" />
          ) : suppliersQuery.isError ? (
            <Alert tone="error">
              خطا در دریافت تأمین‌کنندگان:{' '}
              {translateApiDetail(
                isApiError(suppliersQuery.error)
                  ? suppliersQuery.error.detail
                  : undefined,
              )}
            </Alert>
          ) : (
            <select
              id="supplier"
              value={supplierKey}
              disabled={uploading || busy}
              onChange={(e) => {
                setSupplierKey(e.target.value)
                setPendingPdf(null)
                setPdfError(null)
              }}
            >
              <option value="">انتخاب کنید…</option>
              {(suppliersQuery.data ?? []).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.display_name}
                </option>
              ))}
            </select>
          )}
          <p className="field-hint">
            فقط تأمین‌کنندگانی که سرور پشتیبانی می‌کند نمایش داده می‌شوند.
          </p>
        </div>

        <FileDropzone
          label="لیست قیمت PDF تأمین‌کننده"
          accept=".pdf,application/pdf"
          pendingFile={pendingPdf}
          acceptedFilename={summary?.pdf_filename}
          uploading={uploadPdf.isPending}
          error={pdfError}
          disabled={uploading || matchMutation.isPending || busy}
          onSelect={onPdfSelect}
          hint={
            supplierKey
              ? 'فرمت PDF مخصوص همین تأمین‌کننده است.'
              : 'ابتدا تأمین‌کننده را انتخاب کنید، سپس PDF را بارگذاری کنید.'
          }
        />
      </div>

      {uploading ? <Spinner label="در حال ارسال و پردازش فایل…" /> : null}

      {summary && (excelReady || pdfReady) ? (
        <div className="summary-box">
          <h2>نتیجه بارگذاری</h2>
          <div className="chip-row">
            {summary.pioneers_filename ? (
              <span className="chip">
                اکسل: <strong className="ltr">{summary.pioneers_filename}</strong>
              </span>
            ) : null}
            {summary.product_count > 0 ? (
              <span className="chip">
                محصولات پایونیرز: <strong>{summary.product_count}</strong>
              </span>
            ) : null}
            {summary.supplier_display_name ? (
              <span className="chip">
                تأمین‌کننده: <strong>{summary.supplier_display_name}</strong>
              </span>
            ) : null}
            {summary.pdf_filename ? (
              <span className="chip">
                PDF: <strong className="ltr">{summary.pdf_filename}</strong>
              </span>
            ) : null}
            {summary.supplier_item_count > 0 ? (
              <span className="chip">
                اقلام PDF: <strong>{summary.supplier_item_count}</strong>
              </span>
            ) : null}
            {summary.invalid_row_count > 0 ? (
              <span className="chip">
                ردیف نامعتبر: <strong>{summary.invalid_row_count}</strong>
              </span>
            ) : null}
          </div>
          {summary.invalid_rows.length > 0 ? (
            <Alert tone="warning">
              <p>ردیف‌های اکسل ردشده:</p>
              <ul className="plain-list">
                {summary.invalid_rows.slice(0, 20).map((row) => (
                  <li key={`${row.row_number}-${row.reason}`}>
                    ردیف {row.row_number}
                    {row.column ? ` — ستون «${row.column}»` : ''}
                    {row.name ? ` — ${row.name}` : ''}
                    {row.code ? (
                      <span className="ltr"> ({row.code})</span>
                    ) : null}
                    : {translateApiDetail(row.reason)}
                  </li>
                ))}
              </ul>
              {summary.invalid_rows.length > 20 ? (
                <p className="field-hint">
                  و {summary.invalid_rows.length - 20} مورد دیگر…
                </p>
              ) : null}
            </Alert>
          ) : null}
          {summary.parse_warnings.length > 0 ? (
            <Alert tone="warning">
              <ul className="plain-list">
                {summary.parse_warnings.map((w) => (
                  <li key={w}>{translateApiDetail(w)}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
        </div>
      ) : null}

      <div className="step-actions">
        <Button
          disabled={!canContinue}
          onClick={() => matchMutation.mutate()}
        >
          {matchMutation.isPending ? 'در حال تطابق…' : 'شروع تطابق و ادامه'}
        </Button>
        <Button
          variant="secondary"
          disabled={uploading || matchMutation.isPending || busy}
          onClick={() => {
            reset()
            setPendingExcel(null)
            setPendingPdf(null)
            setSupplierKey('')
            setExcelError(null)
            setPdfError(null)
            setFormError(null)
          }}
        >
          شروع مجدد
        </Button>
      </div>
    </section>
  )
}
