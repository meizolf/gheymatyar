import { Alert } from '../components/ui/Alert'
import { Spinner } from '../components/ui/Spinner'
import { StepNav } from '../components/StepNav'
import { useWorkflow, type WizardStep } from '../workflow/WorkflowContext'
import { ExportStep } from './ExportStep'
import { ImportStep } from './ImportStep'
import { MatchingStep } from './MatchingStep'
import { PreviewStep } from './PreviewStep'

function computeMaxReachable(
  step: WizardStep,
  matchedDone: boolean,
  hasUploads: boolean,
  exportInFlight: boolean,
  pendingOps: number,
): WizardStep {
  if (exportInFlight || pendingOps > 0) {
    // Allow staying on current/export while ops run, but not jumping ahead of pending work.
    return Math.max(step, 1) as WizardStep
  }
  if (!hasUploads) return 1
  if (!matchedDone && step <= 1) return 1
  return Math.max(step, matchedDone ? 4 : 1) as WizardStep
}

export function WizardPage() {
  const {
    step,
    setStep,
    summary,
    matchedDone,
    restoring,
    exportInFlight,
    pendingSessionOps,
  } = useWorkflow()

  if (restoring) {
    return (
      <div className="wizard">
        <Spinner label="در حال بازیابی جلسه قبلی…" />
      </div>
    )
  }

  const hasUploads = Boolean(
    summary?.pioneers_filename && (summary.supplier_item_count ?? 0) > 0,
  )
  const maxReachable = computeMaxReachable(
    step,
    matchedDone,
    hasUploads,
    exportInFlight,
    pendingSessionOps,
  )

  function handleGoto(next: WizardStep) {
    if (exportInFlight && next !== 4) {
      return
    }
    if (pendingSessionOps > 0 && next > step) {
      return
    }
    setStep(next)
  }

  return (
    <div className="wizard">
      {exportInFlight ? (
        <Alert tone="info">در حال تولید خروجی… لطفاً صفحه را نبندید.</Alert>
      ) : null}
      <StepNav
        current={step}
        maxReachable={maxReachable}
        onGoto={handleGoto}
      />
      {step === 1 ? <ImportStep /> : null}
      {step === 2 ? <MatchingStep /> : null}
      {step === 3 ? <PreviewStep /> : null}
      {step === 4 ? <ExportStep /> : null}
    </div>
  )
}
