<script setup lang="ts">
/**
 * StarChip — concept-book chip (concept .chip).
 * Variants: 'default' | 'gold' | 'warn'
 */
defineProps<{
  /** Optional glyph or icon prefix */
  glyph?: string
  label?: string
  variant?: 'default' | 'gold' | 'warn'
  active?: boolean
}>()

defineEmits<{
  (e: 'click'): void
}>()
</script>

<template>
  <button
    class="chip"
    :class="[
      variant === 'gold' ? 'gold' : '',
      variant === 'warn' ? 'warn' : '',
      active ? 'active' : '',
    ]"
    type="button"
    @click="$emit('click')"
  >
    <span v-if="glyph">{{ glyph }}</span>
    <slot>{{ label }}</slot>
  </button>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line-soft);
  background: #efe5c9;
  padding: 3px 11px;
  font-family: var(--cn);
  font-size: 11.5px;
  letter-spacing: 0.14em;
  color: var(--ink-soft);
  cursor: pointer;
  transition: 0.25s;
}
.chip:hover {
  border-color: var(--gold);
  color: var(--ink);
}
.chip.gold {
  border-color: rgba(169, 126, 47, 0.5);
  color: var(--gold);
  background: rgba(201, 162, 74, 0.1);
}
.chip.warn {
  border-color: rgba(156, 59, 42, 0.4);
  color: var(--seal);
  background: rgba(156, 59, 42, 0.07);
}
.chip.active {
  background: var(--ink);
  color: var(--gold-pale);
  border-color: var(--ink);
}
</style>