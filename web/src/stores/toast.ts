import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'error'

export interface ToastItem {
  id: number
  message: string
  type: ToastType
}

const TOAST_DURATION_MS = 3000

/**
 * Ephemeral toast queue. Each toast is auto-removed after 3 seconds.
 * Items are appended in order; expired items are filtered out.
 */
export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])
  let nextId = 0

  function show(message: string, type: ToastType = 'info') {
    const id = nextId++
    items.value.push({ id, message, type })
    setTimeout(() => {
      items.value = items.value.filter((t) => t.id !== id)
    }, TOAST_DURATION_MS)
  }

  return { items, show }
})