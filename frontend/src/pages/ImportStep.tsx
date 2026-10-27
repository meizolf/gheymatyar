import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { DetectionInfo } from '../api/types'
import { FileDropzone } from '../components/FileDropzone'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { describeApiError, translateApiDetail } from '../utils/apiMessages'
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
  const [detection, setDetection] = useState<DetectionInfo | null>(
    () => summary?.detection ?? null,
  )
  const [supplierConfirmed, setSupplierConfirmed] = useState(
    () => Boolean(summary?.supplier_confirmed),
  )
  const [changingSupplier, setChangingSupplier] = useState(false)
  const [excelError, setExcelError] = useState<string | null>(null)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [websiteKey, setWebsiteKey] = useState('')
  const [websiteError, setWebsiteError] = useState<string | null>(null)

  const suppliersQuery = useQuery({
    queryKey: ['suppliers'],
    queryFn: api.listSuppliers,
  })

  const busy = exportInFlight || pendingSessionOps > 0
  const pdfSuppliers = (suppliersQuery.data ?? []).filter((s) => s.source !== 'website')
  const websiteSuppliers = (suppliersQuery.data ?? []).filter((s) => s.source === 'website')
  const selectedWebsiteKey = websiteKey || websiteSuppliers[0]?.key || ''

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
      setExcelError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در بارگذاری اکسل',
        ),
      )
    },
  })

  const detectPdf = useMutation({
    mutationFn: async (file: File) => {
      const sid = await ensureSession()
      return enqueueSessionOp(() => api.detectSupplierPdf(sid, file))
    },
    onSuccess: async (data) => {
      setSummary(data.summary)
      setDetection(data.detection)
      setSupplierConfirmed(false)
      setChangingSupplier(false)
      setPendingPdf(null)
      setPdfError(null)
      setFormError(null)
      clearRestoreError()
      const suggested =
        data.detection.detected_supplier_id ??
        data.summary.supplier_key ??
        ''
      setSupplierKey(suggested)
      invalidateDownstream()
      await invalidateSessionData(
        queryClient,
        data.session_id,
        data.summary.supplier_key,
      )
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setFormError(translateApiDetail(err.detail))
        return
      }
      // Keep local pending PDF so the user can still pick a supplier manually.
      setDetection(null)
      setSupplierConfirmed(false)
      setChangingSupplier(true)
      setPdfError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در شناسایی PDF',
        ),
      )
    },
  })

  // Contacts the supplier website only when the user presses the button.
  const fetchWebsite = useMutation({
    mutationFn: async (key: string) => {
      const sid = await ensureSession()
      return enqueueSessionOp(() => api.fetchSupplierWebsite(sid, key))
    },
    onSuccess: async (data) => {
      setSummary(data)
      setSupplierConfirmed(Boolean(data.supplier_confirmed))
      setSupplierKey(data.supplier_key ?? '')
      setDetection(null)
      setChangingSupplier(false)
      setPendingPdf(null)
      setPdfError(null)
      setWebsiteError(null)
      setFormError(null)
      clearRestoreError()
      invalidateDownstream()
      await invalidateSessionData(queryClient, data.session_id, data.supplier_key)
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setFormError(translateApiDetail(err.detail))
        return
      }
      setWebsiteError(describeApiError(err, 'دریافت قیمت از سایت ناموفق بود.'))
    },
  })

  const confirmPdf = useMutation({
    mutationFn: async ({
      key,
      recoveryFile,
    }: {
      key: string
      recoveryFile: File | null
    }) => {
      const sid = await ensureSession()
      // Detection request failed before the server stored the PDF — re-upload
      // with the explicit supplier key (still validates identity/format).
      if (recoveryFile) {
        return enqueueSessionOp(() =>
          api.uploadSupplierPdf(sid, key, recoveryFile),
        )
      }
      return enqueueSessionOp(() => api.confirmSupplierPdf(sid, key))
    },
    onSuccess: async (data) => {
      setSummary(data)
      setSupplierConfirmed(Boolean(data.supplier_confirmed))
      setSupplierKey(data.supplier_key ?? supplierKey)
      setChangingSupplier(false)
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
      setSupplierConfirmed(false)
      setPdfError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در تأیید تأمین‌کننده',
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
      setExcelError('فقط فایل .xlsx یا .xls پشتیبانی می‌شود (.xlsm مجاز نیست)')
      return
    }
    if (
      uploadExcel.isPending ||
      detectPdf.isPending ||
      confirmPdf.isPending ||
      matchMutation.isPending ||
      busy
    ) {
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
    if (
      uploadExcel.isPending ||
      detectPdf.isPending ||
      confirmPdf.isPending ||
      matchMutation.isPending ||
      busy
    ) {
      setPdfError('لطفاً تا پایان عملیات جاری صبر کنید')
      return
    }
    // Replacing the PDF always resets confirmation.
    setPendingPdf(file)
    setPdfError(null)
    setSupplierConfirmed(false)
    setChangingSupplier(false)
    setDetection(null)
    detectPdf.mutate(file)
  }

  function resetLocalState() {
    setPendingExcel(null)
    setPendingPdf(null)
    setSupplierKey('')
    setDetection(null)
    setSupplierConfirmed(false)
    setChangingSupplier(false)
    setExcelError(null)
    setPdfError(null)
    setFormError(null)
  }

  const excelReady = Boolean(
    summary?.pioneers_filename && summary.product_count > 0,
  )
  const pdfUploaded = Boolean(summary?.pdf_filename)
  const websiteSource = summary?.supplier_source ?? null
  // Supplier prices are ready from a confirmed PDF or a fetched website list.
  const pdfReady = Boolean(
    supplierConfirmed &&
      (summary?.pdf_filename || websiteSource) &&
      (summary?.supplier_item_count ?? 0) > 0,
  )
  const uploading =
    uploadExcel.isPending ||
    detectPdf.isPending ||
    confirmPdf.isPending ||
    fetchWebsite.isPending
  const awaitingConfirmation = pdfUploaded && !supplierConfirmed
  // Local file selected but not yet accepted by a successful detect — including
  // a failed replacement over a previously confirmed PDF A.
  const awaitingManualRecovery =
    Boolean(pendingPdf) && !supplierConfirmed && !detectPdf.isPending
  const showConfirmationPanel =
    !supplierConfirmed &&
    !detectPdf.isPending &&
    (awaitingConfirmation || awaitingManualRecovery)
  const suggestedName = detection?.detected_supplier_name ?? null
  const selectedName =
    suppliersQuery.data?.find((s) => s.key === supplierKey)?.display_name ||
    summary?.supplier_display_name ||
    null
  const detectionFailed =
    showConfirmationPanel &&
    (awaitingManualRecovery ||
      !detection?.detected_supplier_id ||
      detection.confidence === 'UNKNOWN')
  const needsManualSupplier =
    Boolean(pdfError) ||
    Boolean(pendingPdf) ||
    detectionFailed ||
    awaitingConfirmation ||
    supplierConfirmed
  const canContinue =
    excelReady &&
    pdfReady &&
    !uploading &&
    !matchMutation.isPending &&
    !busy &&
    !excelError &&
    !pdfError

  const supplierSelectLocked =
    uploading ||
    busy ||
    (supplierConfirmed && !changingSupplier) ||
    (awaitingConfirmation &&
      !changingSupplier &&
      !detectionFailed &&
      Boolean(detection?.detected_supplier_id))

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
                resetLocalState()
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
          label="اکسل پایونیرز (.xlsx / .xls)"
          accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
          pendingFile={pendingExcel}
          acceptedFilename={summary?.pioneers_filename}
          uploading={uploadExcel.isPending}
          error={excelError}
          disabled={uploading || matchMutation.isPending || busy}
          onSelect={onExcelSelect}
          hint="فقط نرخ فروش اصلی در خروجی تغییر می‌کند؛ فایل اصلی دست‌نخورده می‌ماند."
        />

        <FileDropzone
          label="لیست قیمت PDF تأمین‌کننده"
          accept=".pdf,application/pdf"
          pendingFile={pendingPdf}
          acceptedFilename={summary?.pdf_filename}
          uploading={detectPdf.isPending}
          error={pdfError}
          disabled={uploading || matchMutation.isPending || busy}
          onSelect={onPdfSelect}
          hint="پس از بارگذاری، شرکت به‌صورت خودکار شناسایی می‌شود و باید تأیید شود."
        />

        {websiteSuppliers.length > 0 ? (
          <div className="field">
            <label htmlFor="website-supplier">
              یا: دریافت قیمت از سایت تأمین‌کننده
            </label>
            <div className="search-row">
              <select
                id="website-supplier"
                value={selectedWebsiteKey}
                disabled={uploading || matchMutation.isPending || busy}
                onChange={(e) => {
                  setWebsiteKey(e.target.value)
                  setWebsiteError(null)
                }}
              >
                {websiteSuppliers.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.display_name}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                disabled={
                  !selectedWebsiteKey || uploading || matchMutation.isPending || busy
                }
                onClick={() => fetchWebsite.mutate(selectedWebsiteKey)}
              >
                {fetchWebsite.isPending ? 'در حال دریافت…' : 'دریافت قیمت از سایت'}
              </Button>
            </div>
            <p className="field-hint">
              فقط با زدن این دکمه به سایت رسمی تأمین‌کننده وصل می‌شود. سایر
              تأمین‌کنندگان بدون اینترنت کار می‌کنند.
            </p>
            {websiteError ? <Alert tone="error">{websiteError}</Alert> : null}
          </div>
        ) : null}

        {needsManualSupplier ? (
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
                disabled={supplierSelectLocked}
                onChange={(e) => {
                  setSupplierKey(e.target.value)
                  setPdfError(null)
                  if (supplierConfirmed) {
                    setSupplierConfirmed(false)
                  }
                }}
              >
                <option value="">انتخاب کنید…</option>
                {pdfSuppliers.map((s) => (
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
        ) : null}
      </div>

      {showConfirmationPanel ? (
        <div className="summary-box">
          <h2>تأیید شرکت تأمین‌کننده</h2>
          {detectionFailed ? (
            <Alert tone="warning">
              {awaitingManualRecovery
                ? 'شناسایی خودکار ناموفق بود، اما فایل PDF برای تأیید دستی نگه داشته شد. لطفاً تأمین‌کننده را انتخاب و تأیید کنید.'
                : 'شرکت به‌صورت خودکار شناسایی نشد. لطفاً تأمین‌کننده را از فهرست انتخاب کنید و تأیید نمایید.'}
            </Alert>
          ) : (
            <Alert tone="info">
              {suggestedName ? (
                <p>
                  پیشنهاد سامانه:{' '}
                  <strong>{suggestedName}</strong>
                  {detection?.confidence ? (
                    <span className="field-hint">
                      {' '}
                      (اطمینان: {detection.confidence})
                    </span>
                  ) : null}
                </p>
              ) : null}
              <p>
                آیا این لیست قیمت متعلق به شرکت{' '}
                <strong>{selectedName ?? 'انتخاب‌شده'}</strong> است؟
              </p>
            </Alert>
          )}
          {(changingSupplier || detectionFailed) && !suppliersQuery.isLoading ? (
            <p className="field-hint">
              در صورت نیاز، شرکت را از فهرست بالا تغییر دهید و سپس تأیید کنید.
            </p>
          ) : null}
          <div className="step-actions">
            <Button
              disabled={
                !supplierKey ||
                confirmPdf.isPending ||
                detectPdf.isPending ||
                busy
              }
              onClick={() =>
                confirmPdf.mutate({
                  key: supplierKey,
                  // Always upload the pending local file; never confirm stale A.
                  recoveryFile: pendingPdf,
                })
              }
            >
              {confirmPdf.isPending ? 'در حال تأیید…' : 'تأیید شرکت'}
            </Button>
            <Button
              variant="secondary"
              disabled={
                confirmPdf.isPending ||
                detectPdf.isPending ||
                busy ||
                awaitingManualRecovery
              }
              onClick={() => setChangingSupplier(true)}
            >
              تغییر شرکت
            </Button>
          </div>
        </div>
      ) : null}

      {uploading ? (
        <Spinner
          label={
            fetchWebsite.isPending
              ? 'در حال دریافت قیمت از سایت تأمین‌کننده…'
              : detectPdf.isPending
              ? 'در حال شناسایی تأمین‌کننده…'
              : confirmPdf.isPending
                ? 'در حال استخراج قیمت‌ها…'
                : 'در حال ارسال و پردازش فایل…'
          }
        />
      ) : null}

      {summary && (excelReady || pdfReady || pdfUploaded) ? (
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
                {supplierConfirmed ? null : ' (در انتظار تأیید)'}
              </span>
            ) : null}
            {summary.pdf_filename ? (
              <span className="chip">
                PDF: <strong className="ltr">{summary.pdf_filename}</strong>
              </span>
            ) : null}
            {summary.supplier_item_count > 0 ? (
              <span className="chip">
                {websiteSource ? 'اقلام سایت' : 'اقلام PDF'}:{' '}
                <strong>{summary.supplier_item_count}</strong>
              </span>
            ) : null}
            {websiteSource?.categories[0]?.updated ? (
              <span className="chip">
                به‌روزرسانی سایت: <strong>{websiteSource.categories[0].updated}</strong>
              </span>
            ) : null}
            {summary.invalid_row_count > 0 ? (
              <span className="chip">
                ردیف نامعتبر: <strong>{summary.invalid_row_count}</strong>
              </span>
            ) : null}
          </div>
          {websiteSource ? (
            <Alert tone="success">
              <p>
                {websiteSource.item_count} محصول از{' '}
                {websiteSource.categories.length} دسته سایت رسمی دریافت شد. همین
                قیمت‌ها تا پایان این جلسه برای تطابق و خروجی استفاده می‌شوند.
              </p>
              <ul className="plain-list">
                {websiteSource.categories.map((c) => (
                  <li key={c.title}>
                    {c.title}: {c.items} محصول
                    {c.excluded > 0 ? ` (${c.excluded} ردیف بدون قیمت کنار گذاشته شد)` : ''}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}
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
            resetLocalState()
          }}
        >
          شروع مجدد
        </Button>
      </div>
    </section>
  )
}
