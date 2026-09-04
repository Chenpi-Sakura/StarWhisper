import { setActivePinia, createPinia } from 'pinia'
import { vi, test, expect, beforeEach } from 'vitest'

import { useToastStore } from '../src/stores/toast'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useRealTimers()
})

test('show adds a toast entry', () => {
  const toast = useToastStore()
  toast.show('hello', 'info')
  expect(toast.items).toHaveLength(1)
  expect(toast.items[0].message).toBe('hello')
  expect(toast.items[0].type).toBe('info')
})

test('show defaults type to info when omitted', () => {
  const toast = useToastStore()
  toast.show('default-type')
  expect(toast.items[0].type).toBe('info')
})

test('toast auto-removes after 3 seconds', () => {
  vi.useFakeTimers()
  const toast = useToastStore()
  toast.show('auto-remove', 'success')
  expect(toast.items).toHaveLength(1)
  vi.advanceTimersByTime(3000)
  expect(toast.items).toHaveLength(0)
  vi.useRealTimers()
})

test('multiple toasts keep independent ids', () => {
  vi.useFakeTimers()
  const toast = useToastStore()
  toast.show('first', 'info')
  vi.advanceTimersByTime(1000)
  toast.show('second', 'error')
  expect(toast.items).toHaveLength(2)
  vi.advanceTimersByTime(2000) // first expires
  expect(toast.items).toHaveLength(1)
  expect(toast.items[0].message).toBe('second')
  vi.useRealTimers()
})