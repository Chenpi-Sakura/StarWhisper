<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStargazeStore } from '../stores/stargaze'
import {
  applyRangePatch,
  currentHourOffset,
  dateHourFromOffset,
  formatHourOffset,
  isoPlusDays,
  todayIso,
} from '../utils/stargazeRange'
import StarBtn from '../components/common/StarBtn.vue'
import StarChip from '../components/common/StarChip.vue'
import IndexGauge from '../components/index/IndexGauge.vue'
import TrendBars from '../components/index/TrendBars.vue'
import MoonCard from '../components/index/MoonCard.vue'
import CitySearch from '../components/index/CitySearch.vue'

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

/** 与 server/services/index.py 的 grade() 对齐：≥80 优 / ≥60 良 / ≥40 一般 / 其余差。 */
const gradeDesc = computed(() => {
  switch (data.value?.grade) {
    case '优': return '夜空澄澈，宜观星'
    case '良': return '尚可一观，留意月色'
    case '一般': return '条件平平，量力而行'
    case '差': return '云深雨重，不宜观星'
    default: return ''
  }
})

const factors = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { key: 'cloud', label: '云量覆盖', display: `${d.now.cloud}%`, value: d.now.cloud },
    { key: 'rain',  label: '降水概率', display: `${d.now.precip}%`, value: d.now.precip },
    { key: 'light', label: '光污染强度', display: `${d.bortle_label} · ${Math.round(d.components.bortle)}%`, value: d.components.bortle },
  ]
})

/** 快捷预设：`24h` = 此刻起 24 小时；`7d` = 今日 00:00 起整 7 日。 */
function setRange(preset: '24h' | '7d'): void {
  store.applyPreset(preset)
}

/** 今天（本地时区，选择器与偏移换算的基准日）。 */
const today = todayIso()

/** 区间端点在「日期 + 整点」形态下的当前值（唯一来源 = store.rangeStartHour/rangeHours）。 */
const startPoint = computed(() => dateHourFromOffset(store.rangeStartHour, today))
const endPoint = computed(() =>
  dateHourFromOffset(store.rangeStartHour + store.rangeHours - 1, today),
)

/**
 * 任意单端改动（日期或整点）→ 重算区间并重新拉取。
 * 最小粒度 1 小时；起点平移保持原时长，终点越界自动 clamp 到 7 天窗口。
 */
function applyRangeChange(patch: {
  startDate?: string
  startHour?: number
  endDate?: string
  endHour?: number
}): void {
  const { startHour, hours } = applyRangePatch(
    {
      startDate: startPoint.value.date,
      startHour: startPoint.value.hour,
      endDate: endPoint.value.date,
      endHour: endPoint.value.hour,
    },
    patch,
    today,
  )
  store.setRange(startHour, hours)
}

const rangeStartDate = computed({
  get: () => startPoint.value.date,
  set: (v: string) => applyRangeChange({ startDate: v }),
})
const rangeStartHour = computed({
  get: () => startPoint.value.hour,
  set: (v: number) => applyRangeChange({ startHour: Number(v) }),
})
const rangeEndDate = computed({
  get: () => endPoint.value.date,
  set: (v: string) => applyRangeChange({ endDate: v }),
})
const rangeEndHour = computed({
  get: () => endPoint.value.hour,
  set: (v: number) => applyRangeChange({ endHour: Number(v) }),
})

/** 可选日期：今天 ~ +6 天（后端 7 天窗口）。 */
function minDay(): string {
  return today
}

function maxDay(): string {
  return isoPlusDays(today, 6)
}

/** 整点选项 00:00 - 23:00（最小粒度小时）。 */
const hourOptions = Array.from({ length: 24 }, (_, h) => ({
  value: h,
  label: `${String(h).padStart(2, '0')}:00`,
}))

/** 当前选中日展示文字：今天 / 明天 / 后天 + M月D日（FIG.3 用）。 */
const dayDisplay = computed(() => {
  const offset = store.selectedDayIndex
  const prefix = offset === 0 ? '今天' : offset === 1 ? '明天' : offset === 2 ? '后天' : ''
  const d = new Date()
  d.setDate(d.getDate() + offset)
  const md = `${d.getMonth() + 1} 月 ${d.getDate()} 日`
  return prefix ? `${prefix} · ${md}` : md
})

