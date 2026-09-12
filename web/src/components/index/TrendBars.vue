<script setup lang="ts">
import { computed } from 'vue'

import type { HourlyPoint } from '../../types'
import { formatSpan } from '../../utils/stargazeRange'

const props = defineProps<{ hourly: HourlyPoint[]; nowTime?: string }>()

function hhmm(t: string): string {
  return t.split('T')[1]?.slice(0, 5) ?? t
}

function hourOf(t: string): string {
  return t.split('T')[1]?.slice(0, 2) ?? ''
}

/**
 * 夜间可观测：后端逐点标 `night`；缺字段（旧 fixture / 简版）按可观测处理。
 * 白天不是“没有指数”，而是不宜观测——故照旧画柱，但弱化并单独标注。
 */
function isNight(p: HourlyPoint): boolean {
  return p.night !== false
}

const hasDay = computed(() => props.hourly.some((p) => p.night === false))
const dayCount = computed(() => props.hourly.filter((p) => p.night === false).length)

/**
 * 最佳观测窗：只在夜间小时里找峰值（白昼分数不代表可观测），
 * 峰值 ≥60 起算，先收「峰值 ±10 分」核心带，再沿 ≥60 分的夜间时次延展。
 */
const bestRange = computed<[number, number] | null>(() => {
  const pts = props.hourly
  if (pts.length === 0) return null
  let peak = -1
  for (let i = 0; i < pts.length; i++) {
    if (!isNight(pts[i])) continue
    if (peak < 0 || pts[i].score > pts[peak].score) peak = i
  }
  if (peak < 0 || pts[peak].score < 60) return null
  const usable = (i: number): boolean =>
    i >= 0 && i < pts.length && isNight(pts[i]) && pts[i].score >= 60
  let a = peak
  let b = peak
  while (usable(a - 1) && pts[a - 1].score >= pts[peak].score - 10) a--
  while (usable(b + 1) && pts[b + 1].score >= pts[peak].score - 10) b++
  while (usable(a - 1)) a--
  while (usable(b + 1)) b++
  return [a, b]
})

/** 区间文案：跨日/月/年自动补上日期，单点则只给“M月D日 HH:MM”。 */
const bestLabel = computed(() => {
  const r = bestRange.value
  if (!r) return null
  return formatSpan(props.hourly[r[0]].time, props.hourly[r[1]].time)
})

/** 柱数超过 48 时进入密集模式（gap 收窄到 1px）。 */
const dense = computed(() => props.hourly.length > 48)

/** 纵坐标刻度：0-100 的观星指数（与 4 等分网格线对齐）。 */
const yTicks = ['100', '75', '50', '25', '0']

/**
 * 小时视图（≤24 点）：一格一槽，标签落在真实小时位置（区间起点可以不是 0 点）。
 * 每 4 小时标一格，末点补一个标签标出区间终点。
 */
function axisSlotLabel(i: number): string {
  if (i % 4 === 0 || i === props.hourly.length - 1) return hourOf(props.hourly[i].time)
  return ''
}

/** 多日视图（>24 点）的 x 轴刻度：按天派生（避免 7 天视图仍标 00-24 的误导）。 */
const axisTicks = computed<string[]>(() => {
  const n = props.hourly.length
  if (n <= 24) return []
  const days = Math.floor(n / 24)
  return Array.from({ length: days + 1 }, (_, i) => `+${i}d`)
})

function barH(score: number): string {
  return `${Math.max(2, score)}%`
}
</script>

<template>
  <div v-if="hourly.length === 0" class="bars-empty">
    趋势图暂不可用 —— 简版指数仅提供总评。
  </div>
  <template v-else>
    <div class="chart-area">
      <div class="chart-ylab">观星指数 · 0—100</div>
      <div class="chart-main">
        <div class="chart-row">
          <div class="chart-yticks" aria-hidden="true">
            <i v-for="t in yTicks" :key="t">{{ t }}</i>
          </div>
          <div class="chart-box">
            <div class="chart-bars" :class="{ dense }">
              <i
                v-for="(p, i) in hourly" :key="p.time" class="cbar"
                :class="{
                  good: p.score >= 60,
                  best: bestRange !== null && i >= bestRange[0] && i <= bestRange[1],
                  now: p.time === nowTime,
                  day: p.night === false,
                }"
                :title="`${hhmm(p.time)} 指数 ${p.score}（${p.night === false ? '白昼/暮光' : '夜间'}）`"
                :style="{ height: barH(p.score) }"
              />
            </div>
          </div>
        </div>
        <!-- 昼夜带：与柱同槽位，直观标出哪些小时是夜间可观测时段 -->
        <div v-if="hasDay" class="night-band" :class="{ dense }">
          <i
            v-for="p in hourly" :key="`nb-${p.time}`" class="nb"
            :class="{ day: p.night === false }"
          />
        </div>
        <div v-if="hourly.length <= 24" class="chart-axis slots">
          <span
            v-for="(p, i) in hourly" :key="p.time" class="axis-slot"
          >{{ axisSlotLabel(i) }}</span>
        </div>
        <div v-else class="chart-axis">
          <span v-for="t in axisTicks" :key="t">{{ t }}</span>
        </div>
      </div>
    </div>
    <div class="chart-note">
      <span v-if="bestLabel">☾ 最佳观测窗 <b>{{ bestLabel }}</b></span>
      <span v-else-if="hasDay && dayCount === hourly.length" class="note-dim">
        整段皆为白昼 / 暮光 —— 无观测窗
      </span>
      <span>✦ 当前时刻</span>
      <span v-if="hasDay" class="band-legend">
        <i class="sw night" />夜间可观测
        <i class="sw day" />白昼 / 暮光
      </span>
    </div>
  </template>
