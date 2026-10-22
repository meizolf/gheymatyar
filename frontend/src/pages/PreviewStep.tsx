import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { Candidate } from '../api/types'
import { Alert } from '../components/ui/Alert'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { usePagedFilter } from '../hooks/usePagedFilter'
import { translateApiDetail } from '../utils/apiMessages'
import {
  formatPercent,
  formatPrice,
  REVIEW_LABEL,
} from '../utils/format'
import { matchesSearch } from '../utils/searchNormalize'
import { invalidateSessionData, sessionQueryKeys } from '../workflow/queryKeys'
import { enqueueSessionOp } from '../workflow/sessionQueue'
import { useWorkflow } from '../workflow/WorkflowContext'

type PreviewFilter = 'ALL' | 'EXPORTABLE' | 'WARNINGS' | 'EXCLUDED' | 'UNCHANGED'

const CURRENCY_LABEL: Record<string, string> = {
  rial: 'ریال',
  toman: 'تومان',
}

const BASIS_LABEL: Record<string, string> = {
  meter: 'هر متر',
  piece: 'هر عدد',
  listed: 'قیمت اعلام‌شده',
}

const TAX_LABEL: Record<string, string> = {
  included_10_percent: '۱۰٪ ارزش افزوده در مبلغ',
  not_stated: 'مالیات در سند نیامده',
}

function isHardBlocked(candidate: Candidate): boolean {
  return (candidate.pricing_blockers?.length ?? 0) > 0
}

function approvableWarnings(candidate: Candidate): string[] {
  const blocked = new Set(candidate.pricing_blockers ?? [])
  return candidate.warnings.filter((warning) => !blocked.has(warning))
}

function provenanceText(candidate: Candidate): string {
  const parts: string[] = []
  if (candidate.source_currency) {
    parts.push(
      `ارز: ${CURRENCY_LABEL[candidate.source_currency] ?? candidate.source_currency}`,
    )
  }
  if (candidate.price_basis) {
    parts.push(
      `مبنا: ${BASIS_LABEL[candidate.price_basis] ?? candidate.price_basis}`,
    )
  }
  if (candidate.source_unit) parts.push(`واحد: ${candidate.source_unit}`)
  if (candidate.tax_state) {
    parts.push(
      `مالیات: ${TAX_LABEL[candidate.tax_state] ?? candidate.tax_state}`,
    )
  }
  if (candidate.source_page) parts.push(`صفحه ${candidate.source_page}`)
  return parts.join(' · ')
}

function candidateFilter(c: Candidate, filter: PreviewFilter): boolean {
  const oldP = c.old_price
  const newP = c.new_price
  const unchanged =
    oldP !== null && newP !== null && String(oldP) === String(newP)
  switch (filter) {
    case 'EXPORTABLE':
      return c.exportable
    case 'WARNINGS':
      return c.warnings.length > 0
    case 'EXCLUDED':
      return c.review_decision === 'EXCLUDE'
    case 'UNCHANGED':
      return unchanged
    default:
      return true
  }
}

function isPriceChanged(c: Candidate): boolean {
  return (
    c.old_price !== null &&
    c.new_price !== null &&
    String(c.old_price) !== String(c.new_price)
  )
}

