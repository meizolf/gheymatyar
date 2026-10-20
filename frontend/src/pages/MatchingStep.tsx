import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { Candidate } from '../api/types'
import { ProductSearch } from '../components/ProductSearch'
import { Alert } from '../components/ui/Alert'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Spinner } from '../components/ui/Spinner'
import { usePagedFilter } from '../hooks/usePagedFilter'
import { translateApiDetail } from '../utils/apiMessages'
import {
  MATCH_STATUS_LABEL,
  MATCH_TYPE_LABEL,
} from '../utils/format'
import { matchesSearch } from '../utils/searchNormalize'
import { invalidateSessionData, sessionQueryKeys } from '../workflow/queryKeys'
import { enqueueSessionOp } from '../workflow/sessionQueue'
import { useWorkflow } from '../workflow/WorkflowContext'

type StatusFilter = 'ALL' | 'MATCHED' | 'UNMATCHED' | 'AMBIGUOUS'

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'MATCHED') return 'ok'
  if (status === 'AMBIGUOUS') return 'warn'
  if (status === 'UNMATCHED') return 'danger'
  return 'neutral'
}

export function MatchingStep() {
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
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [editing, setEditing] = useState<Candidate | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selectedRow, setSelectedRow] = useState<{
    rowNumber: number
    label: string
  } | null>(null)

  const candidatesQuery = useQuery({
    queryKey: sessionQueryKeys.candidates(sessionId ?? ''),
    queryFn: () => api.listCandidates(sessionId!),
    enabled: Boolean(sessionId),
  })

  const filterPredicate = useCallback(
    (item: Candidate, q: string) =>
      matchesSearch(
        [
          item.supplier_name,
          item.pioneers_name,
          item.supplier_code,
          item.pioneers_code,
        ],
        q,
      ),
    [],
  )

  const statusFiltered = useMemo(() => {
    const all = candidatesQuery.data?.candidates ?? []
    if (statusFilter === 'ALL') return all
    return all.filter((c) => c.status === statusFilter)
  }, [candidatesQuery.data, statusFilter])

  const pager = usePagedFilter(statusFiltered, filterPredicate, 40)

  const confirmMutation = useMutation({
    mutationFn: async ({
      candidateId,
      rowNumber,
    }: {
      candidateId: string
      rowNumber: number
    }) =>
      enqueueSessionOp(() =>
        api.confirmMapping(sessionId!, candidateId, rowNumber, true),
      ),
    onSuccess: async () => {
      setEditing(null)
      setSelectedRow(null)
      setActionError(null)
      if (!sessionId) return
      await invalidateSessionData(
        queryClient,
        sessionId,
        summary?.supplier_key,
      )
      const next = await api.getSession(sessionId)
      setSummary(next)
    },
    onError: (err) => {
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setActionError(translateApiDetail(err.detail))
        return
      }
      setActionError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در تأیید نگاشت',
        ),
      )
    },
  })

  const opsPending =
    pendingSessionOps > 0 || exportInFlight || confirmMutation.isPending

  if (!sessionId) {
    return (
      <Alert tone="warning">
        جلسه‌ای فعال نیست. از مرحله بارگذاری شروع کنید.
        <div className="step-actions">
          <Button onClick={() => setStep(1)}>بازگشت به بارگذاری</Button>
        </div>
      </Alert>
    )
  }

  if (candidatesQuery.isLoading) {
    return <Spinner label="در حال دریافت نتایج تطابق…" />
  }

  if (candidatesQuery.isError) {
    const err = candidatesQuery.error
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

  const data = candidatesQuery.data!
  const unresolved = data.unmatched_count + data.ambiguous_count

  return (
    <section className="panel">
      <h1>تطابق محصولات</h1>
      <p className="lede">
        تطابق‌های خودکار و نگاشت‌های ذخیره‌شده را بررسی کنید. پیشنهادهای فازی
        هرگز به‌صورت خودکار تأیید نمی‌شوند.
      </p>

      <div className="chip-row">
        <span className="chip">
          متطابق: <strong>{data.matched_count}</strong>
        </span>
        <span className="chip">
          بدون تطابق: <strong>{data.unmatched_count}</strong>
        </span>
        <span className="chip">
          مبهم: <strong>{data.ambiguous_count}</strong>
        </span>
        {unresolved > 0 ? (
          <span className="chip">
            حل‌نشده: <strong>{unresolved}</strong>
          </span>
        ) : null}
      </div>

      {unresolved > 0 ? (
        <Alert tone="warning">
          {unresolved} محصول هنوز حل نشده است. می‌توانید ادامه دهید، اما در
          پیش‌نمایش قیمت فقط محصولات متطابق نمایش داده می‌شوند.
        </Alert>
      ) : (
        <Alert tone="success">همه محصولات تأمین‌کننده تطابق دارند.</Alert>
      )}

      {actionError ? <Alert tone="error">{actionError}</Alert> : null}

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="فیلتر وضعیت">
          {(
            [
              ['ALL', 'همه'],
              ['MATCHED', 'متطابق'],
              ['UNMATCHED', 'بدون تطابق'],
              ['AMBIGUOUS', 'مبهم'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={statusFilter === key}
              className={statusFilter === key ? 'is-active' : ''}
              onClick={() => {
                setStatusFilter(key)
                pager.setQuery(pager.query)
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="field search-field">
          <label htmlFor="match-search" className="sr-only">
            جستجو
          </label>
          <input
            id="match-search"
            type="search"
            placeholder="جستجو در نام یا کد…"
            value={pager.query}
            onChange={(e) => pager.setQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>نام تأمین‌کننده</th>
              <th>کد تأمین‌کننده</th>
              <th>نام پایونیرز</th>
              <th>کد پایونیرز</th>
              <th>نوع تطابق</th>
              <th>وضعیت</th>
              <th>عملیات</th>
            </tr>
          </thead>
          <tbody>
            {pager.pageItems.length === 0 ? (
              <tr>
                <td colSpan={7}>موردی یافت نشد.</td>
              </tr>
            ) : (
              pager.pageItems.map((c) => (
                <tr key={c.candidate_id}>
                  <td>{c.supplier_name}</td>
                  <td className="ltr">{c.supplier_code ?? '—'}</td>
                  <td>{c.pioneers_name ?? '—'}</td>
                  <td className="ltr">{c.pioneers_code ?? '—'}</td>
                  <td>
                    {c.match_type
                      ? (MATCH_TYPE_LABEL[c.match_type] ?? c.match_type)
                      : '—'}
                  </td>
                  <td>
                    <Badge tone={statusTone(c.status)}>
                      {MATCH_STATUS_LABEL[c.status] ?? c.status}
                    </Badge>
                  </td>
                  <td>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={opsPending}
                      onClick={() => {
                        setEditing(c)
                        setSelectedRow(null)
                        setActionError(null)
                      }}
                    >
                      {c.status === 'MATCHED' ? 'اصلاح' : 'تطابق دستی'}
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span>
          نمایش {pager.pageItems.length} از {pager.filteredCount} (کل:{' '}
          {pager.totalCount})
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
          <span>
            صفحه {pager.page} از {pager.pageCount}
          </span>
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
          onClick={() => setStep(1)}
        >
          قبلی
        </Button>
        <Button disabled={opsPending} onClick={() => setStep(3)}>
          ادامه به پیش‌نمایش قیمت
        </Button>
      </div>

      {editing ? (
        <Modal
          title={`تطابق دستی — ${editing.supplier_name}`}
          onClose={() => {
            setEditing(null)
            setSelectedRow(null)
          }}
          actions={
            <>
              <Button
                disabled={!selectedRow || confirmMutation.isPending}
                onClick={() => {
                  if (!selectedRow) return
                  confirmMutation.mutate({
                    candidateId: editing.candidate_id,
                    rowNumber: selectedRow.rowNumber,
                  })
                }}
              >
                {confirmMutation.isPending ? 'در حال ذخیره…' : 'تأیید و ذخیره نگاشت'}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setEditing(null)
                  setSelectedRow(null)
                }}
              >
                انصراف
              </Button>
            </>
          }
        >
          <p className="field-hint">
            محصول پایونیرز را جستجو و انتخاب کنید. نگاشت تأییدشده در پایگاه داده
            ذخیره می‌شود.
          </p>
          {editing.suggestions.length > 0 ? (
            <div className="suggestions">
              <p>
                <strong>پیشنهادها (نیاز به تأیید دستی):</strong>
              </p>
              <ul className="plain-list">
                {editing.suggestions.map((s, idx) => {
                  const row = Number(s.row_number)
                  const name = String(s.pioneers_name ?? s.name ?? '')
                  const code = String(s.pioneers_code ?? s.code ?? '')
                  if (!row) return null
                  return (
                    <li key={`${row}-${idx}`}>
                      <Button
                        size="sm"
                        variant={
                          selectedRow?.rowNumber === row ? 'primary' : 'secondary'
                        }
                        onClick={() =>
                          setSelectedRow({
                            rowNumber: row,
                            label: code ? `${name} (${code})` : name,
                          })
                        }
                      >
                        {name || `ردیف ${row}`}
                        {code ? ` — ${code}` : ''}
                      </Button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
          <ProductSearch
            sessionId={sessionId}
            onSelect={(rowNumber, label) =>
              setSelectedRow({ rowNumber, label })
            }
          />
          {selectedRow ? (
            <Alert tone="info">
              انتخاب‌شده: {selectedRow.label} (ردیف {selectedRow.rowNumber})
            </Alert>
          ) : null}
        </Modal>
      ) : null}
    </section>
  )
}
