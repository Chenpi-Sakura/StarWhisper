<script setup lang="ts">
/**
 * PlateBox — concept-book parchment plate with double-line border + cap header.
 * Slots:
 *  - `cap-icon`: small decorative element on the left of the cap
 *  - `default`:   plate body content
 *
 * The cap uses the standard `<b>PLATE Ⅹ</b><span>subtitle</span><i class="rule"/><span class="fleuron">❧</span>` layout;
 * callers usually supply caption text via the `caption` prop.
 */
defineProps<{
  /** Small uppercase latin label, e.g. "PLATE Ⅰ" */
  plate?: string
  /** Chinese subtitle, e.g. "观星指数 · 今夜之鉴" */
  caption?: string
}>()
</script>

<template>
  <section class="plate anim">
    <header v-if="plate || caption || $slots['cap-icon']" class="plate-cap">
      <slot name="cap-icon">
        <b v-if="plate">{{ plate }}</b>
        <span v-if="caption">{{ caption }}</span>
      </slot>
      <i class="rule" />
      <span class="fleuron">❧</span>
    </header>
    <div class="plate-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.plate {
  position: relative;
  background: var(--paper-hi);
  border: 1px solid var(--line);
}
.plate::before {
  content: '';
  position: absolute;
  inset: 7px;
  border: 1px solid var(--line-soft);
  pointer-events: none;
}
.plate-cap {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 26px;
  border-bottom: 1px solid var(--line-soft);
}
.plate-cap b {
  font-family: var(--disp);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.34em;
  color: var(--gold);
}
.plate-cap span {
  font-family: var(--cn);
  font-size: 12px;
  color: var(--ink-faint);
  letter-spacing: 0.2em;
}
.plate-cap .rule {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--line-soft), transparent);
}
.plate-cap .fleuron {
  color: var(--gold);
  font-size: 13px;
}
.plate-body {
  padding: 26px;
}
</style>