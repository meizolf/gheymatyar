/** Translate common backend detail strings into actionable Persian. */

import { isApiError } from '../api/errors'

const PATTERNS: Array<{ re: RegExp; fa: string | ((m: RegExpMatchArray) => string) }> = [
  {
    re: /session not found/i,
    fa: 'جلسه منقضی شده — لطفاً دوباره فایل‌ها را بارگذاری کنید.',
  },
  {
    re: /expected an \.xlsx or \.xls/i,
    fa: 'فقط فایل اکسل با پسوند .xlsx یا .xls پذیرفته می‌شود (.xlsm مجاز نیست).',
  },
  {
    re: /expected an \.xlsx/i,
    fa: 'فقط فایل اکسل با پسوند .xlsx یا .xls پذیرفته می‌شود (.xlsm مجاز نیست).',
  },
  {
    re: /unsupported Excel format|Not a Pioneers HTML|binary Excel \.xls/i,
    fa: 'فرمت فایل اکسل پشتیبانی نمی‌شود. فایل .xlsx یا خروجی HTML پایونیرز با پسوند .xls ارسال کنید.',
  },
  {
    re: /expected a \.pdf/i,
    fa: 'فقط فایل PDF پذیرفته می‌شود.',
  },
  {
    re: /Unsupported supplier/i,
    fa: 'این تأمین‌کننده پشتیبانی نمی‌شود. از فهرست پشتیبانی‌شده انتخاب کنید.',
  },
  {
    re: /Pioneers Excel has not been uploaded/i,
    fa: 'ابتدا فایل اکسل پایونیرز را بارگذاری کنید.',
  },
  {
    re: /Supplier PDF has not been uploaded/i,
    fa: 'ابتدا فایل PDF تأمین‌کننده را بارگذاری کنید.',
  },
  {
    re: /Supplier has not been confirmed/i,
    fa: 'ابتدا شرکت تأمین‌کننده شناسایی‌شده را تأیید کنید.',
  },
  {
    re: /detect a PDF first/i,
    fa: 'ابتدا فایل PDF را بارگذاری کنید تا شرکت شناسایی شود.',
  },
  {
    re: /no Pioneers product at row (\d+)/i,
    fa: (m) => `محصول پایونیرز در ردیف ${m[1]} یافت نشد.`,
  },
  {
    re: /Approved product «(.+?)» has no product code/i,
    fa: (m) =>
      `کالای «${m[1]}» در پایونیرز کد کالا ندارد و پایونیرز قیمت را با کد کالا به‌روز می‌کند. کد کالا را در پایونیرز ثبت کنید یا این کالا را از خروجی حذف کنید.`,
  },
  {
    re: /Pioneers product (.+?) is already mapped to supplier product «(.+?)»/i,
    fa: (m) =>
      `این کالای پایونیرز (${m[1]}) قبلاً به کالای «${m[2]}» نگاشت شده است. ابتدا نگاشت قبلی را اصلاح یا حذف کنید.`,
  },
  {
    re: /Pioneers product is already matched to another supplier product/i,
    fa: 'این کالای پایونیرز به کالای دیگری از همین تأمین‌کننده هم نگاشت شده است. یکی از دو نگاشت را اصلاح یا حذف کنید.',
  },
  {
    re: /no approved updates available for export/i,
    fa: 'هیچ به‌روزرسانی تأییدشده‌ای برای خروجی وجود ندارد. ابتدا قیمت‌های تغییرکرده را تأیید کنید.',
  },
  {
    re: /conflicting final sale prices for the same Pioneers product/i,
    fa: 'چند قیمت متفاوت برای یک کالای پایونیرز تأیید شده است. تا رفع تعارض، خروجی ساخته نمی‌شود.',
  },
  {
    re: /selected Pioneers product cannot be identified uniquely/i,
    fa: 'کالای انتخاب‌شده در فایل پایونیرز یکتا نیست. خروجی ساخته نمی‌شود.',
  },
  {
    re: /exported product row count does not match/i,
    fa: 'تعداد ردیف‌های فایل خروجی با انتخاب تأییدشده یکی نیست.',
  },
  {
    re: /no exportable candidates|nothing to export/i,
    fa: 'هیچ ردیف قابل خروجی وجود ندارد. ابتدا موارد را تأیید کنید.',
  },
  {
    re: /export not available/i,
    fa: 'خروجی آماده نیست؛ ابتدا تولید اکسل را اجرا کنید.',
  },
  {
    re: /decision must be INCLUDE, EXCLUDE, or APPROVE/i,
    fa: 'تصمیم نامعتبر است. یکی از گزینه‌های شامل، حذف یا تأیید هشدار را انتخاب کنید.',
  },
  {
    re: /only matched candidates can be included or approved/i,
    fa: 'فقط محصولات متطابق را می‌توان شامل یا تأیید کرد.',
  },
  {
    re: /cannot approve a candidate with a duplicate Pioneers product code/i,
    fa: 'به‌خاطر کد تکراری پایونیرز نمی‌توان این مورد را تأیید کرد.',
  },
  {
    re: /cannot approve a candidate while a supplier price restriction is unresolved/i,
    fa: 'این محدودیت قیمت قابل تأیید نیست و خروجی خودکار مسدود می‌ماند.',
  },
  {
    re: /price basis: supplier price is per metre and the Pioneers unit is (.+); no conversion was applied/i,
    fa: (m) =>
      `قیمت تأمین‌کننده برای هر متر است و واحد پایونیرز ${m[1]} است. تبدیلی انجام نشده و خروجی مسدود است.`,
  },
  {
    re: /price basis: supplier price is per piece and the Pioneers unit is (.+); no conversion was applied/i,
    fa: (m) =>
      `قیمت تأمین‌کننده برای هر عدد است و واحد پایونیرز ${m[1]} است. تبدیلی انجام نشده و خروجی مسدود است.`,
  },
  {
    re: /price basis: Pioneers unit is not a recognised metre, piece, or branch/i,
    fa: 'واحد پایونیرز متر، عدد یا شاخه نیست. تبدیلی انجام نشده و خروجی مسدود است.',
  },
  {
    re: /price basis: supplier price basis is not an explicit per-metre or per-piece price/i,
    fa: 'مبنای قیمت تأمین‌کننده به‌صورت هر متر یا هر عدد مشخص نیست. خروجی تا تأیید واحد مسدود است.',
  },
  {
    re: /sale currency: supplier currency was not stated/i,
    fa: 'ارز قیمت تأمین‌کننده در سند نیامده است. خروجی مسدود است.',
  },
  {
    re: /sale currency: supplier currency (\S+) does not match confirmed Pioneers currency (\S+)/i,
    fa: (m) =>
      `ارز تأمین‌کننده (${m[1]}) با ارز تأییدشده پایونیرز (${m[2]}) یکی نیست. تبدیلی انجام نشده و خروجی مسدود است.`,
  },
  {
    re: /mapping not found/i,
    fa: 'نگاشت یافت نشد.',
  },
  {
    re: /ignored supplier products must be restored/i,
    fa: 'این محصول حذف شده است. ابتدا آن را از تب حذف‌شده بازگردانی کنید.',
  },
  {
    re: /saved Pioneers mapping no longer identifies a single product/i,
    fa: 'محصول پایونیرزِ این نگاشت در فایل فعلی یکتا نیست یا وجود ندارد. قبل از ادامه باید دوباره نگاشت شود.',
  },
  {
    re: /saved mapping has no supplier code or unit/i,
    fa: 'این نگاشت کد یا واحد تأمین‌کننده ندارد و به یک نوع مشخص وصل نمی‌شود. این کد و واحد را جداگانه تأیید کنید.',
  },
  {
    re: /could not save the decision/i,
    fa: 'ذخیرهٔ تصمیم انجام نشد. وضعیت قبلی حفظ شده است.',
  },
  {
    re: /price change (-?[\d.]+)% exceeds ([\d.]+)% threshold/i,
    fa: (m) =>
      `تغییر قیمت ${m[1]}٪ از آستانه ${m[2]}٪ بیشتر است و نیاز به تأیید هشدار دارد.`,
  },
  {
    re: /previous sale price was zero; percentage change undefined/i,
    fa: 'قیمت قبلی صفر بوده است؛ درصد تغییر قابل محاسبه نیست و نیاز به بررسی دارد.',
  },
  {
    re: /final sale price must be greater than zero/i,
    fa: 'قیمت فروش نهایی باید بزرگ‌تر از صفر باشد.',
  },
  {
    re: /duplicate Pioneers product code; cannot export until uniqueness is resolved/i,
    fa: 'کد محصول پایونیرز تکراری است؛ تا رفع یکتایی نمی‌توان خروجی گرفت.',
  },
  {
    re: /identity conflict/i,
    fa: 'تعارض هویت ردیف — این به‌روزرسانی مسدود است.',
  },
  {
    re: /normalized name matches (\d+) Pioneers products/i,
    fa: (m) =>
      `نام نرمال‌شده با ${m[1]} محصول پایونیرز هم‌خوان است — تطابق دستی لازم است.`,
  },
  {
    re: /PDF does not clearly identify as/i,
    fa: 'هویت تأمین‌کننده در PDF واضح نیست؛ تلاش برای استخراج ادامه می‌یابد.',
  },
  {
    re: /page (\d+): no table detected/i,
    fa: (m) => `صفحه ${m[1]}: جدولی تشخیص داده نشد.`,
  },
  {
    re: /page (\d+): unreadable price for code (\S+)(?:\s+\((.+)\))?/i,
    fa: (m) =>
      `صفحه ${m[1]}: قیمت کد ${m[2]} خوانا نیست` +
      (m[3] ? ` (${m[3]})` : '') +
      '.',
  },
  {
    re: /page (\d+): duplicate supplier code (\S+) skipped/i,
    fa: (m) => `صفحه ${m[1]}: کد تأمین‌کننده تکراری ${m[2]} نادیده گرفته شد.`,
  },
  {
    re: /page (\d+): missing category for code (\S+); row skipped/i,
    fa: (m) =>
      `صفحه ${m[1]}: دسته برای کد ${m[2]} مشخص نیست؛ ردیف نادیده گرفته شد.`,
  },
  {
    re: /No priced products could be extracted/i,
    fa: 'هیچ محصول قیمت‌داری از PDF استخراج نشد. ساختار لیست قیمت پشتیبانی نمی‌شود یا خالی است.',
  },
  {
    re: /failed to read .+ PDF/i,
    fa: 'خواندن فایل PDF ناموفق بود.',
  },
  {
    re: /PDF has no pages/i,
    fa: 'فایل PDF صفحه‌ای ندارد.',
  },
  {
    re: /PDF not found/i,
    fa: 'فایل PDF یافت نشد.',
  },
  {
    re: /required header not found/i,
    fa: 'ستون الزامی در ردیف سربرگ اکسل یافت نشد.',
  },
  {
    re: /product-like row has empty/i,
    fa: 'ردیف شبیه محصول است ولی نام کالا خالی است.',
  },
  {
    re: /numeric cell has no zero-pad number format/i,
    fa: 'عدد بدون قالب حفظ صفرهای ابتدایی است؛ برای حفظ صفرها به‌صورت متن ذخیره کنید.',
  },
  {
    re: /boolean is not a valid/i,
    fa: 'مقدار بولی برای این فیلد معتبر نیست.',
  },
  {
    re: /formula(?:\/error)? cells? (?:are not supported|cannot be used)/i,
    fa: 'سلول فرمول/خطا برای این فیلد پشتیبانی نمی‌شود.',
  },
  {
    re: /cannot parse price text/i,
    fa: 'متن قیمت قابل تجزیه نیست.',
  },
  {
    re: /unsupported price type/i,
    fa: 'نوع داده قیمت پشتیبانی نمی‌شود.',
  },
  {
    re: /path does not exist or is not a file/i,
    fa: 'مسیر فایل وجود ندارد یا فایل نیست.',
  },
  {
    re: /unknown setting key/i,
    fa: 'کلید تنظیمات ناشناخته است.',
  },
  {
    re: /empty value for/i,
    fa: 'مقدار تنظیمات نباید خالی باشد.',
  },
  {
    re: /suspicious_percent_threshold must be/i,
    fa: 'آستانه هشدار تغییر قیمت باید یک عدد مثبت معتبر باشد.',
  },
  {
    re: /supplier is not set on this session/i,
    fa: 'تأمین‌کننده برای این جلسه تنظیم نشده است.',
  },
  {
    re: /candidate has no new price/i,
    fa: 'این مورد قیمت جدید ندارد.',
  },
  {
    re: /shutdown is only available when launched via/i,
    fa: 'خروج فقط وقتی در دسترس است که برنامه از میانبر نصب‌شده (GheymatYar) اجرا شده باشد.',
  },
  {
    re: /shutdown only allowed from localhost|API only allowed from localhost/i,
    fa: 'دسترسی API فقط از همین رایانه مجاز است.',
  },
  {
    re: /missing or invalid local control token/i,
    fa: 'توکن کنترل محلی نامعتبر است. صفحه را تازه کنید و دوباره خارج شوید.',
  },
  {
    re: /cross-origin (?:control|API) requests are not allowed/i,
    fa: 'درخواست از مبدأ غیرمجاز مسدود شد.',
  },
  {
    re: /invalid Host header for local (?:control|API) request/i,
    fa: 'هدر Host نامعتبر است؛ دسترسی فقط از سرور محلی مجاز است.',
  },
]

