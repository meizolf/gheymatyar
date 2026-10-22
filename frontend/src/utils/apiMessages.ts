/** Translate common backend detail strings into actionable Persian. */

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
    re: /no Pioneers product at row (\d+)/i,
    fa: (m) => `محصول پایونیرز در ردیف ${m[1]} یافت نشد.`,
  },
  {
    re: /no approved updates available for export/i,
    fa: 'هیچ به‌روزرسانی تأییدشده‌ای برای خروجی وجود ندارد. ابتدا موارد را تأیید یا شامل کنید.',
  },
  {
    re: /no exportable candidates|nothing to export/i,
    fa: 'هیچ ردیف قابل خروجی وجود ندارد. ابتدا موارد را تأیید یا شامل کنید.',
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
    re: /price basis: Pioneers price basis is not on the workbook and was not confirmed/i,
    fa: 'مبنای قیمت در فایل پایونیرز نیست و تأیید نشده است. خروجی مسدود است.',
  },
  {
    re: /price basis: supplier price basis is not an explicit per-metre or per-piece price/i,
    fa: 'مبنای قیمت تأمین‌کننده به‌صورت هر متر یا هر عدد مشخص نیست. خروجی تا تأیید واحد مسدود است.',
  },
  {
    re: /sale currency: Pioneers sale currency is not confirmed/i,
    fa: 'ارز نرخ فروش پایونیرز تأیید نشده است. هیچ تبدیلی انجام نمی‌شود و خروجی مسدود است.',
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
