import type { ReactNode } from 'react'

type Tone = 'error' | 'warning' | 'success' | 'info'

export function Alert({
  tone = 'info',
  children,
  role = 'alert',
}: {
  tone?: Tone
  children: ReactNode
  role?: string
}) {
  return (
    <div className={`alert alert-${tone}`} role={role}>
      {children}
    </div>
  )
}
