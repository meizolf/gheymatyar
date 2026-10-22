import { useEffect, useState } from 'react'

/** Minimum engines documented for the offline Windows installer UI. */
const MESSAGE =
  'برای استفادهٔ آفلاین قیمت‌یار یکی از مرورگرهای Edge 111+، Chrome 111+ یا Firefox 114+ لازم است (هم‌تراز با باندل Vite). برنامه مرورگر را دانلود نمی‌کند.'

function isSupportedBrowser(): boolean {
  if (typeof window === 'undefined') return true
  // React 19 + Vite build need ES2020-class engines. Detect obvious legacy UAs.
  const ua = navigator.userAgent
  const msie = /MSIE |Trident\//.test(ua)
  if (msie) return false
  // Very old EdgeHTML
  if (/Edge\/\d+/.test(ua) && !/Edg\//.test(ua)) return false
  try {
    // Features exercised by the production bundle.
    return (
      typeof fetch === 'function' &&
      typeof Promise !== 'undefined' &&
      typeof globalThis !== 'undefined' &&
      typeof CSS !== 'undefined' &&
      typeof CSS.supports === 'function'
    )
  } catch {
    return false
  }
}

export function BrowserCompatBanner() {
  const [show, setShow] = useState(false)
  useEffect(() => {
    setShow(!isSupportedBrowser())
  }, [])
  if (!show) return null
  return (
    <p className="exit-banner" role="alert">
      {MESSAGE}
    </p>
  )
}
