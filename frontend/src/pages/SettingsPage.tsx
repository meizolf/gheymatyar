import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'

const THRESHOLD_KEY = 'suspicious_percent_threshold'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState('30')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  useEffect(() => {
    if (settingsQuery.data?.settings[THRESHOLD_KEY]) {
      setThreshold(settingsQuery.data.settings[THRESHOLD_KEY])
    }
  }, [settingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateSettings({ [THRESHOLD_KEY]: threshold.trim() }),
    onSuccess: async () => {
      setMessage('تنظیمات ذخیره شد.')
      setError(null)
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
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
