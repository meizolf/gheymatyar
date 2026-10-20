import type { ReactNode } from 'react'

type Tone = 'ok' | 'warn' | 'danger' | 'neutral' | 'info'

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: Tone
  children: ReactNode
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}
