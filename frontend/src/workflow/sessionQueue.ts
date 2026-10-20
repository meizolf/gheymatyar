/** Serialize per-session mutations so review/export cannot race. */

type Task<T> = () => Promise<T>

let chain: Promise<unknown> = Promise.resolve()
let pending = 0
const listeners = new Set<() => void>()

function notify() {
  for (const listener of listeners) listener()
}

export function getPendingSessionOps(): number {
  return pending
}

export function subscribeSessionOps(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function enqueueSessionOp<T>(task: Task<T>): Promise<T> {
  pending += 1
  notify()
  const run = chain.then(task, task)
  chain = run.then(
    () => undefined,
    () => undefined,
  )
  return run.finally(() => {
    pending = Math.max(0, pending - 1)
    notify()
  })
}