/** 当前所选日的月相 + astro 切片（向后兼容：未提供 daily 字段时 fallback 到 data.moon / data.astro）。 */
const currentMoon = computed(() =>
  data.value?.daily_moon?.[store.selectedDayIndex] ?? data.value?.moon,
)
const currentAstro = computed(() =>
  data.value?.daily_astro?.[store.selectedDayIndex] ?? data.value?.astro,
)
/** 次日天文时刻：用于「次日天文晨光」与今夜的暗夜时长（最后一天回退当天值）。 */
const nextAstro = computed(() =>
  data.value?.daily_astro?.[store.selectedDayIndex + 1],
)

/** FIG.2 标题里的区间文字：今天 14:00 → 明天 13:00 · 共 24 小时。 */
const rangeText = computed(() => {
  const s = store.rangeStartHour
  const e = s + store.rangeHours - 1
  return `${formatHourOffset(s, today)} → ${formatHourOffset(e, today)} · 共 ${store.rangeHours} 小时`
})

/** chip 选中态：24h = 此刻起满 24 个整点；7d = 今日 00:00 起整 7 日。 */
const preset24Active = computed(
  () => store.rangeHours === 24 && store.rangeStartHour === currentHourOffset(),
)
const preset7dActive = computed(
  () => store.rangeStartHour === 0 && store.rangeHours === 168,
)

// ---- 城市搜索已抽到 <CitySearch />（本地前缀树 + 自绘下拉） ----

</script>

