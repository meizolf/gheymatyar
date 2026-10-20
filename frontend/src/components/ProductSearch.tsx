import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { translateApiDetail } from '../utils/apiMessages'
import { Alert } from './ui/Alert'
import { Button } from './ui/Button'
import { Spinner } from './ui/Spinner'

export function ProductSearch({
  sessionId,
  onSelect,
}: {
  sessionId: string
  onSelect: (rowNumber: number, label: string) => void
}) {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')

  const search = useQuery({
    queryKey: ['product-search', sessionId, submitted],
    queryFn: () => api.searchProducts(sessionId, submitted),
    enabled: submitted.length >= 1,
    retry: 1,
  })

  return (
    <div className="product-search">
      <div className="search-row">
        <input
          type="search"
          value={query}
          placeholder="جستجوی نام یا کد محصول پایونیرز…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && query.trim()) {
              setSubmitted(query.trim())
            }
          }}
          aria-label="جستجوی محصول پایونیرز"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!query.trim() || search.isFetching}
          onClick={() => setSubmitted(query.trim())}
        >
          جستجو
        </Button>
      </div>
      {search.isFetching ? <Spinner label="در حال جستجو…" /> : null}
      {search.isError ? (
        <Alert tone="error">
          {translateApiDetail(
            isApiError(search.error) ? search.error.detail : undefined,
          )}
          <div className="step-actions">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void search.refetch()}
            >
              تلاش مجدد
            </Button>
          </div>
        </Alert>
      ) : null}
      {search.data && search.data.results.length === 0 && !search.isFetching ? (
        <p className="field-hint">نتیجه‌ای یافت نشد.</p>
      ) : null}
      {search.data && search.data.results.length > 0 ? (
        <ul className="search-results">
          {search.data.results.map((r) => {
            const name = String(r.name ?? r.pioneers_name ?? '')
            const code = String(r.code ?? r.pioneers_code ?? '')
            const label = code ? `${name} (${code})` : name
            return (
              <li key={`${r.row_number}-${code}-${name}`}>
                <button
                  type="button"
                  onClick={() => onSelect(r.row_number, label)}
                >
                  <span>{name || '—'}</span>
                  {code ? <span className="ltr meta">{code}</span> : null}
                  <span className="meta">ردیف {r.row_number}</span>
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}
