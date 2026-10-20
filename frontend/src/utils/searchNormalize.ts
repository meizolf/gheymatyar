/** Normalize Persian/Arabic letter variants and digits for client-side search. */

const ARABIC_YEH = /\u064A/g // ي
const ALEF_MAKSURA = /\u0649/g // ى (common in supplier PDFs)
const ARABIC_KAF = /\u0643/g // ك
const PERSIAN_YEH = '\u06CC' // ی
const PERSIAN_KEHEH = '\u06A9' // ک

const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
const LATIN_DIGITS = '0123456789'

function mapDigits(text: string): string {
  let out = ''
  for (const ch of text) {
    const a = ARABIC_DIGITS.indexOf(ch)
    if (a >= 0) {
      out += LATIN_DIGITS[a]
      continue
    }
    const p = PERSIAN_DIGITS.indexOf(ch)
    if (p >= 0) {
      out += LATIN_DIGITS[p]
      continue
    }
    out += ch
  }
  return out
}

export function normalizeSearchText(value: string): string {
  return mapDigits(
    value
      .replace(ARABIC_YEH, PERSIAN_YEH)
      .replace(ALEF_MAKSURA, PERSIAN_YEH)
      .replace(ARABIC_KAF, PERSIAN_KEHEH)
      .replace(/\u200c/g, ' ') // ZWNJ
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase(),
  )
}

export function matchesSearch(
  haystackParts: Array<string | null | undefined>,
  query: string,
): boolean {
  const q = normalizeSearchText(query)
  if (!q) return true
  const hay = normalizeSearchText(haystackParts.filter(Boolean).join(' '))
  return hay.includes(q)
}
