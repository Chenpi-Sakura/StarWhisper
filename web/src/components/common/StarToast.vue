<script setup lang="ts">
import { useToastStore } from '../../stores/toast'

const toast = useToastStore()
</script>

<template>
  <div class="star-toast-stack" aria-live="polite">
    <div
      v-for="t in toast.items"
      :key="t.id"
      class="star-toast"
      :class="t.type"
      role="status"
    >
      {{ t.message }}
    </div>
  </div>
</template>

<style scoped>
.star-toast-stack {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.star-toast {
  background: var(--parchment-dark);
  color: var(--ink);
  border: 1px solid var(--gold-ink);
  padding: 8px 16px;
  font-size: 13px;
  min-width: 200px;
  text-align: center;
}
.star-toast.success {
  border-color: var(--gold-bright);
  color: var(--gold-bright);
}
.star-toast.error {
  border-color: var(--seal-red);
  color: var(--seal-red);
}
</style>