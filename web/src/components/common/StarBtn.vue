<script setup lang="ts">
/**
 * StarBtn — concept-book action button (concept .btn).
 * Variants:
 *  - gold:  gold-ink filled (primary action)
 *  - seal:  red seal outline (destructive / warning)
 *  - ghost: ink-soft outline, transparent background
 *  - default: ink outline, transparent background
 *
 * Sizes: 'sm' | 'md' (default) | 'lg'
 */
defineProps<{
  label?: string
  variant?: 'default' | 'gold' | 'seal' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  type?: 'button' | 'submit'
}>()

defineEmits<{
  (e: 'click'): void
}>()
</script>

<template>
  <button
    class="btn"
    :class="[
      variant && variant !== 'default' ? `btn-${variant}` : '',
      size === 'sm' ? 'btn-sm' : '',
      size === 'lg' ? 'btn-lg' : '',
    ]"
    :disabled="disabled"
    :type="type ?? 'button'"
    @click="$emit('click')"
  >
    <slot>{{ label }}</slot>
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--ink);
  background: transparent;
  color: var(--ink);
  font-family: var(--cn);
  font-size: 14px;
  letter-spacing: 0.16em;
  padding: 10px 24px;
  border-radius: 2px;
  transition: 0.25s;
}
.btn:hover:not(:disabled) {
  background: var(--ink);
  color: var(--paper-hi);
}
.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-sm {
  padding: 6px 14px;
  font-size: 12px;
  letter-spacing: 0.12em;
}
.btn-lg {
  padding: 13px 34px;
  font-size: 15px;
}
.btn-gold {
  background: var(--gold-2);
  border-color: #7c5f1e;
  color: #241c10;
  font-weight: 700;
}
.btn-gold:hover:not(:disabled) {
  background: var(--gold);
  color: #241c10;
}
.btn-seal {
  border-color: var(--seal);
  color: var(--seal);
}
.btn-seal:hover:not(:disabled) {
  background: var(--seal);
  color: var(--paper-hi);
}
.btn-ghost {
  border-color: transparent;
  color: var(--ink-soft);
}
.btn-ghost:hover:not(:disabled) {
  background: rgba(46, 36, 23, 0.06);
  color: var(--ink);
}
</style>