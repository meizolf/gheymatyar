import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'

const THRESHOLD_KEY = 'suspicious_percent_threshold'
const CURRENCY_KEY = 'pioneers_sale_currency'
const BASIS_KEY = 'pioneers_sale_basis'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState('30')
  const [saleCurrency, setSaleCurrency] = useState('')
  const [saleBasis, setSaleBasis] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  useEffect(() => {
    const stored = settingsQuery.data?.settings
    if (!stored) return
    if (stored[THRESHOLD_KEY]) setThreshold(stored[THRESHOLD_KEY])
    setSaleCurrency(stored[CURRENCY_KEY] ?? '')
    setSaleBasis(stored[BASIS_KEY] ?? '')
  }, [settingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateSettings({
        [THRESHOLD_KEY]: threshold.trim(),
        [CURRENCY_KEY]: saleCurrency,
        [BASIS_KEY]: saleBasis,
      }),
    onSuccess: async () => {
      setMessage('تنظیمات ذخیره شد.')
      setError(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['settings'] }),
        queryClient.invalidateQueries({ queryKey: ['preview'] }),
        queryClient.invalidateQueries({ queryKey: ['candidates'] }),
        queryClient.invalidateQueries({ queryKey: ['session'] }),
      ])
    },
    onError: (err) => {
      setMessage(null)
      setError(isApiError(err) ? err.detail : 'خطا در ذخیره')
    },
  })

  return (
    <section className="panel">
      <h1>تنظیمات</h1>
      <p className="lede">
        آستانه‌ها و پیکربندی‌هایی که سرور در اختیار می‌گذارد. محاسبات قیمت در
        فرانت‌اند انجام نمی‌شود.
      </p>

      {settingsQuery.isLoading ? <Spinner /> : null}
      {settingsQuery.isError ? (
        <Alert tone="error">
          {isApiError(settingsQuery.error)
            ? settingsQuery.error.detail
            : 'خطا در دریافت تنظیمات'}
        </Alert>
      ) : null}

      {settingsQuery.data ? (
        <form
          className="settings-form"
          onSubmit={(e) => {
            e.preventDefault()
            saveMutation.mutate()
          }}
        >
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="threshold">
              آستانه هشدار تغییر قیمت (درصد)
            </label>
            <input
              id="threshold"
              inputMode="decimal"
              className="ltr"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              required
            />
            <p className="field-hint">
              تغییرات مطلق بیش از این درصد نیاز به تأیید صریح دارند. مقدار پیش‌فرض
              سرور: ۳۰
            </p>
          </div>
          <div className="field" style={{ maxWidth: 420 }}>
            <label htmlFor="sale-currency">ارز نرخ فروش اصلی</label>
            <select
              id="sale-currency"
              value={saleCurrency}
              onChange={(e) => setSaleCurrency(e.target.value)}
            >
              <option value="">تأیید نشده</option>
              <option value="rial">ریال</option>
            </select>
            <p className="field-hint">
              نرخ فروش اصلی پایونیرز به‌صورت تأییدشده ریالی است (پیش‌فرض). انتخاب
              «تأیید نشده» خروجی را مسدود می‌کند. تبدیل تومان→ریال فقط در
              پردازنده تأمین‌کننده‌ای مثل تاپ (×۱۰) انجام می‌شود.
            </p>
          </div>
          <div className="field" style={{ maxWidth: 420 }}>
            <label htmlFor="sale-basis">مبنای نرخ فروش وقتی واحد در اکسل نیست</label>
            <select
              id="sale-basis"
              value={saleBasis}
              onChange={(e) => setSaleBasis(e.target.value)}
            >
              <option value="">تأیید نشده</option>
              <option value="meter">هر متر</option>
              <option value="piece">هر عدد</option>
            </select>
            <p className="field-hint">
              اگر خود ردیف واحد داشته باشد، همان واحد ملاک است. قیمت هر متر روی
              شاخه نوشته نمی‌شود و متراژ/کارتن در قیمت ضرب نمی‌شود. مبالغ چاپی
              تأییدشدهٔ آذین، نیوپایپ و آبراهان بدون نیاز به این مبنا خروجی
              می‌شوند. تغییر یا پاک کردن ارز یا مبنا، نشست‌های باز را دوباره
              بررسی می‌کند و فایل اکسل ساخته‌شده را باطل می‌کند.
            </p>
          </div>

          {error ? <Alert tone="error">{error}</Alert> : null}
          {message ? <Alert tone="success">{message}</Alert> : null}

          <div className="step-actions">
            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'در حال ذخیره…' : 'ذخیره'}
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  )
}
