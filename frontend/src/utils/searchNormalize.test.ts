import { describe, expect, it } from 'vitest'
import { matchesSearch, normalizeSearchText } from './searchNormalize'

describe('normalizeSearchText', () => {
  it('unifies Arabic yeh/kaf with Persian forms', () => {
    expect(normalizeSearchText('پايپ')).toBe(normalizeSearchText('پایپ'))
    expect(normalizeSearchText('لكه')).toBe(normalizeSearchText('لکه'))
  })

  it('maps alef maksura (U+0649) used in supplier PDFs to Persian yeh', () => {
    // Exact sample failure: query دیواری vs PDF name دیوارى
    const query = 'دیواری' // ends with U+06CC
    const pdfName = 'دیوارى' // ends with U+0649
    expect(normalizeSearchText(query)).toBe(normalizeSearchText(pdfName))
    expect(matchesSearch([pdfName], query)).toBe(true)
    expect(matchesSearch([`لوله ${pdfName} سفید`], query)).toBe(true)
  })

  it('maps Persian and Arabic digits to Latin', () => {
    expect(normalizeSearchText('۱۲۳')).toBe('123')
    expect(normalizeSearchText('١٢٣')).toBe('123')
  })
})

describe('matchesSearch', () => {
  it('matches across digit scripts', () => {
    expect(matchesSearch(['کد ۱۲'], '12')).toBe(true)
    expect(matchesSearch(['کد 12'], '۱۲')).toBe(true)
  })
})
