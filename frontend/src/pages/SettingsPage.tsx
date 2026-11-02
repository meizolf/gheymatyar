import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'

const INCREASE_KEY = 'price_increase_warning_percent'
const DECREASE_KEY = 'price_decrease_warning_percent'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [increase, setIncrease] = useState('30')
  const [decrease, setDecrease] = useState('10')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  useEffect(() => {
    const stored = settingsQuery.data?.settings
    if (!stored) return
    if (stored[INCREASE_KEY]) setIncrease(stored[INCREASE_KEY])
    if (stored[DECREASE_KEY]) setDecrease(stored[DECREASE_KEY])
  }, [settingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateSettings({
        [INCREASE_KEY]: increase.trim(),
        [DECREASE_KEY]: decrease.trim(),
      }),
    // The server has already re-checked the open session; refetch so the
    // price review and export step show its new warnings and approvals.
    onSuccess: async () => {
      setMessage('تنظیمات ذخیره شد و روی بررسی قیمت فعلی اعمال شد.')
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
            <label htmlFor="increase-threshold">
              آستانه هشدار افزایش قیمت (درصد)
            </label>
            <input
              id="increase-threshold"
              inputMode="decimal"
              className="ltr"
              value={increase}
              onChange={(e) => setIncrease(e.target.value)}
              required
            />
          </div>
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="decrease-threshold">
              آستانه هشدار کاهش قیمت (درصد)
            </label>
            <input
              id="decrease-threshold"
              inputMode="decimal"
              className="ltr"
              value={decrease}
              onChange={(e) => setDecrease(e.target.value)}
              required
            />
            <p className="field-hint">
              افزایش بیش از آستانه افزایش یا کاهش بیش از آستانه کاهش نیاز به
              تأیید هشدار دارد؛ تغییرات تا خود آستانه خودکار تأیید می‌شوند. هر دو
              عدد مثبت‌اند (پیش‌فرض ۳۰ و ۱۰). ذخیره، همین حالا روی بررسی قیمت باز
              اعمال می‌شود. نرخ فروش اصلی پایونیرز همیشه ریال است و قیمت در متراژ
              یا تعداد بسته ضرب نمی‌شود.
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
