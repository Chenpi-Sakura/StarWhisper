<script setup lang="ts">
import { computed } from 'vue'

import type { StargazeAstro, StargazeMoon } from '../../types'

const props = defineProps<{
  moon: StargazeMoon
  astro?: StargazeAstro
  /** 次日的天文时刻（用于「次日天文晨光」与暗夜时长）；缺失时回退当天值 */
  nextAstro?: StargazeAstro
}>()

const R = 25
const CX = 26
const CY = 26

/** 月相双弧法：phase∈[0,29.53)，0=新月。返回亮面 path。 */
const moonPath = computed(() => {
  const phase = ((props.moon.phase % 29.53) + 29.53) % 29.53
  const k = phase / 29.53
  // 亮面宽边：盈月（k<0.5）在西侧（右），亏月在东侧（左）
  const waxing = k < 0.5
  // 中线椭圆半宽：0（弦月直边）→ R（半月圆边）→ 0
  const bulge = Math.abs(Math.cos(2 * Math.PI * k)) * R
  const sweepOuter = waxing ? 1 : 0
  const sweepInner = waxing ? (k < 0.25 ? 1 : 0) : (k < 0.75 ? 0 : 1)
  const outer =
    `M ${CX} ${CY - R} A ${R} ${R} 0 0 ${sweepOuter} ${CX} ${CY + R} `
  const inner =
    `A ${Math.max(0.01, bulge)} ${R} 0 0 ${sweepInner} ${CX} ${CY - R} Z`
  return outer + inner
})

const illumPct = computed(() => Math.round(props.moon.illumination * 100))

/** 保留 2 位小数，避免 SVG 属性里出现一长串浮点数。 */
function round2(v: number): number {
  return Math.round(v * 100) / 100
}

/** 太阳图例：空心圆环 r=14，8 道光芒全在圆环之外（r=17 → 24.4，不越出 52 画布）。 */
const SUN_RING_R = 14
const SUN_RAY_IN = 17
const SUN_RAY_OUT = 24.4
const sunRays = Array.from({ length: 8 }, (_, i) => {
  const rad = (i * 45 * Math.PI) / 180
  return {
    x1: round2(26 + SUN_RAY_IN * Math.sin(rad)),
    y1: round2(26 - SUN_RAY_IN * Math.cos(rad)),
    x2: round2(26 + SUN_RAY_OUT * Math.sin(rad)),
    y2: round2(26 - SUN_RAY_OUT * Math.cos(rad)),
  }
})

/** "HH:MM" → 当日分钟数；非法/缺省 → null。 */
function toMinutes(hhmm: string | null | undefined): number | null {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':').map(Number)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null
  return h * 60 + m
}

/** 当日白昼时长（日出 → 日落）。 */
const dayLength = computed(() => {
  const rise = toMinutes(props.astro?.sunrise)
  const set = toMinutes(props.astro?.sunset)
  if (rise === null || set === null || set <= rise) return null
  const mins = set - rise
  return `白昼 ${Math.floor(mins / 60)} 时 ${mins % 60} 分`
})

/** 次日凌晨的天文晨光（今夜的暗夜结束时刻）。 */
const nextDawn = computed(
  () => props.nextAstro?.astro_dawn ?? props.astro?.astro_dawn ?? null,
)

/** 今夜暗夜时长：天文暮光结束 → 次日天文晨光。 */
const darkLength = computed(() => {
  const dusk = toMinutes(props.astro?.astro_dusk)
  const dawn = toMinutes(nextDawn.value)
  if (dusk === null || dawn === null) return null
  const mins = (dawn + 24 * 60 - dusk) % (24 * 60)
  if (mins <= 0) return null
  return `暗夜 ${Math.floor(mins / 60)} 时 ${mins % 60} 分`
})

/** 银心落下是否已跨到次日（落下时刻早于升起时刻 → 次日凌晨）。 */
const galacticSetText = computed(() => {
  const set = props.astro?.galactic_set
  const rise = props.astro?.galactic_rise
  if (!set) return null
  const nextDay = !!rise && set < rise
  return `${nextDay ? '次日 ' : ''}${set} 落`
})

/** 入夜时银心是否已在地平线上（升起早于天文暮光结束）。 */
const galacticUpAtDusk = computed(() => {
  const rise = props.astro?.galactic_rise
  const dusk = props.astro?.astro_dusk
  return !!rise && !!dusk && rise < dusk
})

