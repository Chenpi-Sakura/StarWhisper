<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStargazeStore } from '../stores/stargaze'
import PlateBox from '../components/common/PlateBox.vue'
import StarBtn from '../components/common/StarBtn.vue'
import StarChip from '../components/common/StarChip.vue'

defineEmits<{
  'go-atlas': []
  'try-orion': []
}>()

const store = useStargazeStore()

onMounted(() => {
  store.locate()
})

const status = computed(() => store.status)
const data = computed(() => store.data)

const gradeColor = computed(() => {
  switch (data.value?.grade) {
    case '优':
      return 'var(--good)'
    case '良':
      return 'var(--gold)'
    case '一般':
      return 'var(--ink-soft)'
    case '差':
      return 'var(--seal)'
    default:
      return 'var(--ink)'
  }
})

const components = computed(() => {
  const c = data.value?.components
  if (!c) return []
  return [
    { key: 'cloud', label: '云量', value: c.cloud },
    { key: 'precip', label: '降水', value: c.precip },
    { key: 'windtemp', label: '风温', value: c.windtemp },
    { key: 'moon', label: '月相', value: c.moon },
    { key: 'bortle', label: '光污染', value: c.bortle },
  ]
})

// ---- 曲线 ----
const W = 600
const H = 180
const PAD_X = 10
const PAD_TOP = 18
const PAD_BOTTOM = 26

function yForScore(score: number): number {
  return PAD_TOP + (1 - score / 100) * (H - PAD_TOP - PAD_BOTTOM)
}