<template>
  <div class="index-view">
    <!-- 卷首题签 -->
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

    <!-- 无外框容器：三态（loading / error / ready）直接铺开 -->
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

      <!-- ready：双栏图版 -->
      <div v-else-if="data" class="ready anim go" data-testid="stargaze-ready">
        <div class="index-grid">
          <!-- 左：PLATE Ⅰ 主图版 -->
          <div class="plate">
            <div class="plate-cap">
              <b>FIG. 1</b><span>今夜指数总评</span><i class="rule"></i><span class="fleuron">❧</span>
            </div>
            <div class="plate-body">
              <div class="city-bar">
                <CitySearch />
              </div>

              <div class="city-title">
                <h3>{{ data.province }} · {{ data.city }}</h3>
                <span class="tag">北纬 {{ data.lat.toFixed(2) }}° · Bortle {{ data.bortle }} · {{ data.bortle_label }}</span>
              </div>

              <div class="gauge-wrap">
                <IndexGauge :score="data.score" />
                <div class="gauge-meta">
                  <div class="seal" :class="`lv-${data.grade}`">{{ data.grade }}</div>
                  <span class="lv-desc">{{ gradeDesc }}</span>
                </div>
                <div class="lv-legend">
                  <i class="g">优 ≥80</i><i>良 60–79</i><i>一般 40–59</i><i class="r">差 &lt;40</i>
                </div>
              </div>

              <div class="divider-orn">☾ 综合云量 · 降水 · 光污染 ☽</div>
              <template v-for="f in factors" :key="f.key">
                <div class="meter-row"><span>{{ f.label }}</span><b>{{ f.display }}</b></div>
                <div class="meter-track"><div class="meter-fill" :style="{ width: `${Math.min(100, f.value)}%` }"></div></div>
              </template>

              <div class="actions">
                <StarBtn label="试一张 orion" variant="gold" @click="$emit('try-orion')" />
                <StarBtn label="前往星座图鉴 →" variant="default" @click="$emit('go-atlas')" />
              </div>
            </div>
          </div>

          <!-- 右：FIG.2 + FIG.3 -->
          <div class="side-col">
            <div class="plate">
              <div class="plate-cap">
                <b>FIG. 2</b><span>{{ rangeText }}</span><i class="rule"></i><span class="fleuron">❧</span>
              </div>
              <div class="plate-body">
                <div class="range-picker">
                  <!-- 起/止各自成组：窄屏换行时整组走，不会拆出「起 日期」在上一行、
                       小时在下一行的错位（移动端实测问题） -->
                  <div class="range-group">
                    <span class="picker-label">起</span>
                    <input
                      class="date-input range-start-date"
                      type="date"
                      :min="minDay()"
                      :max="maxDay()"
                      v-model="rangeStartDate"
                      aria-label="区间起始日期"
                    />
                    <select
                      class="hour-select range-start-hour"
                      v-model.number="rangeStartHour"
                      aria-label="区间起始整点"
                    >
                      <option v-for="h in hourOptions" :key="h.value" :value="h.value">{{ h.label }}</option>
                    </select>
                  </div>
                  <div class="range-group">
                    <span class="picker-label">止</span>
                    <input
                      class="date-input range-end-date"
                      type="date"
                      :min="minDay()"
                      :max="maxDay()"
                      v-model="rangeEndDate"
                      aria-label="区间结束日期"
                    />
                    <select
                      class="hour-select range-end-hour"
                      v-model.number="rangeEndHour"
                      aria-label="区间结束整点"
                    >
                      <option v-for="h in hourOptions" :key="h.value" :value="h.value">{{ h.label }}</option>
                    </select>
                  </div>
                  <span class="range-hint">最小粒度 1 小时 · 限未来 7 日</span>
                </div>
                <TrendBars :hourly="data.hourly" :now-time="data.now.time" />
                <div class="curve-tabs">
                  <StarChip label="此刻起 24 时" :active="preset24Active" @click="setRange('24h')" />
                  <StarChip label="整 7 日" :active="preset7dActive" @click="setRange('7d')" />
                </div>
              </div>
            </div>

            <div class="plate">
              <div class="plate-cap">
                <b>FIG. 3</b><span>{{ dayDisplay }} · 月相</span><i class="rule"></i><span class="fleuron">❧</span>
              </div>
              <div class="plate-body">
                <MoonCard :moon="currentMoon!" :astro="currentAstro" :next-astro="nextAstro" />
              </div>
            </div>
          </div>
        </div>
      </div>

    <div class="mascot">
      <figure class="mascot-frame">
        <img src="/小聆.jpg" alt="小聆妹" />
      </figure>
      <div class="mascot-banner">
        <span class="star-row">✦ ✦ ✦</span>
        <!-- 一句一行（移动端长句平铺会折在奇怪的位置） -->
        <p class="mantra">
          <span>小聆妹祝你观星成功！</span>
          <span>永远不淋雨！</span>
          <span>阴天教退散！</span>
        </p>
      </div>
    </div>
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

/* ---- 双栏图版 ---- */
.index-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}
.side-col {
  display: flex;
  flex-direction: column;
  gap: 22px;
  min-width: 0;
}
@media (max-width: 1000px) {
  /* 必须是 minmax(0, 1fr) 而不是 1fr：单列下 1fr 的最小尺寸是 auto，
     会被 plate 内仪表盘（280px）等固定宽度撑到 366px，窄屏整块内容
     横向溢出、被 main.frame 的 overflow-x: clip 裁掉（移动端实测问题） */
  .index-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* ---- 城市搜索（控件样式在 CitySearch.vue 内，为 scoped 作用域一致） ---- */
.city-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 18px;
}

/* ---- 城市标题 ---- */
.city-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.city-title h3 {
  margin: 0;
  font-family: var(--cn);
  font-weight: 900;
  font-size: 22px;
  letter-spacing: 0.1em;
  color: var(--ink);
}
.city-title .tag {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}

/* ---- 仪表盘 + 等级卡 ---- */
.gauge-wrap {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 24px;
  align-items: center;
  padding: 14px 4px 8px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 14px;
}
.gauge-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.gauge-meta .seal {
  width: 111px;
  height: 111px;
  font-size: 36px;
  border-width: 2.5px;
}
/* 只保留等级描述文案，不再重复印章里的「优/良/一般/差」字 */
.gauge-meta .lv-desc {
  font-family: var(--cn);
  font-size: 23px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--ink-soft);
}
.seal.lv-优 { color: var(--good); border-color: var(--good); }
.seal.lv-良 { color: var(--gold); border-color: var(--gold); }
.seal.lv-一般 { color: var(--ink-soft); border-color: var(--ink-soft); }
.seal.lv-差 { color: var(--seal); border-color: var(--seal); }
.lv-legend {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  font-family: var(--cn);
  font-size: 11.5px;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
  padding-top: 4px;
}
.lv-legend i {
  font-style: normal;
}
.lv-legend i.g { color: var(--good); }
.lv-legend i.r { color: var(--seal); }

