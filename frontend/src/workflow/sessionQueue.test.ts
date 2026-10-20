import { describe, expect, it } from 'vitest'
import { enqueueSessionOp, getPendingSessionOps } from './sessionQueue'

describe('enqueueSessionOp', () => {
  it('runs tasks strictly in order', async () => {
    const order: number[] = []
    const slow = enqueueSessionOp(async () => {
      await new Promise((r) => setTimeout(r, 40))
      order.push(1)
      return 'a'
    })
    const fast = enqueueSessionOp(async () => {
      order.push(2)
      return 'b'
    })
    expect(getPendingSessionOps()).toBeGreaterThan(0)
    const [a, b] = await Promise.all([slow, fast])
    expect(a).toBe('a')
    expect(b).toBe('b')
    expect(order).toEqual([1, 2])
    expect(getPendingSessionOps()).toBe(0)
  })
})