export function PreviewStep() {
  const {
    sessionId,
    setStep,
    reset,
    setSummary,
    summary,
    exportInFlight,
    pendingSessionOps,
  } = useWorkflow()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<PreviewFilter>('ALL')
  const [error, setError] = useState<string | null>(null)

  const previewQuery = useQuery({
    queryKey: sessionQueryKeys.preview(sessionId ?? ''),
    queryFn: () => api.preview(sessionId!),
    enabled: Boolean(sessionId),
  })

  const summaryQuery = useQuery({
    queryKey: sessionQueryKeys.session(sessionId ?? ''),
    queryFn: () => api.getSession(sessionId!),
    enabled: Boolean(sessionId),
  })

  const predicate = useCallback(
    (item: Candidate, q: string) =>
      matchesSearch(
        [item.supplier_name, item.pioneers_name, item.pioneers_code],
        q,
      ),
    [],
  )

  const filtered = useMemo(() => {
    const all = previewQuery.data?.candidates ?? []
    return all.filter((c) => candidateFilter(c, filter))
  }, [previewQuery.data, filter])

  const pager = usePagedFilter(filtered, predicate, 40)

  const reviewMutation = useMutation({
    mutationKey: sessionQueryKeys.review(sessionId ?? ''),
    mutationFn: ({
      candidateId,
      decision,
    }: {
      candidateId: string
      decision: 'INCLUDE' | 'EXCLUDE' | 'APPROVE'
    }) =>
      enqueueSessionOp(() =>
        api.setReview(sessionId!, candidateId, decision),
      ),
    onSuccess: async () => {
      setError(null)
      if (!sessionId) return
      await invalidateSessionData(
        queryClient,
        sessionId,
        summary?.supplier_key ?? summaryQuery.data?.supplier_key,
      )
      const next = await api.getSession(sessionId)
      setSummary(next)
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setError(translateApiDetail(err.detail))
        return
      }
      setError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در ثبت تصمیم',
        ),
      )
    },
  })

  const opsPending =
    pendingSessionOps > 0 || exportInFlight || reviewMutation.isPending

  if (!sessionId) {
    return (
      <Alert tone="warning">
        جلسه‌ای فعال نیست.
        <div className="step-actions">
          <Button onClick={() => setStep(1)}>بازگشت</Button>
        </div>
      </Alert>
    )
  }

  if (previewQuery.isLoading) {
    return <Spinner label="در حال دریافت پیش‌نمایش قیمت…" />
  }

  if (previewQuery.isError) {
    const err = previewQuery.error
    if (isApiError(err) && err.sessionExpired) {
      return (
        <Alert tone="error">
          جلسه منقضی شده — لطفاً دوباره بارگذاری کنید.
          <div className="step-actions">
            <Button
              onClick={() => {
                reset()
                setStep(1)
              }}
            >
              شروع مجدد
            </Button>
          </div>
        </Alert>
      )
    }
    return (
      <Alert tone="error">
        {translateApiDetail(isApiError(err) ? err.detail : undefined)}
      </Alert>
    )
  }

  const candidates = previewQuery.data!.candidates
  const exportableCount =
    summaryQuery.data?.exportable_count ??
    candidates.filter((c) => c.exportable).length
  const warningCount = candidates.filter((c) => c.warnings.length > 0).length
  const excludedCount = candidates.filter(
    (c) => c.review_decision === 'EXCLUDE',
  ).length
  const unchangedCount = candidates.filter(
    (c) =>
      c.old_price !== null &&
      c.new_price !== null &&
      String(c.old_price) === String(c.new_price),
  ).length
  const changedDetected = candidates.filter(isPriceChanged).length
  const changedExportable = candidates.filter(
    (c) => isPriceChanged(c) && c.exportable,
  ).length

  return (
    <section className="panel">
      <h1>پیش‌نمایش قیمت</h1>
      <p className="lede">
        قیمت‌ها و هشدارها از سرور آمده‌اند. تغییرات مشکوک نیاز به تأیید صریح
        دارند.
      </p>

      <div className="chip-row">
        <span className="chip">
          متطابق: <strong>{previewQuery.data!.matched_count}</strong>
        </span>
        <span className="chip">
          قابل خروجی: <strong>{exportableCount}</strong>
        </span>
        <span className="chip" title="ردیف‌هایی با قیمت متفاوت (حتی اگر حذف‌شده)">
          اختلاف قیمت: <strong>{changedDetected}</strong>
        </span>
        <span className="chip" title="اختلاف‌هایی که در خروجی اعمال می‌شوند">
          به‌روزرسانی خروجی: <strong>{changedExportable}</strong>
        </span>
        <span className="chip">
          بدون تغییر: <strong>{unchangedCount}</strong>
        </span>
        <span className="chip">
          هشدار: <strong>{warningCount}</strong>
        </span>
        <span className="chip">
          حذف‌شده: <strong>{excludedCount}</strong>
        </span>
      </div>

      {opsPending ? (
        <Alert tone="info">
          در حال ثبت تصمیم… تا پایان این عملیات نمی‌توانید به خروجی بروید.
        </Alert>
      ) : null}

      {error ? <Alert tone="error">{error}</Alert> : null}

      <div className="toolbar">
        <div className="tabs" role="tablist">
          {(
            [
              ['ALL', 'همه'],
              ['EXPORTABLE', 'قابل خروجی'],
              ['WARNINGS', 'هشداردار'],
              ['EXCLUDED', 'حذف‌شده'],
              ['UNCHANGED', 'بدون تغییر'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filter === key ? 'is-active' : ''}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="جستجو…"
          value={pager.query}
          onChange={(e) => pager.setQuery(e.target.value)}
          aria-label="جستجو در پیش‌نمایش"
        />
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>تأمین‌کننده</th>
              <th>پایونیرز</th>
              <th>قیمت قدیم</th>
              <th>قیمت جدید</th>
              <th>اختلاف</th>
              <th>درصد</th>
              <th>وضعیت</th>
              <th>هشدار</th>
              <th>عملیات</th>
            </tr>
          </thead>
          <tbody>
            {pager.pageItems.length === 0 ? (
              <tr>
                <td colSpan={9}>موردی یافت نشد.</td>
              </tr>
            ) : (
              pager.pageItems.map((c) => {
                const blocked = isHardBlocked(c)
                const softWarnings = approvableWarnings(c)
                const excluded = c.review_decision === 'EXCLUDE'
                const needsApprove =
                  !blocked &&
                  softWarnings.length > 0 &&
                  c.review_decision !== 'APPROVE'
                const provenance = provenanceText(c)
                return (
                  <tr
                    key={c.candidate_id}
                    className={
                      blocked
                        ? 'row-blocked'
                        : excluded
                          ? 'row-excluded'
                          : needsApprove
                            ? 'row-warn'
                            : c.exportable
                              ? 'row-ok'
                              : ''
                    }
                  >
                    <td>
                      {c.supplier_name}
                      {provenance ? (
                        <div className="provenance">{provenance}</div>
                      ) : null}
                    </td>
                    <td>{c.pioneers_name ?? '—'}</td>
                    <td className="ltr">{formatPrice(c.old_price)}</td>
                    <td className="ltr">{formatPrice(c.new_price)}</td>
                    <td className="ltr">{formatPrice(c.absolute_change)}</td>
                    <td className="ltr">
                      {formatPercent(c.percentage_change)}
                    </td>
                    <td>
                      <Badge
                        tone={
                          blocked
                            ? 'danger'
                            : c.exportable
                              ? 'ok'
                              : needsApprove
                                ? 'warn'
                                : excluded
                                  ? 'neutral'
                                  : 'danger'
                        }
                      >
                        {blocked
                          ? 'مسدود'
                          : c.exportable
                            ? 'معتبر'
                            : needsApprove
                              ? 'نیاز به تأیید هشدار'
                              : (REVIEW_LABEL[c.review_decision] ??
                                c.review_decision)}
                      </Badge>
                    </td>
                    <td>
                      {c.warnings.length > 0 ? (
                        <ul className="warn-list">
                          {c.warnings.map((w) => (
                            <li key={w}>{translateApiDetail(w)}</li>
                          ))}
                        </ul>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <div className="row-actions">
                        {blocked ? (
                          <span className="blocked-note">تأیید ممکن نیست</span>
                        ) : null}
                        {!blocked && excluded && softWarnings.length > 0 ? (
                          <Button
                            size="sm"
                            disabled={opsPending}
                            onClick={() =>
                              void reviewMutation.mutateAsync({
                                candidateId: c.candidate_id,
                                decision: 'APPROVE',
                              })
                            }
                          >
                            تأیید هشدار و شامل کردن
                          </Button>
                        ) : null}
                        {!blocked && excluded && softWarnings.length === 0 ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={opsPending}
                            onClick={() =>
                              void reviewMutation.mutateAsync({
                                candidateId: c.candidate_id,
                                decision: 'INCLUDE',
                              })
                            }
                          >
                            شامل کردن
                          </Button>
                        ) : null}
                        {!blocked && !excluded && needsApprove ? (
                          <Button
                            size="sm"
                            disabled={opsPending}
                            onClick={() =>
                              void reviewMutation.mutateAsync({
                                candidateId: c.candidate_id,
                                decision: 'APPROVE',
                              })
                            }
                          >
                            تأیید هشدار
                          </Button>
                        ) : null}
                        {!excluded ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={opsPending}
                            onClick={() =>
                              void reviewMutation.mutateAsync({
                                candidateId: c.candidate_id,
                                decision: 'EXCLUDE',
                              })
                            }
                          >
                            حذف از خروجی
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span>
          {pager.filteredCount} مورد — صفحه {pager.page} از {pager.pageCount}
        </span>
        <div className="pager-btns">
          <Button
            size="sm"
            variant="secondary"
            disabled={pager.page <= 1}
            onClick={() => pager.setPage(pager.page - 1)}
          >
            قبلی
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={pager.page >= pager.pageCount}
            onClick={() => pager.setPage(pager.page + 1)}
          >
            بعدی
          </Button>
        </div>
      </div>

      <div className="step-actions">
        <Button
          variant="secondary"
          disabled={opsPending}
          onClick={() => setStep(2)}
        >
          قبلی
        </Button>
        <Button
          disabled={exportableCount < 1 || opsPending}
          onClick={() => setStep(4)}
          title={
            opsPending ? 'تا پایان ثبت تصمیم‌ها صبر کنید' : undefined
          }
        >
          {opsPending
            ? 'در انتظار ثبت تصمیم…'
            : `ادامه به خروجی (${exportableCount})`}
        </Button>
      </div>
    </section>
  )
}
