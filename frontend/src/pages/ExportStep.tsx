import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { translateApiDetail } from '../utils/apiMessages'
import { sessionQueryKeys } from '../workflow/queryKeys'
import { enqueueSessionOp } from '../workflow/sessionQueue'
import { useWorkflow } from '../workflow/WorkflowContext'

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function ExportStep() {
  const {
    sessionId,
    setStep,
    reset,
    setSummary,
    exportInFlight,
    setExportInFlight,
    pendingSessionOps,
  } = useWorkflow()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const summaryQuery = useQuery({
    queryKey: sessionQueryKeys.session(sessionId ?? ''),
    queryFn: () => api.getSession(sessionId!),
    enabled: Boolean(sessionId),
  })

  const exportMutation = useMutation({
    mutationKey: sessionQueryKeys.export(sessionId ?? ''),
    mutationFn: async () => {
      if (pendingSessionOps > 0) {
        throw new Error('pending-ops')
      }
      setExportInFlight(true)
      try {
        return await enqueueSessionOp(async () => {
          const result = await api.exportExcel(sessionId!)
          if (
            result.exported_row_count !== result.updated_count ||
            result.exported_row_count < 1
          ) {
            throw new Error('count-mismatch')
          }
          const file = await api.downloadExcel(sessionId!)
          if (
            file.exportedRowCount !== result.exported_row_count ||
            file.contentSha256 !== result.content_sha256
          ) {
            throw new Error('count-mismatch')
          }
          return { result, blob: file.blob }
        })
      } finally {
        setExportInFlight(false)
      }
    },
    onSuccess: async ({ result, blob }) => {
      triggerDownload(blob, result.output_filename)
      setMessage(
        `${result.exported_row_count} ردیف محصول در فایل «${result.output_filename}» ذخیره و دانلود شد.`,
      )
      setError(null)
      if (sessionId) {
        const next = await api.getSession(sessionId)
        setSummary(next)
        await queryClient.invalidateQueries({
          queryKey: sessionQueryKeys.session(sessionId),
        })
      }
    },
    onError: (err) => {
      if (err instanceof Error && err.message === 'pending-ops') {
        setError(
          'هنوز تصمیم‌هایی در حال ثبت است. پس از اتمام، دوباره خروجی بگیرید.',
        )
        setMessage(null)
        return
      }
      if (err instanceof Error && err.message === 'count-mismatch') {
        setError(
          'تعداد ردیف‌های فایل خروجی با انتخاب تأییدشده یکی نیست. فایل دانلود نشد.',
        )
        setMessage(null)
        return
      }
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setError(translateApiDetail(err.detail))
        return
      }
      setError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در تولید خروجی',
        ),
      )
      setMessage(null)
    },
  })

  if (!sessionId) {
    return (
      <Alert tone="warning">
        جلسه‌ای فعال نیست.
        <div className="step-actions">
          <Button onClick={() => setStep(1)}>شروع مجدد</Button>
        </div>
      </Alert>
    )
  }

  if (summaryQuery.isLoading) {
    return <Spinner />
  }

  const exportable = summaryQuery.data?.exportable_count ?? 0
  const blocked =
    exportInFlight ||
    exportMutation.isPending ||
    pendingSessionOps > 0

  return (
    <section className="panel">
      <h1>تولید فایل اکسل</h1>
      <p className="lede">
        فایل خروجی فقط محصولات تأییدشده را دارد. در هر ردیف فقط ستون{' '}
        <strong>نرخ فروش اصلی</strong> تغییر می‌کند. فایل اکسل اصلی شما
        دست‌نخورده باقی می‌ماند. هیچ واردکردنی به نرم‌افزار پایونیرز به‌صورت
        خودکار انجام نمی‌شود.
      </p>

      <div className="summary-box">
        <div className="chip-row">
          <span className="chip">
            تغییرات تأییدشده: <strong>{exportable}</strong>
          </span>
          {summaryQuery.data?.pioneers_filename ? (
            <span className="chip">
              منبع:{' '}
              <strong className="ltr">
                {summaryQuery.data.pioneers_filename}
              </strong>
            </span>
          ) : null}
        </div>
      </div>

      {pendingSessionOps > 0 ? (
        <Alert tone="warning">
          هنوز عملیات قبلی (مثلاً حذف یا تأیید) در حال انجام است. تا پایان آن
          نمی‌توان خروجی گرفت.
        </Alert>
      ) : null}

      {exportable < 1 ? (
        <Alert tone="warning">
          هیچ ردیف تأییدشده با قیمت تغییرکرده وجود ندارد. به پیش‌نمایش برگردید و
          موارد را تأیید کنید.
        </Alert>
      ) : (
        <Alert tone="info">
          با فشردن دکمه، فایل جدید تولید و دانلود می‌شود. تا پایان عملیات از
          کلیک مجدد خودداری کنید.
        </Alert>
      )}

      {error ? <Alert tone="error">{error}</Alert> : null}
      {message ? <Alert tone="success">{message}</Alert> : null}

      <div className="step-actions">
        <Button
          variant="secondary"
          disabled={exportInFlight || exportMutation.isPending}
          onClick={() => setStep(3)}
        >
          قبلی
        </Button>
        <Button
          disabled={exportable < 1 || blocked}
          onClick={() => {
            if (
              !window.confirm(
                'فایل اکسل جدید فقط با محصولات تأییدشده تولید شود؟ در هر ردیف فقط نرخ فروش اصلی به‌روز می‌شود.',
              )
            ) {
              return
            }
            exportMutation.mutate()
          }}
        >
          {exportInFlight || exportMutation.isPending
            ? 'در حال تولید…'
            : 'تولید و دانلود اکسل'}
        </Button>
        <Button
          variant="secondary"
          disabled={exportInFlight || exportMutation.isPending}
          onClick={() => {
            reset()
            setStep(1)
            setMessage(null)
            setError(null)
          }}
        >
          شروع عملیات جدید
        </Button>
      </div>
    </section>
  )
}
