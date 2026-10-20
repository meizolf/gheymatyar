import type { WizardStep } from '../workflow/WorkflowContext'

const STEPS: { step: WizardStep; label: string }[] = [
  { step: 1, label: 'بارگذاری فایل‌ها' },
  { step: 2, label: 'تطابق محصولات' },
  { step: 3, label: 'پیش‌نمایش قیمت' },
  { step: 4, label: 'خروجی اکسل' },
]

export function StepNav({
  current,
  maxReachable,
  onGoto,
}: {
  current: WizardStep
  maxReachable: WizardStep
  onGoto: (step: WizardStep) => void
}) {
  return (
    <ol className="step-nav" aria-label="مراحل ویزارد">
      {STEPS.map(({ step, label }) => {
        const active = step === current
        const done = step < current
        const enabled = step <= maxReachable
        return (
          <li key={step} className={active ? 'is-active' : done ? 'is-done' : ''}>
            <button
              type="button"
              disabled={!enabled}
              onClick={() => onGoto(step)}
              aria-current={active ? 'step' : undefined}
            >
              <span className="step-num">{step}</span>
              <span className="step-label">{label}</span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