/** 银河核心 chip 文案：升起 / 落下 / 入夜是否已升起（空值不编造）。 */
const galacticText = computed(() => {
  const rise = props.astro?.galactic_rise
  if (!rise) return '—'
  const parts = [`${rise} 升`]
  if (galacticSetText.value) parts.push(galacticSetText.value)
  const tail = galacticUpAtDusk.value ? '（入夜即在）' : ''
  return `${parts.join(' · ')}${tail}`
})

/** 月出 / 月落文案（月落已在月相信息行，这里只拼月出）。 */
const moonriseText = computed(() => {
  const rise = props.astro?.moonrise
  return rise ? `${rise} 月出` : null
})
</script>

<template>
  <!-- 月亮与太阳并列：两个同尺寸（52px）图例，各自带当日时刻 -->
  <div class="moon-sun">
    <div class="sky-card">
      <svg class="moon-ico sky-ico" viewBox="0 0 52 52" role="img" :aria-label="moon.label">
        <circle :cx="CX" :cy="CY" :r="R" fill="#c9b98e" stroke="var(--line)" />
        <path class="moon-shape" :d="moonPath" fill="#f7f0da" />
      </svg>
      <div class="t">
        <b>{{ moon.label }} · 月龄 {{ moon.phase.toFixed(1) }}</b>
        <span>
          照明度 {{ illumPct }}%
          <template v-if="moonriseText"> · {{ moonriseText }}</template>
          <template v-if="astro?.moonset"> · {{ astro.moonset }} 西沉</template>
        </span>
        <span v-if="astro?.moonset" class="ok-line">✓ 月落之后，深空朗澈</span>
      </div>
    </div>

    <div class="sky-card">
      <svg class="sun-ico sky-ico" viewBox="0 0 52 52" role="img" aria-label="日出日落">
        <g class="sun-rays" stroke="#a97e2f" stroke-width="1.5" stroke-linecap="round" fill="none">
          <line
            v-for="(ray, i) in sunRays" :key="i"
            :x1="ray.x1" :y1="ray.y1" :x2="ray.x2" :y2="ray.y2"
          />
        </g>
        <circle
          class="sun-ring" cx="26" cy="26" :r="SUN_RING_R"
          fill="none" stroke="#a97e2f" stroke-width="1.5"
        />
      </svg>
      <div class="t">
        <b>日出 {{ astro?.sunrise ?? '—' }} · 日落 {{ astro?.sunset ?? '—' }}</b>
        <span v-if="dayLength">{{ dayLength }}</span>
        <span class="sun-hint">日落之后至天文晨光为夜间可观测时段</span>
      </div>
    </div>
  </div>

  <div class="moon-chips">
    <span class="chip">天文暮光 {{ astro?.astro_dusk ?? '—' }} 结束</span>
    <span class="chip">次日天文晨光 {{ nextDawn ?? '—' }}</span>
    <span v-if="darkLength" class="chip gold">{{ darkLength }}</span>
    <span class="chip gold">银河核心 {{ galacticText }}</span>
  </div>
</template>

<style scoped>
/* 并列布局：容器宽度不够（<2×230px）时自动上下堆叠 */
.moon-sun {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 18px 20px;
}
.sky-card {
  display: flex;
  gap: 16px;
  align-items: center;
  min-width: 0;
}
.sky-ico {
  width: 52px;
  height: 52px;
  flex: none;
}
/* 月相：满圆盘 + 描边环 */
.moon-ico {
  border-radius: 50%;
  border: 1px solid var(--line);
}
/* 太阳：纯线描（空心圆环 + 环外光芒），不加外框，否则光芒会被包在圈里 */
.sun-ico {
  overflow: visible;
}
.sky-card .t {
  font-family: var(--cn);
  min-width: 0;
}
.sky-card .t b {
  font-size: 15px;
  font-weight: 700;
}
.sky-card .t span {
  display: block;
  font-size: 12px;
  color: var(--ink-faint);
}
.ok-line {
  color: var(--good);
}
.sun-hint {
  font-size: 11px !important;
}
.moon-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

/* ================= 移动端（≤620px） ================= */
@media (max-width: 620px) {
  /* 显式单列：minmax(230px, 1fr) 在 ≤300px 可用宽度下会把 plate 撑宽 */
  .moon-sun {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
  }
  .sky-card {
    gap: 12px;
  }
  .sky-ico {
    width: 44px;
    height: 44px;
  }
  .sky-card .t b {
    font-size: 14px;
  }
  .moon-chips {
    gap: 6px;
    margin-top: 12px;
  }
}
</style>
