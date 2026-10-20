import { describe, expect, it } from 'vitest'
import { formatFileSize, formatPercent, formatPrice, isExcelFile, isPdfFile } from './format'

describe('formatPrice', () => {
  it('formats numeric strings', () => {
    const formatted = formatPrice('1234567')
    expect(formatted).not.toBe('—')
    expect(formatted.length).toBeGreaterThan(3)
  })

  it('returns dash for empty', () => {
    expect(formatPrice(null)).toBe('—')
    expect(formatPrice('')).toBe('—')
  })
})

describe('formatPercent', () => {
  it('adds percent sign', () => {
    expect(formatPercent('12.5')).toContain('٪')
  })
})

describe('formatFileSize', () => {
  it('formats bytes', () => {
    expect(formatFileSize(500)).toContain('بایت')
    expect(formatFileSize(2048)).toContain('کیلوبایت')
  })
})

describe('file validators', () => {
  it('accepts xlsx and xls, rejects xlsm', () => {
    expect(isExcelFile(new File([], 'a.xlsx'))).toBe(true)
    expect(isExcelFile(new File([], 'a.xls'))).toBe(true)
    expect(isExcelFile(new File([], 'a.xlsm'))).toBe(false)
  })

  it('accepts pdf only', () => {
    expect(isPdfFile(new File([], 'a.pdf'))).toBe(true)
    expect(isPdfFile(new File([], 'a.xlsx'))).toBe(false)
  })
})
