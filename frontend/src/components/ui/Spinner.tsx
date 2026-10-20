export function Spinner({ label = 'در حال بارگذاری…' }: { label?: string }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <span className="spinner-dot" aria-hidden />
      <span>{label}</span>
    </div>
  )
}