export function translateApiDetail(detail: string | null | undefined): string {
  if (!detail) return 'خطای ناشناخته از سرور'
  for (const { re, fa } of PATTERNS) {
    const m = detail.match(re)
    if (m) return typeof fa === 'function' ? fa(m) : fa
  }
  return detail
}

type DuplicateConflict = { supplier_name?: unknown }

/**
 * Persian text for an API error. A 409 duplicate-mapping conflict names the
 * Pioneers product and the supplier product that already holds it.
 */
export function describeApiError(error: unknown, fallback: string): string {
  if (isApiError(error)) {
    const data = error.data
    if (data && data.code === 'duplicate_mapping_target') {
      const code = typeof data.pioneers_code === 'string' ? data.pioneers_code : ''
      const name = typeof data.pioneers_name === 'string' ? data.pioneers_name : ''
      const holders = Array.isArray(data.conflicts)
        ? (data.conflicts as DuplicateConflict[])
            .map((c) => (typeof c.supplier_name === 'string' ? c.supplier_name : ''))
            .filter(Boolean)
        : []
      const product = [code, name].filter(Boolean).join(' — ')
      const held = holders.map((h) => `«${h}»`).join('، ')
      return `این کالای پایونیرز (${product}) قبلاً به کالای ${held} نگاشت شده است. ابتدا نگاشت قبلی را اصلاح یا حذف کنید.`
    }
    return translateApiDetail(error.detail)
  }
  return fallback
}
