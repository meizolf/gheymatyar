import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { usePagedFilter } from './usePagedFilter'

describe('usePagedFilter large list', () => {
  it('paginates thousands of items without returning all at once', () => {
    const items = Array.from({ length: 6700 }, (_, i) => ({
      id: i,
      name: `محصول ${i}`,
    }))
    const { result } = renderHook(() =>
      usePagedFilter(items, (item, q) => item.name.includes(q), 50),
    )
    expect(result.current.totalCount).toBe(6700)
    expect(result.current.pageItems).toHaveLength(50)
    expect(result.current.pageCount).toBe(134)

    act(() => {
      result.current.setPage(2)
    })
    expect(result.current.pageItems[0].id).toBe(50)

    act(() => {
      result.current.setQuery('محصول 1234')
    })
    expect(result.current.filteredCount).toBeGreaterThan(0)
    expect(result.current.pageItems.length).toBeLessThanOrEqual(50)
  })
})
