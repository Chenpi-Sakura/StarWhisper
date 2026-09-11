<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ score: number }>()

const R = 88
const CIRC = 2 * Math.PI * R
const num = ref(0)
const arcOffset = ref(CIRC)
const needleDeg = ref(-90)

let raf = 0

function animateTo(target: number): void {
  cancelAnimationFrame(raf)
  // jsdom 未实现 matchMedia，可选链容错（prefers-reduced-motion 取不到按 false）
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false
  if (reduced) {
    num.value = target
    arcOffset.value = CIRC * (1 - target / 100)
    needleDeg.value = -90 + (target / 100) * 270
    return
  }
  const start = performance.now()
  const dur = 1300
  const from = num.value
  const step = (t: number): void => {
    const p = Math.min(1, (t - start) / dur)
    const e = 1 - Math.pow(1 - p, 3)
    num.value = Math.round(from + (target - from) * e)
    arcOffset.value = CIRC * (1 - ((from + (target - from) * e) / 100))
    needleDeg.value = -90 + ((from + (target - from) * e) / 100) * 270
    if (p < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

// 刻度：270° 扇区，每 6.75° 一根
const ticks = Array.from({ length: 41 }, (_, i) => {
  const deg = -90 + (i / 40) * 270
  const major = i % 5 === 0
  const rad = (deg * Math.PI) / 180
  const r1 = major ? 74 : 78
  const r2 = 82
  const cx = 110
  const cy = 110
  return {
    x1: cx + r1 * Math.sin(rad), y1: cy - r1 * Math.cos(rad),
    x2: cx + r2 * Math.sin(rad), y2: cy - r2 * Math.cos(rad),
    major,
  }
})

onMounted(() => animateTo(props.score))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <div class="gauge-box">
    <svg viewBox="0 0 220 220" role="img" aria-label="观星指数仪表盘">
      <circle cx="110" cy="110" r="104" fill="none" stroke="rgba(46,36,23,.5)" stroke-width="1" />
      <circle cx="110" cy="110" r="99" fill="none" stroke="rgba(46,36,23,.25)" stroke-width=".6" />
      <g class="gauge-ticks">
        <line
          v-for="(t, i) in ticks" :key="i" class="gauge-tick"
          :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2"
          :stroke="t.major ? 'rgba(46,36,23,.6)' : 'rgba(46,36,23,.28)'"
          :stroke-width="t.major ? 1.2 : 0.6"
        />
      </g>
      <circle cx="110" cy="110" :r="R" fill="none" stroke="rgba(169,126,47,.18)" stroke-width="7" />
      <circle
        cx="110" cy="110" :r="R" fill="none" stroke="#b3873a" stroke-width="7"
        stroke-linecap="round" :stroke-dasharray="CIRC" :stroke-dashoffset="arcOffset"
        transform="rotate(-90 110 110)"
      />
      <circle cx="110" cy="110" r="70" fill="none" stroke="rgba(46,36,23,.3)" stroke-width=".6" stroke-dasharray="1 5" />
      <g class="gauge-needle" :style="{ transform: `rotate(${needleDeg}deg)`, transformOrigin: '110px 110px' }">
        <path d="M110 110 L110 34" stroke="#9c3b2a" stroke-width="1.4" />
        <path d="M110 34 L106 44 L114 44 Z" fill="#9c3b2a" />
      </g>
      <circle cx="110" cy="110" r="5" fill="#2e2417" />
      <circle cx="110" cy="110" r="2" fill="#c9a24a" />
    </svg>
    <div class="gauge-center">
      <div class="gauge-num">{{ num }}</div>
      <div class="gauge-of">INDEX · 满分百</div>
    </div>
  </div>
</template>

<style scoped>
.gauge-box {
  position: relative;
  width: 280px;
  height: 280px;
  max-width: 100%;
}
.gauge-box svg {
  width: 100%;
  height: 100%;
}
.gauge-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.gauge-num {
  font-family: var(--disp);
  font-weight: 700;
  font-size: 58px;
  line-height: 1;
  color: var(--ink);
}
.gauge-of {
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: var(--ink-faint);
  margin-top: 6px;
}
</style>