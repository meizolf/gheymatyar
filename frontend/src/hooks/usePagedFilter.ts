import { useMemo, useState } from 'react'

export function usePagedFilter<T>(
  items: T[],
  predicate: (item: T, query: string) => boolean,
  pageSize = 50,
) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)

  const filtered = useMemo(() => {
    const q = query.trim()
    if (!q) return items
    return items.filter((item) => predicate(item, q))
  }, [items, query, predicate])

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, pageCount)
  const pageItems = filtered.slice(
    (safePage - 1) * pageSize,
    safePage * pageSize,
  )

  return {
    query,
    setQuery: (value: string) => {
      setQuery(value)
      setPage(1)
    },
    page: safePage,
    setPage,
    pageCount,
    pageItems,
    filteredCount: filtered.length,
    totalCount: items.length,
  }
}