const curvePoints = computed(() => {
  const pts = data.value?.hourly ?? []
  if (pts.length === 0) return ''
  const step = (W - PAD_X * 2) / Math.max(1, pts.length - 1)
  return pts
    .map((p, i) => {
      const x = PAD_X + i * step
      const y = yForScore(p.score)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const curveArea = computed(() => {
  const pts = data.value?.hourly ?? []
  if (pts.length === 0) return ''
  const step = (W - PAD_X * 2) / Math.max(1, pts.length - 1)
  const line = pts
    .map((p, i) => `${(PAD_X + i * step).toFixed(1)},${yForScore(p.score).toFixed(1)}`)
    .join(' ')
  return `${PAD_X},${H - PAD_BOTTOM} ${line} ${W - PAD_X},${H - PAD_BOTTOM}`
})

const xLabels = computed(() => {
  const pts = data.value?.hourly ?? []
  if (pts.length === 0) return []
  const idxs = [0, Math.floor((pts.length - 1) / 2), pts.length - 1]
  return [...new Set(idxs)].map((i) => formatHour(pts[i].time))
})

function formatHour(t: string): string {
  const [d, time] = t.split('T')
  const mm = d.slice(5, 7)
  const dd = d.slice(8, 10)
  return `${mm}/${dd} ${time.slice(0, 2)}时`
}

function setRange(days: 1 | 7): void {
  store.setRange(days)
}

</script>

<template>
  <div class="index-view">
    <!-- 卷首题签（只在首页显示） -->
    <section class="frontispiece anim go">
      <svg class="orn orn-spin" viewBox="0 0 120 120" fill="none" stroke="#5c4b32" stroke-width="0.8">
        <circle cx="60" cy="60" r="56" opacity="0.5" />
        <circle cx="60" cy="60" r="42" stroke-dasharray="2 4" opacity="0.6" />
        <path d="M60 10 L65 55 L110 60 L65 65 L60 110 L55 65 L10 60 L55 55 Z" fill="rgba(169,126,47,0.15)" />
        <path d="M60 28 L63 57 L92 60 L63 63 L60 92 L57 63 L28 60 L57 57 Z" transform="rotate(45 60 60)" opacity="0.6" />
        <circle cx="60" cy="60" r="3.5" fill="#a97e2f" stroke="none" />
      </svg>
      <div class="f-title">
        <div class="star-row">✦ ✦ ✦</div>
        <h1>星语图鉴</h1>
        <div class="latin">STELLA LOQUITUR · 俯仰之间 星河可辨</div>
        <div class="motto">「以眼为镜，上溯星河；以纸为舟，夜渡千星。」</div>
        <div class="rule">❦</div>
      </div>
      <svg class="orn orn-spin rev" viewBox="0 0 120 120" fill="none" stroke="#5c4b32" stroke-width="0.8">
        <circle cx="60" cy="60" r="52" opacity="0.6" />
        <ellipse cx="60" cy="60" rx="52" ry="17" opacity="0.55" />
        <ellipse cx="60" cy="60" rx="52" ry="17" transform="rotate(62 60 60)" stroke-dasharray="3 3" opacity="0.5" />
        <circle cx="38" cy="42" r="1.6" fill="#a97e2f" stroke="none" />
        <circle cx="76" cy="34" r="1.2" fill="#a97e2f" stroke="none" />
        <circle cx="88" cy="66" r="1.8" fill="#a97e2f" stroke="none" />
        <circle cx="52" cy="82" r="1.3" fill="#a97e2f" stroke="none" />
      </svg>
    </section>

    <PlateBox plate="PLATE Ⅰ" caption="观星指数 · 今夜之鉴">
      <!-- loading -->
      <div v-if="status === 'loading'" class="placeholder anim go" data-testid="stargaze-loading">
        <div class="seal gold big-seal">观</div>
        <h2>观星指数</h2>
        <p class="sub">OPEN-METEO · 月相 · BORTLE</p>
        <div class="divider-orn">❦</div>
        <p class="note">正在晚风中问卜今夜的天象……</p>
      </div>

      <!-- error -->
      <div v-else-if="status === 'error'" class="placeholder anim go" data-testid="stargaze-error">
        <div class="seal gold big-seal">滞</div>
        <h2>天象未明</h2>
        <p class="note">{{ store.errorMessage ?? '天气服务暂不可用' }}</p>
        <div class="actions">
          <StarBtn label="重新问卜" variant="gold" @click="store.locate()" />
        </div>
      </div>

      <!-- ready -->
      <div v-else-if="data" class="ready anim go" data-testid="stargaze-ready">
        <div class="loc-bar">
          <span class="loc-name">{{ data.province }} · {{ data.city }}</span>
          <span class="loc-coord">
            北纬 {{ data.lat.toFixed(2) }}° · 东经 {{ data.lon.toFixed(2) }}°
          </span>
          <StarBtn label="重新定位" variant="ghost" size="sm" @click="store.locate()" />
        </div>

        <div class="score-row">
          <div class="dial" :style="{ borderColor: gradeColor }">
            <div class="dial-score" :style="{ color: gradeColor }">{{ data.score }}</div>
            <div class="dial-grade" :style="{ color: gradeColor }">{{ data.grade }}</div>
            <div class="dial-cap">今夜观星指数</div>
          </div>
          <div class="meta">
            <div class="meta-item">
              <span class="k">月相</span>
              <span class="v">
                {{ data.moon.label }} · 月照 {{ Math.round(data.moon.illumination * 100) }}%
              </span>
            </div>
            <div class="meta-item">
              <span class="k">光污染</span>
              <span class="v">Bortle {{ data.bortle }} · {{ data.bortle_label }}</span>
            </div>
            <div class="meta-item">
              <span class="k">今夜天气</span>
              <span class="v">
                云 {{ data.now.cloud }}% · 降水 {{ data.now.precip }}% ·
                {{ data.now.temp.toFixed(0) }}°C · 风 {{ data.now.wind.toFixed(0) }} km/h
              </span>
            </div>
          </div>
        </div>

        <div class="components">
          <div v-for="c in components" :key="c.key" class="comp">
            <span class="comp-label">{{ c.label }}</span>
            <span class="comp-bar"><i :style="{ width: `${Math.min(100, c.value)}%` }" /></span>
            <span class="comp-val">{{ Math.round(c.value) }}</span>
          </div>
        </div>

        <div class="curve-head">
          <span class="curve-title">
            未来 {{ store.rangeDays === 1 ? '24 小时' : '7 天' }} 观星时段曲线
          </span>
          <div class="curve-tabs">
            <StarChip label="24 小时" :active="store.rangeDays === 1" @click="setRange(1)" />
            <StarChip label="7 天" :active="store.rangeDays === 7" @click="setRange(7)" />
          </div>
        </div>

        <svg
          class="curve"
          :viewBox="`0 0 ${W} ${H}`"
          role="img"
          aria-label="观星指数时段曲线"
        >
          <line :x1="PAD_X" :x2="W - PAD_X" :y1="yForScore(60)" :y2="yForScore(60)" class="ref-line" />
          <line :x1="PAD_X" :x2="W - PAD_X" :y1="yForScore(40)" :y2="yForScore(40)" class="ref-line soft" />
          <polygon :points="curveArea" class="curve-area" />
          <polyline :points="curvePoints" class="curve-line" />
        </svg>
        <div class="curve-xlabels">
          <span v-for="(l, i) in xLabels" :key="i">{{ l }}</span>
        </div>

        <div class="actions">
          <StarBtn label="试一张 orion" variant="gold" @click="$emit('try-orion')" />
          <StarBtn label="前往星座图鉴 →" variant="default" @click="$emit('go-atlas')" />
        </div>
      </div>
    </PlateBox>
  </div>
</template>

<style scoped>
.index-view {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin-top: 8px;
}
.placeholder {
  text-align: center;
  padding: 32px 20px 8px;
}
.big-seal {
  margin: 0 auto 14px;
  width: 72px;
  height: 72px;
  font-size: 22px;
}
.placeholder h2 {
  font-family: var(--cn);
  font-weight: 900;
  font-size: 32px;
  letter-spacing: 0.16em;
  margin: 0 0 4px;
  color: var(--ink);
}
.placeholder .sub {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.4em;
  color: var(--gold);
  margin: 0;
}
.placeholder .note {
  font-style: italic;
  color: var(--ink-soft);
  margin: 16px auto;
  max-width: 540px;
  line-height: 2;
}
.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 20px;
}

/* ---- ready ---- */
.loc-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 20px;
}
.loc-name {
  font-family: var(--cn);
  font-weight: 700;
  font-size: 18px;
  letter-spacing: 0.12em;
  color: var(--ink);
}
.loc-coord {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
  flex: 1;
}

.score-row {
  display: flex;
  gap: 28px;
  align-items: center;
  flex-wrap: wrap;
}
.dial {
  width: 180px;
  height: 180px;
  border-radius: 50%;
  border: 6px double var(--gold);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin: 10px auto;
}
.dial-score {
  font-family: var(--disp);
  font-size: 58px;
  font-weight: 700;
  line-height: 1;
}
.dial-grade {
  font-family: var(--cn);
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 0.3em;
  margin-top: 2px;
}
.dial-cap {
  font-family: var(--cn);
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.2em;
  margin-top: 6px;
}
.meta {
  flex: 1;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.meta-item {
  display: flex;
  gap: 12px;
  align-items: baseline;
}
.meta-item .k {
  font-family: var(--cn);
  font-size: 13px;
  color: var(--gold);
  letter-spacing: 0.2em;
  min-width: 74px;
}
.meta-item .v {
  font-family: var(--cn);
  font-size: 14px;
  color: var(--ink-soft);
}

.components {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px 22px;
  margin: 22px 0;
  padding: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(244, 236, 212, 0.5);
}
.comp {
  display: flex;
  align-items: center;
  gap: 10px;
}
.comp-label {
  font-family: var(--cn);
  font-size: 12px;
  color: var(--ink-soft);
  letter-spacing: 0.12em;
  min-width: 48px;
}
.comp-bar {
  flex: 1;
  height: 6px;
  background: rgba(46, 36, 23, 0.1);
  overflow: hidden;
}
.comp-bar i {
  display: block;
  height: 100%;
  background: var(--gold);
  transition: width 0.6s;
}
.comp-val {
  font-family: var(--disp);
  font-size: 13px;
  color: var(--gold);
  min-width: 24px;
  text-align: right;
}

.curve-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.curve-title {
  font-family: var(--cn);
  font-size: 14px;
  color: var(--ink);
  letter-spacing: 0.14em;
}
.curve-tabs {
  display: flex;
  gap: 8px;
}
.curve {
  width: 100%;
  height: 200px;
  margin-top: 14px;
}
.ref-line {
  stroke: var(--gold);
  stroke-opacity: 0.4;
  stroke-dasharray: 4 5;
  stroke-width: 1;
}
.ref-line.soft {
  stroke: var(--ink-faint);
  stroke-opacity: 0.3;
}
.curve-area {
  fill: rgba(201, 162, 74, 0.12);
  stroke: none;
}
.curve-line {
  fill: none;
  stroke: var(--gold);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.curve-xlabels {
  display: flex;
  justify-content: space-between;
  font-family: var(--disp);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  padding: 6px 4px 0;
}
</style>