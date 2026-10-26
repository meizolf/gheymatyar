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
import { describeApiError, translateApiDetail } from '../utils/apiMessages'
import {
  MATCH_STATUS_LABEL,
  MATCH_TYPE_LABEL,
} from '../utils/format'
import { matchesSearch } from '../utils/searchNormalize'
import { invalidateSessionData, sessionQueryKeys } from '../workflow/queryKeys'
import { enqueueSessionOp } from '../workflow/sessionQueue'
import { useWorkflow } from '../workflow/WorkflowContext'

type StatusFilter = 'ALL' | 'MATCHED' | 'UNMATCHED' | 'AMBIGUOUS' | 'IGNORED'

// Row warnings shown under the status badge on the matching table.
const ROW_WARNING =
  /saved Pioneers mapping no longer identifies a single product|Pioneers product is already matched to another supplier product/i

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'MATCHED') return 'ok'
  if (status === 'AMBIGUOUS') return 'warn'
  if (status === 'UNMATCHED') return 'danger'
  return 'neutral'
}

function countByStatus(candidates: Candidate[]) {
  let matched = 0
  let unmatched = 0
  let ambiguous = 0
  let ignored = 0
  for (const candidate of candidates) {
    if (candidate.status === 'MATCHED') matched += 1
    else if (candidate.status === 'UNMATCHED') unmatched += 1
    else if (candidate.status === 'AMBIGUOUS') ambiguous += 1
    else if (candidate.status === 'IGNORED') ignored += 1
  }
  return { matched, unmatched, ambiguous, ignored }
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
  const [pendingDelete, setPendingDelete] = useState<Candidate | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [selectedRow, setSelectedRow] = useState<{
    rowNumber: number
    label: string
  } | null>(null)

  const candidatesQuery = useQuery({
    queryKey: sessionQueryKeys.candidates(sessionId ?? ''),
    queryFn: () => api.listCandidates(sessionId!),
    enabled: Boolean(sessionId),
  })

  // Fetched each time the dialog opens: which products are taken changes as
  // other rows are mapped. Saving still re-checks on the server.
  const suggestionsQuery = useQuery({
    queryKey: sessionQueryKeys.suggestions(sessionId ?? '', editing?.candidate_id ?? ''),
    queryFn: () => api.candidateSuggestions(sessionId!, editing!.candidate_id),
    enabled: Boolean(sessionId && editing),
    staleTime: 0,
  })
  const dialogSuggestions =
    suggestionsQuery.data?.suggestions ?? editing?.suggestions ?? []

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

  const statusCounts = useMemo(
    () => countByStatus(candidatesQuery.data?.candidates ?? []),
    [candidatesQuery.data],
  )

  const statusFiltered = useMemo(() => {
    const all = candidatesQuery.data?.candidates ?? []
    if (statusFilter === 'ALL') {
      return all.filter((c) => c.status !== 'IGNORED')
    }
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
      setActionMessage('نگاشت ذخیره شد و در تطابق‌های بعدی همین تأمین‌کننده اولویت دارد.')
      if (!sessionId) return
      try {
        await invalidateSessionData(
          queryClient,
          sessionId,
          summary?.supplier_key,
        )
        const next = await api.getSession(sessionId)
        setSummary(next)
      } catch (err) {
        if (isApiError(err) && err.sessionExpired) {
          reset()
          setActionMessage(null)
          setActionError(translateApiDetail(err.detail))
        }
      }
    },
    onError: (err) => {
      setActionMessage(null)
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setActionError(translateApiDetail(err.detail))
        return
      }
      // A 409 names the supplier product that already holds this product.
      setActionError(describeApiError(err, 'خطا در تأیید نگاشت'))
    },
  })

  const ignoreMutation = useMutation({
    mutationFn: async (candidateId: string) =>
      enqueueSessionOp(() => api.ignoreCandidate(sessionId!, candidateId)),
    onSuccess: async () => {
      setPendingDelete(null)
      setActionError(null)
      setActionMessage(
        'محصول حذف شد و فقط در تب حذف‌شده دیده می‌شود. داده تأمین‌کننده و پایونیرز پاک نشده است.',
      )
      if (!sessionId) return
      try {
        await invalidateSessionData(
          queryClient,
          sessionId,
          summary?.supplier_key,
        )
        const next = await api.getSession(sessionId)
        setSummary(next)
      } catch (err) {
        if (isApiError(err) && err.sessionExpired) {
          reset()
          setActionMessage(null)
          setActionError(translateApiDetail(err.detail))
        }
      }
    },
    onError: (err) => {
      setPendingDelete(null)
      setActionMessage(null)
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setActionError(translateApiDetail(err.detail))
        return
      }
      setActionError(
        translateApiDetail(isApiError(err) ? err.detail : 'خطا در حذف محصول'),
      )
    },
  })

  const restoreMutation = useMutation({
    mutationFn: async (candidateId: string) =>
      enqueueSessionOp(() => api.restoreCandidate(sessionId!, candidateId)),
    onSuccess: async () => {
      setActionError(null)
      setActionMessage('محصول بازگردانی شد و دوباره در تطابق قرار گرفت.')
      if (!sessionId) return
      try {
        await invalidateSessionData(
          queryClient,
          sessionId,
          summary?.supplier_key,
        )
        const next = await api.getSession(sessionId)
        setSummary(next)
      } catch (err) {
        if (isApiError(err) && err.sessionExpired) {
          reset()
          setActionMessage(null)
          setActionError(translateApiDetail(err.detail))
        }
      }
    },
    onError: (err) => {
      setActionMessage(null)
      if (isApiError(err) && err.sessionExpired) {
        reset()
        setActionError(translateApiDetail(err.detail))
        return
      }
      setActionError(
        translateApiDetail(
          isApiError(err) ? err.detail : 'خطا در بازگردانی محصول',
        ),
      )
    },
  })

  const opsPending =
    pendingSessionOps > 0 ||
    exportInFlight ||
    confirmMutation.isPending ||
    ignoreMutation.isPending ||
    restoreMutation.isPending

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

  const unresolved = statusCounts.unmatched + statusCounts.ambiguous
  const activeCount =
    statusCounts.matched + statusCounts.unmatched + statusCounts.ambiguous

  return (
    <section className="panel">
      <h1>تطابق محصولات</h1>
      <p className="lede">
        تطابق‌های خودکار و نگاشت‌های ذخیره‌شده را بررسی کنید. پیشنهادهای فازی
        هرگز به‌صورت خودکار تأیید نمی‌شوند.
      </p>

      <div className="chip-row">
        <span className="chip">
          متطابق: <strong>{statusCounts.matched}</strong>
        </span>
        <span className="chip">
          بدون تطابق: <strong>{statusCounts.unmatched}</strong>
        </span>
        <span className="chip">
          مبهم: <strong>{statusCounts.ambiguous}</strong>
        </span>
        <span className="chip">
          حذف‌شده: <strong>{statusCounts.ignored}</strong>
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
      ) : activeCount === 0 && statusCounts.ignored > 0 ? (
        <Alert tone="info">
          همه محصولات این فهرست حذف شده‌اند. برای بررسی دوباره، آن‌ها را از تب
          حذف‌شده بازگردانی کنید.
        </Alert>
      ) : (
        <Alert tone="success">همه محصولات تأمین‌کننده تطابق دارند.</Alert>
      )}

      {actionMessage ? <Alert tone="success">{actionMessage}</Alert> : null}
      {actionError && !editing ? <Alert tone="error">{actionError}</Alert> : null}

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="فیلتر وضعیت">
          {(
            [
              ['ALL', 'همه', activeCount],
              ['MATCHED', 'متطابق', statusCounts.matched],
              ['UNMATCHED', 'بدون تطابق', statusCounts.unmatched],
              ['AMBIGUOUS', 'مبهم', statusCounts.ambiguous],
              ['IGNORED', 'حذف‌شده', statusCounts.ignored],
            ] as const
          ).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={statusFilter === key}
              aria-label={`${label} (${count})`}
              className={statusFilter === key ? 'is-active' : ''}
              onClick={() => {
                setStatusFilter(key)
                pager.setQuery(pager.query)
              }}
            >
              {label}
              <span className="tab-count"> ({count})</span>
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
                    {c.warnings.filter((warning) =>
                      ROW_WARNING.test(warning),
                    ).map((warning) => (
                      <div key={warning} className="field-hint">
                        {translateApiDetail(warning)}
                      </div>
                    ))}
                  </td>
                  <td>
                    <div className="row-actions inline">
                      {c.status === 'IGNORED' ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={opsPending}
                          onClick={() => {
                            setActionError(null)
                            setActionMessage(null)
                            restoreMutation.mutate(c.candidate_id)
                          }}
                        >
                          {restoreMutation.isPending ? 'در حال بازگردانی…' : 'بازگردانی'}
                        </Button>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={opsPending}
                            onClick={() => {
                              setEditing(c)
                              setPendingDelete(null)
                              setSelectedRow(null)
                              setActionError(null)
                              setActionMessage(null)
                            }}
                          >
                            {c.status === 'MATCHED' ? 'اصلاح' : 'تطابق دستی'}
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            disabled={opsPending}
                            onClick={() => {
                              setEditing(null)
                              setSelectedRow(null)
                              setPendingDelete(c)
                              setActionError(null)
                              setActionMessage(null)
                            }}
                          >
                            حذف
                          </Button>
                        </>
                      )}
                    </div>
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

      {pendingDelete ? (
        <Modal
          title="حذف محصول"
          onClose={() => {
            if (!ignoreMutation.isPending) setPendingDelete(null)
          }}
          actions={
            <>
              <Button
                variant="danger"
                disabled={ignoreMutation.isPending}
                onClick={() => ignoreMutation.mutate(pendingDelete.candidate_id)}
              >
                {ignoreMutation.isPending ? 'در حال حذف…' : 'حذف'}
              </Button>
              <Button
                variant="secondary"
                disabled={ignoreMutation.isPending}
                onClick={() => setPendingDelete(null)}
              >
                انصراف
              </Button>
            </>
          }
        >
          <p>
            «{pendingDelete.supplier_name}» از بررسی تطابق، پیش‌نمایش قیمت و
            خروجی اکسل کنار گذاشته می‌شود.
          </p>
          <p className="field-hint">
            این حذف دائمیِ داده نیست. ردیف تأمین‌کننده و محصول پایونیرز پاک
            نمی‌شوند و از تب حذف‌شده قابل بازگردانی است.
          </p>
        </Modal>
      ) : null}

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
          {dialogSuggestions.length > 0 ? (
            <div className="suggestions">
              <p>
                <strong>پیشنهادها (نیاز به تأیید دستی):</strong>
              </p>
              <ul className="plain-list">
                {dialogSuggestions.map((s, idx) => {
                  const row = Number(s.row_number)
                  const name = String(s.pioneers_name ?? s.name ?? '')
                  const code = String(s.pioneers_code ?? s.code ?? '')
                  const assignedTo = s.assigned_to ? String(s.assigned_to) : null
                  if (!row) return null
                  return (
                    <li key={`${row}-${idx}`}>
                      <Button
                        size="sm"
                        variant={
                          selectedRow?.rowNumber === row ? 'primary' : 'secondary'
                        }
                        disabled={assignedTo !== null}
                        title={
                          assignedTo
                            ? `قبلاً به «${assignedTo}» نگاشت شده است`
                            : undefined
                        }
                        onClick={() => {
                          setActionError(null)
                          setSelectedRow({
                            rowNumber: row,
                            label: code ? `${name} (${code})` : name,
                          })
                        }}
                      >
                        {name || `ردیف ${row}`}
                        {code ? ` — ${code}` : ''}
                      </Button>
                      {assignedTo ? (
                        <span className="field-hint">
                          {' '}قبلاً به «{assignedTo}» نگاشت شده است
                        </span>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
          <ProductSearch
            sessionId={sessionId}
            candidateId={editing.candidate_id}
            onSelect={(rowNumber, label) => {
              setActionError(null)
              setSelectedRow({ rowNumber, label })
            }}
          />
          {selectedRow ? (
            <Alert tone="info">
              انتخاب‌شده: {selectedRow.label} (ردیف {selectedRow.rowNumber})
            </Alert>
          ) : null}
          {/* Next to the confirm button, not behind the dialog. */}
          {actionError ? <Alert tone="error">{actionError}</Alert> : null}
        </Modal>
      ) : null}
    </section>
  )
}
