import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { Mapping } from '../api/types'
import { Alert } from '../components/ui/Alert'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Spinner } from '../components/ui/Spinner'
import { usePagedFilter } from '../hooks/usePagedFilter'
import { describeApiError } from '../utils/apiMessages'
import { MATCH_TYPE_LABEL } from '../utils/format'

export function MappingsPage() {
  const queryClient = useQueryClient()
  const [supplierKey, setSupplierKey] = useState('')
  const [editing, setEditing] = useState<Mapping | null>(null)
  const [editName, setEditName] = useState('')
  const [editCode, setEditCode] = useState('')
  const [error, setError] = useState<string | null>(null)

  const suppliersQuery = useQuery({
    queryKey: ['suppliers'],
    queryFn: api.listSuppliers,
  })

  const mappingsQuery = useQuery({
    queryKey: ['mappings', supplierKey],
    queryFn: () => api.listMappings(supplierKey),
    enabled: Boolean(supplierKey),
  })

  const predicate = useCallback((item: Mapping, q: string) => {
    const hay = [
      item.supplier_name_raw,
      item.pioneers_name_raw,
      item.pioneers_code,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return hay.includes(q.toLowerCase())
  }, [])

  const items = useMemo(
    () => mappingsQuery.data?.mappings ?? [],
    [mappingsQuery.data],
  )
  const pager = usePagedFilter(items, predicate, 50)

  const updateMutation = useMutation({
    mutationFn: () =>
      api.updateMapping(supplierKey, editing!.id, {
        pioneers_name_raw: editName.trim(),
        pioneers_code: editCode.trim() || null,
      }),
    onSuccess: async () => {
      setEditing(null)
      setError(null)
      await queryClient.invalidateQueries({
        queryKey: ['mappings', supplierKey],
      })
    },
    onError: (err) => {
      // A 409 names the supplier product that already holds this product.
      setError(describeApiError(err, 'خطا در به‌روزرسانی'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteMapping(supplierKey, id),
    onSuccess: async () => {
      setError(null)
      await queryClient.invalidateQueries({
        queryKey: ['mappings', supplierKey],
      })
    },
    onError: (err) => {
      setError(isApiError(err) ? err.detail : 'خطا در حذف')
    },
  })

  return (
    <section className="panel">
      <h1>نگاشت‌های ذخیره‌شده</h1>
      <p className="lede">
        نگاشت‌های نام تأییدشده برای هر تأمین‌کننده. در عملیات بعدی به‌صورت خودکار
        استفاده می‌شوند.
      </p>

      <div className="field" style={{ maxWidth: 360 }}>
        <label htmlFor="map-supplier">تأمین‌کننده</label>
        {suppliersQuery.isLoading ? (
          <Spinner />
        ) : (
          <select
            id="map-supplier"
            value={supplierKey}
            onChange={(e) => setSupplierKey(e.target.value)}
          >
            <option value="">انتخاب کنید…</option>
            {(suppliersQuery.data ?? []).map((s) => (
              <option key={s.key} value={s.key}>
                {s.display_name}
              </option>
            ))}
          </select>
        )}
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}

      {!supplierKey ? (
        <Alert tone="info">یک تأمین‌کننده انتخاب کنید.</Alert>
      ) : mappingsQuery.isLoading ? (
        <Spinner label="در حال دریافت نگاشت‌ها…" />
      ) : mappingsQuery.isError ? (
        <Alert tone="error">
          {isApiError(mappingsQuery.error)
            ? mappingsQuery.error.detail
            : 'خطا'}
        </Alert>
      ) : (
        <>
          <div className="toolbar">
            <input
              type="search"
              placeholder="جستجو در نگاشت‌ها…"
              value={pager.query}
              onChange={(e) => pager.setQuery(e.target.value)}
              aria-label="جستجوی نگاشت"
            />
            <span className="field-hint">{pager.filteredCount} نگاشت</span>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>نام تأمین‌کننده</th>
                  <th>نام پایونیرز</th>
                  <th>کد پایونیرز</th>
                  <th>نوع</th>
                  <th>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {pager.pageItems.length === 0 ? (
                  <tr>
                    <td colSpan={5}>نگاشتی ثبت نشده است.</td>
                  </tr>
                ) : (
                  pager.pageItems.map((m) => (
                    <tr key={m.id}>
                      <td>{m.supplier_name_raw}</td>
                      <td>
                        {m.pioneers_name_raw}
                        {m.conflicts_with && m.conflicts_with.length > 0 ? (
                          <div className="field-hint">
                            <Badge tone="danger">نگاشت تکراری</Badge>{' '}
                            همین کالای پایونیرز به{' '}
                            {m.conflicts_with.map((name) => `«${name}»`).join('، ')}{' '}
                            هم نگاشت شده است. یکی را اصلاح یا حذف کنید.
                          </div>
                        ) : null}
                      </td>
                      <td className="ltr">{m.pioneers_code ?? '—'}</td>
                      <td>
                        {MATCH_TYPE_LABEL[m.mapping_type] ?? m.mapping_type}
                      </td>
                      <td>
                        <div className="row-actions">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setEditing(m)
                              setError(null)
                              setEditName(m.pioneers_name_raw)
                              setEditCode(m.pioneers_code ?? '')
                            }}
                          >
                            اصلاح
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => {
                              if (
                                window.confirm(
                                  'این نگاشت حذف شود؟ این عمل قابل بازگشت نیست.',
                                )
                              ) {
                                deleteMutation.mutate(m.id)
                              }
                            }}
                          >
                            حذف
                          </Button>
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
              صفحه {pager.page} از {pager.pageCount}
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
        </>
      )}

      {editing ? (
        <Modal
          title="اصلاح نگاشت"
          onClose={() => setEditing(null)}
          actions={
            <>
              <Button
                disabled={!editName.trim() || updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
              >
                ذخیره
              </Button>
              <Button variant="secondary" onClick={() => setEditing(null)}>
                انصراف
              </Button>
            </>
          }
        >
          <p>
            محصول تأمین‌کننده: <strong>{editing.supplier_name_raw}</strong>
          </p>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div className="field">
            <label htmlFor="edit-name">نام پایونیرز</label>
            <input
              id="edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>
          <div className="field" style={{ marginTop: '0.75rem' }}>
            <label htmlFor="edit-code">کد پایونیرز (اختیاری)</label>
            <input
              id="edit-code"
              className="ltr"
              value={editCode}
              onChange={(e) => setEditCode(e.target.value)}
            />
          </div>
        </Modal>
      ) : null}
    </section>
  )
}
