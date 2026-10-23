import { describe, expect, it } from 'vitest'
import { translateApiDetail } from './apiMessages'

describe('translateApiDetail', () => {
  it('translates session expiry', () => {
    expect(translateApiDetail('session not found')).toMatch(/منقضی/)
  })

  it('translates positive and negative price threshold warnings', () => {
    expect(
      translateApiDetail('price change 70.21% exceeds 30% threshold'),
    ).toMatch(/تأیید هشدار/)
    expect(
      translateApiDetail('price change -45.50% exceeds 30% threshold'),
    ).toMatch(/-45\.50/)
  })

  it('translates zero previous price warning', () => {
    expect(
      translateApiDetail(
        'previous sale price was zero; percentage change undefined',
      ),
    ).toMatch(/صفر/)
  })

  it('translates export-empty message from backend', () => {
    expect(
      translateApiDetail('no approved updates available for export'),
    ).toMatch(/تأییدشده/)
  })

  it('translates sample PDF parse warnings', () => {
    expect(
      translateApiDetail(
        'PDF does not clearly identify as آذین لوله; parsing will still be attempted',
      ),
    ).toMatch(/هویت تأمین‌کننده/)
    expect(translateApiDetail('page 3: no table detected')).toMatch(/صفحه 3/)
    expect(
      translateApiDetail("page 4: unreadable price for code 819121025 ('—')"),
    ).toBe("صفحه 4: قیمت کد 819121025 خوانا نیست ('—').")
    expect(
      translateApiDetail('page 2: duplicate supplier code 123 skipped'),
    ).toMatch(/تکراری/)
    expect(
      translateApiDetail('page 1: missing category for code 456; row skipped'),
    ).toMatch(/دسته/)
  })

  it('translates common rejected-row reasons', () => {
    expect(translateApiDetail('required header not found in row 1')).toMatch(
      /سربرگ/,
    )
    expect(
      translateApiDetail('product-like row has empty نـــام کــالا'),
    ).toMatch(/خالی/)
  })

  it('translates packaged-app shutdown guidance', () => {
    expect(
      translateApiDetail(
        'shutdown is only available when launched via GheymatYar.exe or python -m gheymatyar',
      ),
    ).toMatch(/میانبر نصب‌شده/)
    expect(
      translateApiDetail('missing or invalid local control token'),
    ).toMatch(/توکن کنترل/)
  })

  it('translates persistent decision errors', () => {
    expect(
      translateApiDetail(
        'ignored supplier products must be restored before they can be included or approved',
      ),
    ).toMatch(/بازگردانی/)
    expect(
      translateApiDetail(
        'saved Pioneers mapping no longer identifies a single product in the current workbook; remap before this product can be included',
      ),
    ).toMatch(/نگاشت/)
    expect(
      translateApiDetail(
        'saved mapping has no supplier code or unit, so it cannot be applied to a specific variant; confirm this code and unit before it can be included',
      ),
    ).toMatch(/جداگانه/)
    expect(translateApiDetail('could not save the decision')).toMatch(/حفظ شده/)
  })

  it('passes through unknown details', () => {
    expect(translateApiDetail('weird custom error')).toBe('weird custom error')
  })
})