</template>

<style scoped>
.bars-empty {
  text-align: center;
  color: var(--ink-faint);
  font-style: italic;
  padding: 30px 10px;
}
.chart-area {
  display: flex;
  gap: 4px;
}
.chart-main {
  flex: 1;
  min-width: 0;
}
/* 纵坐标说明（竖排）+ 0—100 刻度 */
.chart-ylab {
  display: flex;
  align-items: center;
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: var(--cn);
  font-size: 10.5px;
  letter-spacing: 0.26em;
  color: var(--ink-faint);
  white-space: nowrap;
}
.chart-row {
  display: flex;
  align-items: stretch;
}
.chart-yticks {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 26px;
  padding-right: 6px;
  text-align: right;
  font-family: var(--disp);
  font-size: 9.5px;
  color: var(--ink-faint);
}
.chart-yticks i {
  font-style: normal;
  line-height: 1;
}
.chart-box {
  flex: 1;
  min-width: 0;
  position: relative;
  height: 190px;
  border: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line);
  background: repeating-linear-gradient(
    to top,
    transparent 0 calc(25% - 1px),
    rgba(46, 36, 23, 0.07) calc(25% - 1px) 25%
  );
}
.chart-bars {
  position: absolute;
  inset: 0 8px;
  display: flex;
  align-items: flex-end;
  gap: 3px;
}
.chart-bars.dense {
  gap: 1px;
}
.cbar {
  flex: 1;
  min-width: 0;
  height: 0;
  border-top: 2px solid var(--ink-soft);
  background: repeating-linear-gradient(0deg, rgba(92, 75, 50, 0.85) 0 2px, rgba(92, 75, 50, 0.45) 2px 4px);
  transition: height 0.9s cubic-bezier(0.2, 0.8, 0.2, 1);
  position: relative;
}
.cbar.good {
  border-top-color: var(--gold);
  background: repeating-linear-gradient(0deg, rgba(169, 126, 47, 0.9) 0 2px, rgba(201, 162, 74, 0.4) 2px 4px);
}
/* 白昼 / 暮光：照旧给分数，但压淡（提示“不宜观测”而非“无数据”） */
.cbar.day {
  opacity: 0.3;
  border-top-color: var(--ink-faint);
  background: repeating-linear-gradient(0deg, rgba(92, 75, 50, 0.7) 0 2px, rgba(92, 75, 50, 0.35) 2px 4px);
}
.cbar.now::after {
  content: '✦';
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--seal);
  font-size: 10px;
}
.cbar.best::before {
  content: '☾';
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--gold);
  font-size: 11px;
}
/* 昼夜带 */
.night-band {
  display: flex;
  gap: 3px;
  margin-top: 6px;
  padding: 0 8px 0 34px;
}
.night-band.dense {
  gap: 1px;
}
.night-band .nb {
  flex: 1;
  min-width: 0;
  height: 6px;
  background: repeating-linear-gradient(90deg, var(--ink-soft) 0 3px, rgba(92, 75, 50, 0.35) 3px 6px);
}
.night-band .nb.day {
  background: repeating-linear-gradient(90deg, rgba(169, 126, 47, 0.45) 0 2px, transparent 2px 4px);
  outline: 1px solid rgba(169, 126, 47, 0.3);
  outline-offset: -1px;
}
.chart-axis {
  display: flex;
  justify-content: space-between;
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
  margin-top: 8px;
  padding: 0 6px 0 32px;
}
/* 小时视图：与柱同宽的槽位，保证标签落在真实小时上 */
.chart-axis.slots {
  gap: 3px;
  justify-content: flex-start;
  letter-spacing: 0;
  padding: 0 8px 0 34px;
}
.axis-slot {
  flex: 1;
  min-width: 0;
  text-align: center;
  font-size: 9px;
}
.chart-note {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 14px;
  font-family: var(--cn);
  font-size: 12.5px;
  color: var(--ink-soft);
}
.chart-note b {
  color: var(--gold);
}
.note-dim {
  color: var(--ink-faint);
  font-style: italic;
}
.band-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink-faint);
}
.band-legend .sw {
  width: 16px;
  height: 6px;
  display: inline-block;
}
.band-legend .sw.night {
  background: repeating-linear-gradient(90deg, var(--ink-soft) 0 3px, rgba(92, 75, 50, 0.35) 3px 6px);
}
.band-legend .sw.day {
  background: repeating-linear-gradient(90deg, rgba(169, 126, 47, 0.45) 0 2px, transparent 2px 4px);
  outline: 1px solid rgba(169, 126, 47, 0.3);
  outline-offset: -1px;
}

/* ================= 移动端（≤620px） ================= */
@media (max-width: 620px) {
  /* 降高 + 收紧字号，保证 24 槽的小时标签（每 4 小时一个）与 7 日视图
     的 +Nd 刻度都不相互叠字（移动端实测问题） */
  .chart-box {
    height: 150px;
  }
  .chart-ylab {
    /* 竖向说明在窄屏占比过大，且与左侧 y 刻度重复，让位给图体 */
    display: none;
  }
  .chart-yticks {
    width: 24px;
    font-size: 9px;
  }
  .chart-axis {
    font-size: 9px;
    letter-spacing: 0.05em;
    padding: 0 4px 0 30px;
  }
  .chart-axis.slots {
    padding: 0 6px 0 32px;
  }
  .axis-slot {
    font-size: 8.5px;
  }
  .night-band {
    padding: 0 6px 0 32px;
  }
  .chart-note {
    gap: 10px;
    font-size: 11.5px;
  }
}
</style>
