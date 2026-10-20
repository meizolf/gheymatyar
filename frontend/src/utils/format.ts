/** Display helpers for prices, file sizes, and Persian labels. */

const faNumber = new Intl.NumberFormat('fa-IR')

export function formatPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const raw = String(value).replace(/,/g, '').trim()
  if (!raw) return '—'
  const num = Number(raw)
  if (Number.isNaN(num)) return String(value)
  return faNumber.format(num)
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = Number(String(value).replace(/%/g, '').trim())
  if (Number.isNaN(num)) return String(value)
  return `${faNumber.format(Math.round(num * 100) / 100)}٪`
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${faNumber.format(bytes)} بایت`
  if (bytes < 1024 * 1024) {
    return `${faNumber.format(Math.round((bytes / 1024) * 10) / 10)} کیلوبایت`
  }
  return `${faNumber.format(Math.round((bytes / (1024 * 1024)) * 100) / 100)} مگابایت`
}

export const MATCH_STATUS_LABEL: Record<string, string> = {
  MATCHED: 'متطابق',
  UNMATCHED: 'بدون تطابق',
  AMBIGUOUS: 'مبهم',
}

export const REVIEW_LABEL: Record<string, string> = {
  INCLUDE: 'شامل',
  EXCLUDE: 'حذف‌شده',
  APPROVE: 'تأیید هشدار',
}

export const MATCH_TYPE_LABEL: Record<string, string> = {
  SAVED_MAPPING: 'نگاشت ذخیره‌شده',
  EXACT_NAME: 'نام دقیق',
  MANUAL: 'دستی',
}

export function isExcelFile(file: File): boolean {
  const name = file.name.toLowerCase()
  if (name.endsWith('.xlsm')) return false
  return name.endsWith('.xlsx') || name.endsWith('.xls')
}

export function isPdfFile(file: File): boolean {
  return file.name.toLowerCase().endsWith('.pdf')
}