/* ---- FIG.2 chip ---- */
.curve-tabs {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 14px;
}

/* ---- FIG.2 时间区间选择器（小时粒度） ---- */
.range-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}
.range-picker .range-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.range-picker .picker-label {
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--ink-soft);
}
.range-picker .range-hint {
  font-family: var(--cn);
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.date-input {
  border: 1px solid var(--line-soft);
  background: #efe5c9;
  padding: 5px 10px;
  font-family: var(--cn);
  font-size: 12.5px;
  letter-spacing: 0.08em;
  color: var(--ink);
  transition: 0.25s;
}
.date-input:focus {
  outline: none;
  border-color: var(--gold);
}
.hour-select {
  border: 1px solid var(--line-soft);
  background: #efe5c9;
  padding: 5px 6px;
  font-family: var(--disp);
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
  transition: 0.25s;
}
.hour-select:focus {
  outline: none;
  border-color: var(--gold);
}

/* ---- 行动按钮 ---- */
.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 20px;
}

/* ---- 小聆 mascot ---- */
.mascot {
  text-align: center;
  padding: 12px 0 8px;
}
.mascot-frame {
  position: relative;
  display: inline-block;
  padding: 12px;
  border: 1px solid var(--line);
  background: var(--paper-hi);
}
.mascot-frame::before {
  content: '';
  position: absolute;
  inset: 5px;
  border: 1px solid var(--line-soft);
  pointer-events: none;
}
.mascot-frame img {
  display: block;
  width: 210px;
  max-width: 100%;
  height: auto;
}
.mascot-banner {
  margin-top: 16px;
}
.mascot-banner .star-row {
  display: block;
  font-size: 12px;
  letter-spacing: 0.8em;
  margin-left: 0.8em;
  color: var(--gold);
}
.mascot-banner p {
  margin: 8px 0 0;
  font-family: var(--cn);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: var(--gold);
}
.mascot-banner .mantra {
  line-height: 1.9;
}
/* 每句独占一行：letter-spacing 尾隙会让居中略偏右，用 margin-left 抵消 */
.mascot-banner .mantra span {
  display: block;
  margin-left: 0.14em;
}

/* ================= 移动端（≤620px） ================= */
@media (max-width: 620px) {
  .index-view {
    gap: 16px;
  }

  /* 仪表盘 + 等级印章：桌面是「仪表 auto + 印章 1fr」两列，窄屏必须单列，
     否则 1fr 列被压到 0 宽（印章 111px 溢出行外被裁、等级描述一字一行） */
  .gauge-wrap {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    gap: 12px;
    padding: 8px 0 6px;
  }
  .gauge-meta {
    align-items: center;
    gap: 8px;
  }
  .gauge-meta .seal {
    width: 96px;
    height: 96px;
    font-size: 30px;
    border-width: 2px;
  }
  .gauge-meta .lv-desc {
    font-size: 17px;
    text-align: center;
  }
  .lv-legend {
    justify-content: center;
    gap: 8px 12px;
  }

  /* 城市标题：窄屏不再两端对齐（tag 会跑到屏幕外） */
  .city-title {
    justify-content: flex-start;
  }
  .city-title h3 {
    font-size: 20px;
  }

  /* 时间区间选择器：起/止成组换行 + 提示独占一行 */
  .range-picker {
    gap: 8px;
  }
  .range-picker .range-hint {
    flex: 1 1 100%;
  }
  .date-input,
  .hour-select {
    padding: 5px 8px;
    font-size: 12px;
  }

  /* 行动按钮：竖排铺满，扩大点按目标 */
  .actions {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .curve-tabs {
    justify-content: center;
  }

  .mascot-frame img {
    width: 168px;
  }
}
</style>
