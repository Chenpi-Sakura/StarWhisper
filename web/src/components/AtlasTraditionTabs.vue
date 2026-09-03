<script setup lang="ts">
import { onMounted } from 'vue'
import { useAtlasStore } from '../stores/atlas'

const store = useAtlasStore()

onMounted(async () => {
  await store.loadTraditions()
})
</script>

<template>
  <nav class="tradition-tabs" role="tablist">
    <button
      v-for="t in store.traditions"
      :key="t.key"
      :class="['trad-tab', { active: t.key === store.currentTradition }]"
      role="tab"
      :aria-selected="t.key === store.currentTradition"
      :data-testid="`trad-tab-${t.key}`"
      type="button"
      @click="store.setTradition(t.key)"
    >
      <span class="trad-glyph">{{ t.key === 'western' ? '✦' : '☷' }}</span>
      <span class="trad-label">{{ t.label }}</span>
      <span class="trad-count">{{ t.count }}</span>
    </button>
  </nav>
</template>

<style scoped>
.tradition-tabs {
  display: flex;
  gap: 0;
  margin: 18px 0 14px;
  border-bottom: 2px solid var(--line);
}
.trad-tab {
  background: none;
  border: none;
  padding: 12px 24px;
  font-family: var(--cn);
  font-size: 15px;
  letter-spacing: 0.15em;
  color: var(--ink-faint);
  cursor: pointer;
  position: relative;
  transition: 0.2s;
}
.trad-tab.active {
  color: var(--ink);
  font-weight: 700;
}
.trad-tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gold);
}
.trad-glyph {
  margin-right: 6px;
  font-size: 18px;
  color: var(--gold);
}
.trad-count {
  margin-left: 6px;
  font-size: 12px;
  color: var(--ink-faint);
  font-style: italic;
}
</style>
