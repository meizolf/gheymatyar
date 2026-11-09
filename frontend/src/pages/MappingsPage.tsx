import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { Mapping, MappingImportItem, MappingImportResponse } from '../api/types'
import { Alert } from '../components/ui/Alert'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Spinner } from '../components/ui/Spinner'
import { usePagedFilter } from '../hooks/usePagedFilter'
import { describeApiError } from '../utils/apiMessages'
import { MATCH_TYPE_LABEL } from '../utils/format'

function saveFile(blob: Blob, filename: string) {
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

function invalidReason(reason: string | null): string {
  if (!reason) return 'رکورد نامعتبر'
  if (/unknown supplier/i.test(reason)) return 'تأمین‌کننده ناشناخته'
  if (/required|no usable name/i.test(reason)) return 'نام کالا خالی است'
  if (/twice/i.test(reason)) return 'یک کالای تأمین‌کننده دو بار با مقصد متفاوت آمده است'
  return 'ساختار رکورد نامعتبر است'
}

function target(name: string | null, code: string | null): string {
  return code ? `«${name ?? ''}» (${code})` : `«${name ?? ''}»`
}

export function MappingsPage() {
  const queryClient = useQueryClient()
  const [supplierKey, setSupplierKey] = useState('')
  const [editing, setEditing] = useState<Mapping | null>(null)
  const [editName, setEditName] = useState('')
  const [editCode, setEditCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPlan, setImportPlan] = useState<MappingImportResponse | null>(null)
  const [replace, setReplace] = useState<Set<number>>(new Set())
  const [importMessage, setImportMessage] = useState<string | null>(null)

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

  const exportMutation = useMutation({
    mutationFn: api.exportMappings,
    onSuccess: ({ blob, filename }) => {
      setError(null)
      saveFile(blob, filename)
    },
    onError: (err) => setError(describeApiError(err, 'خطا در خروجی نگاشت‌ها')),
  })

  const previewMutation = useMutation({
    mutationFn: (file: File) => api.previewMappingImport(file),
    onSuccess: (plan, file) => {
      setError(null)
      setImportMessage(null)
      setImportFile(file)
      setReplace(new Set())
      setImportPlan(plan)
    },
    onError: (err) => setError(describeApiError(err, 'خطا در خواندن فایل نگاشت‌ها')),
  })

  const confirmMutation = useMutation({
    mutationFn: () => api.confirmMappingImport(importFile!, [...replace]),
    onSuccess: async (result) => {
      setImportPlan(null)
      setImportFile(null)
      setError(null)
      const { new: added, replace: replaced, identical, conflict, invalid } = result.counts
      setImportMessage(
        `ورود انجام شد: ${added} نگاشت جدید و ${replaced} جایگزینی ثبت شد؛ ` +
          `${identical} نگاشت یکسان، ${conflict} نگاشت متعارض و ${invalid} رکورد نامعتبر بدون تغییر ماند.`,
      )
      // Saved mappings change matching for every supplier and open session.
      await Promise.all(
        ['mappings', 'candidates', 'preview', 'session'].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      )
    },
    onError: (err) => setError(describeApiError(err, 'خطا در ورود نگاشت‌ها')),
  })

  const supplierName = (key: string | null) =>
    (suppliersQuery.data ?? []).find((s) => s.key === key)?.display_name ?? key ?? '—'

  const conflicts = importPlan?.items.filter((i) => i.status === 'conflict') ?? []
  const invalid = importPlan?.items.filter((i) => i.status === 'invalid') ?? []
  const toWrite = (importPlan?.counts.new ?? 0) + replace.size

  function conflictText(item: MappingImportItem): string {
    if (item.reason === 'target_taken') {
      return `کالای پایونیرز ${target(item.pioneers_name, item.pioneers_code)} در اختیار «${item.holder ?? ''}» است؛ وارد نمی‌شود.`
    }
    const here = `اینجا: ${target(item.existing_pioneers_name, item.existing_pioneers_code)}`
    const there = `فایل: ${target(item.pioneers_name, item.pioneers_code)}`
    const held = item.replaceable ? '' : ` — کالای فایل در اختیار «${item.holder ?? ''}» است.`
    return `${here}؛ ${there}${held}`
  }

  return (
    <section className="panel">
      <h1>نگاشت‌های ذخیره‌شده</h1>
      <p className="lede">
        نگاشت‌های نام تأییدشده برای هر تأمین‌کننده. در عملیات بعدی به‌صورت خودکار
        استفاده می‌شوند.
      </p>

      <div className="toolbar">
        <Button
          variant="secondary"
          disabled={exportMutation.isPending}
          onClick={() => exportMutation.mutate()}
        >
          خروجی نگاشت‌ها
        </Button>
        <Button
          variant="secondary"
          disabled={previewMutation.isPending || confirmMutation.isPending}
          onClick={() => fileInput.current?.click()}
        >
          ورود نگاشت‌ها
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          aria-label="فایل نگاشت‌ها"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) previewMutation.mutate(file)
          }}
        />
        <span className="field-hint">
          همهٔ نگاشت‌های همهٔ تأمین‌کننده‌ها در یک فایل JSON.
        </span>
      </div>

      {importMessage ? <Alert tone="success">{importMessage}</Alert> : null}

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

      {importPlan ? (
        <Modal
          title="پیش‌نمایش ورود نگاشت‌ها"
          onClose={() => setImportPlan(null)}
          actions={
            <>
              <Button
                disabled={toWrite === 0 || confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
              >
                {confirmMutation.isPending ? 'در حال ورود…' : 'تأیید ورود'}
              </Button>
              <Button variant="secondary" onClick={() => setImportPlan(null)}>
                انصراف
              </Button>
            </>
          }
        >
          <div className="chip-row">
            <span className="chip">
              نگاشت جدید: <strong>{importPlan.counts.new}</strong>
            </span>
            <span className="chip">
              نگاشت یکسان موجود: <strong>{importPlan.counts.identical}</strong>
            </span>
            <span className="chip">
              نگاشت متعارض: <strong>{importPlan.counts.conflict}</strong>
            </span>
            <span className="chip">
              رکورد نامعتبر: <strong>{importPlan.counts.invalid}</strong>
            </span>
          </div>
          <p className="field-hint">
            هیچ نگاشت موجودی بدون انتخاب شما جایگزین نمی‌شود. نگاشت‌های واردشده هنگام
            تطبیق دوباره با فایل پایونیرز بررسی می‌شوند و اگر کالای آن پیدا نشود، تا
            تأیید دوباره در خروجی قیمت استفاده نمی‌شوند.
          </p>
          {toWrite === 0 ? (
            <Alert tone="info">چیزی برای ورود وجود ندارد.</Alert>
          ) : null}
          {conflicts.length > 0 ? (
            <ul className="warn-list">
              {conflicts.map((item) => (
                <li key={item.index}>
                  <strong>
                    {supplierName(item.supplier_key)} — {item.supplier_name}
                  </strong>
                  <div>{conflictText(item)}</div>
                  {item.replaceable ? (
                    <label>
                      <input
                        type="checkbox"
                        checked={replace.has(item.index)}
                        onChange={(e) => {
                          const next = new Set(replace)
                          if (e.target.checked) next.add(item.index)
                          else next.delete(item.index)
                          setReplace(next)
                        }}
                      />{' '}
                      جایگزینی با نگاشت فایل
                    </label>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {invalid.length > 0 ? (
            <ul className="warn-list">
              {invalid.map((item) => (
                <li key={item.index}>
                  رکورد {item.index + 1}: {invalidReason(item.reason)}
                </li>
              ))}
            </ul>
          ) : null}
        </Modal>
      ) : null}

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
