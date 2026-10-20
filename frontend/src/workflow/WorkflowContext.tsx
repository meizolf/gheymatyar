import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { api } from '../api/client'
import { isApiError } from '../api/errors'
import type { SessionSummary } from '../api/types'
import { translateApiDetail } from '../utils/apiMessages'
import {
  getPendingSessionOps,
  subscribeSessionOps,
} from './sessionQueue'

const SESSION_KEY = 'gheymatyar.sessionId'
const STEP_KEY = 'gheymatyar.wizardStep'

export type WizardStep = 1 | 2 | 3 | 4

interface WorkflowState {
  sessionId: string | null
  step: WizardStep
  summary: SessionSummary | null
  matchedDone: boolean
  restoring: boolean
  restoreError: string | null
  exportInFlight: boolean
  pendingSessionOps: number
  setSessionId: (id: string | null) => void
  setStep: (step: WizardStep) => void
  setSummary: (summary: SessionSummary | null) => void
  setMatchedDone: (done: boolean) => void
  setExportInFlight: (value: boolean) => void
  /** Shared session creation — concurrent callers share one POST. */
  ensureSession: () => Promise<string>
  /** Inputs changed: clear match completion and retreat if needed. */
  invalidateDownstream: () => void
  reset: () => void
  clearRestoreError: () => void
}

const WorkflowContext = createContext<WorkflowState | null>(null)

function readStoredSession(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function readStoredStep(): WizardStep {
  try {
    const raw = sessionStorage.getItem(STEP_KEY)
    const n = Number(raw)
    if (n === 1 || n === 2 || n === 3 || n === 4) return n
  } catch {
    /* ignore */
  }
  return 1
}

function inferStepFromSummary(summary: SessionSummary, stored: WizardStep): WizardStep {
  const hasExcel = Boolean(summary.pioneers_filename && summary.product_count > 0)
  const hasPdf = Boolean(summary.pdf_filename && summary.supplier_item_count > 0)
  const hasMatch =
    summary.matched_count + summary.unmatched_count + summary.ambiguous_count > 0
  if (!hasExcel && !hasPdf) return 1
  if (!hasMatch) return 1
  // Prefer stored step when still reachable
  if (stored >= 2 && stored <= 4) return stored
  return 2
}

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionIdState] = useState<string | null>(readStoredSession)
  const [step, setStepState] = useState<WizardStep>(readStoredStep)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [matchedDone, setMatchedDone] = useState(false)
  const [restoring, setRestoring] = useState(() => Boolean(readStoredSession()))
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [exportInFlight, setExportInFlight] = useState(false)
  const sessionCreateRef = useRef<Promise<string> | null>(null)

  const pendingSessionOps = useSyncExternalStore(
    subscribeSessionOps,
    getPendingSessionOps,
    () => 0,
  )

  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id)
    try {
      if (id) sessionStorage.setItem(SESSION_KEY, id)
      else sessionStorage.removeItem(SESSION_KEY)
    } catch {
      /* ignore */
    }
  }, [])

  const setStep = useCallback((next: WizardStep) => {
    setStepState(next)
    try {
      sessionStorage.setItem(STEP_KEY, String(next))
    } catch {
      /* ignore */
    }
  }, [])

  const invalidateDownstream = useCallback(() => {
    setMatchedDone(false)
    setStepState((current) => {
      const next: WizardStep = current > 1 ? 1 : current
      try {
        sessionStorage.setItem(STEP_KEY, String(next))
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  const reset = useCallback(() => {
    sessionCreateRef.current = null
    setSessionId(null)
    setStep(1)
    setSummary(null)
    setMatchedDone(false)
    setExportInFlight(false)
    setRestoreError(null)
    setRestoring(false)
    try {
      sessionStorage.removeItem(STEP_KEY)
    } catch {
      /* ignore */
    }
  }, [setSessionId, setStep])

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId
    if (sessionCreateRef.current) return sessionCreateRef.current
    const pending = api.createSession().then((created) => {
      setSessionId(created.session_id)
      return created.session_id
    })
    sessionCreateRef.current = pending
    try {
      return await pending
    } finally {
      sessionCreateRef.current = null
    }
  }, [sessionId, setSessionId])

  // Intentionally no "already restored" ref: React StrictMode remounts and
  // cancels the first effect; the second must be allowed to run to completion.
  useEffect(() => {
    const sid = readStoredSession()
    if (!sid) {
      setRestoring(false)
      return
    }
    let cancelled = false
    setRestoring(true)
    ;(async () => {
      try {
        const data = await api.getSession(sid)
        if (cancelled) return
        setSessionId(sid)
        setSummary(data)
        const hasMatch =
          data.matched_count + data.unmatched_count + data.ambiguous_count > 0
        setMatchedDone(hasMatch)
        setStep(inferStepFromSummary(data, readStoredStep()))
        setRestoreError(null)
      } catch (err) {
        if (cancelled) return
        try {
          sessionStorage.removeItem(SESSION_KEY)
          sessionStorage.removeItem(STEP_KEY)
        } catch {
          /* ignore */
        }
        setSessionIdState(null)
        setSummary(null)
        setMatchedDone(false)
        setStepState(1)
        setRestoreError(
          isApiError(err) && err.sessionExpired
            ? 'جلسه قبلی منقضی شده است (مثلاً پس از راه‌اندازی مجدد سرور). لطفاً فایل‌ها را دوباره بارگذاری کنید.'
            : translateApiDetail(isApiError(err) ? err.detail : 'خطا در بازیابی جلسه'),
        )
      } finally {
        if (!cancelled) setRestoring(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [setSessionId, setStep])

  const clearRestoreError = useCallback(() => setRestoreError(null), [])

  const value = useMemo(
    () => ({
      sessionId,
      step,
      summary,
      matchedDone,
      restoring,
      restoreError,
      exportInFlight,
      pendingSessionOps,
      setSessionId,
      setStep,
      setSummary,
      setMatchedDone,
      setExportInFlight,
      ensureSession,
      invalidateDownstream,
      reset,
      clearRestoreError,
    }),
    [
      sessionId,
      step,
      summary,
      matchedDone,
      restoring,
      restoreError,
      exportInFlight,
      pendingSessionOps,
      setSessionId,
      setStep,
      ensureSession,
      invalidateDownstream,
      reset,
      clearRestoreError,
    ],
  )

  return (
    <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>
  )
}

export function useWorkflow(): WorkflowState {
  const ctx = useContext(WorkflowContext)
  if (!ctx) {
    throw new Error('useWorkflow must be used within WorkflowProvider')
  }
  return ctx
}
