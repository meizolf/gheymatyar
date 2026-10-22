import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'
import { translateApiDetail } from '../utils/apiMessages'
import { isApiError } from '../api/errors'
import { useWorkflow } from '../workflow/WorkflowContext'
import { BrowserCompatBanner } from './BrowserCompatBanner'
import { Button } from './ui/Button'

export function Layout() {
  const { exportInFlight, pendingSessionOps } = useWorkflow()
  const [exitError, setExitError] = useState<string | null>(null)
  const [exiting, setExiting] = useState(false)

  async function handleExit() {
    if (exportInFlight || pendingSessionOps > 0) {
      setExitError('تا پایان عملیات جاری صبر کنید، سپس خارج شوید.')
      return
    }
    if (
      !window.confirm(
        'سرور محلی قیمت‌یار متوقف شود و برنامه بسته شود؟',
      )
    ) {
      return
    }
    setExiting(true)
    setExitError(null)
    try {
      const health = await api.health()
      if (health.app !== 'gheymatyar' || !health.control_token) {
        throw new Error('پاسخ سلامت سرور نامعتبر است.')
      }
      await api.shutdown(health.control_token)
      setExitError(
        'سرور در حال توقف است. این پنجره مرورگر را می‌توانید ببندید.',
      )
    } catch (err) {
      setExitError(
        translateApiDetail(
          isApiError(err)
            ? err.detail
            : 'خروج فقط وقتی در دسترس است که برنامه از میانبر نصب‌شده (GheymatYar) اجرا شده باشد.',
        ),
      )
    } finally {
      setExiting(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-name">قیمت‌یار</span>
          <span className="brand-sub">به‌روزرسانی نرخ فروش پایونیرز</span>
        </div>
        <nav className="app-nav" aria-label="منوی اصلی">
          <NavLink to="/" end>
            ویزارد
          </NavLink>
          <NavLink to="/mappings">نگاشت‌های ذخیره‌شده</NavLink>
          <NavLink to="/settings">تنظیمات</NavLink>
          <Button
            size="sm"
            variant="secondary"
            className="exit-btn"
            disabled={exiting || exportInFlight}
            onClick={() => void handleExit()}
          >
            {exiting ? 'در حال خروج…' : 'خروج از برنامه'}
          </Button>
        </nav>
      </header>
      <main className="app-main">
        <BrowserCompatBanner />
        {exitError ? (
          <p className="exit-banner" role="status">
            {exitError}
          </p>
        ) : null}
        <Outlet />
      </main>
      <footer className="app-footer">
        فقط روی این رایانه — بدون دسترسی شبکه عمومی
      </footer>
    </div>
  )
}
