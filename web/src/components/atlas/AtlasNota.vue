<script setup lang="ts">
/**
 * 图鉴页 · 识读小笺（NOTA 板）组件
 *
 * 取代原 <PlateBox caption="识读小笺"> 的内联空壳（ConstellationView.vue:181-190）。
 * 三段式：
 *   § 你是谁      —— 名称 + 4 个数据 chip（season / hemisphere / glyph / bright_stars）
 *   § 怎么找你    —— 最亮 3 颗星 + 中西对照（按 name_zh vs name 收集）
 *   § 星座简介    —— 状态机：idle / loading / ready / error（commit C 仅有 idle 占位）
 *
 * 底部 3 个 chip：
 *   - 切换视角（commit F 接 → .tradition-tabs scrollIntoView）
 *   - 重新讲述（commit F 接 → 已 ready 时重发 onGenerate()）
 *   - 生成分享卡（commit F + E 接 → showShareCard=true，<AtlasShareCard> 挂载）
 *
 * 设计决策见 docs/plans/2026-09-16-atlas-nota-ai.md §3 / §7。
 */
import { computed, ref, watch } from 'vue'
import type { ConstellationAtlas, Hemisphere } from '../../types'
import { streamAtlasNota, ATLAS_NOTA_STREAM_TIMEOUT_MS } from '../../api/atlasNota'
import AtlasShareCard from './AtlasShareCard.vue'
import StarBtn from '../common/StarBtn.vue'
import StarChip from '../common/StarChip.vue'

const props = defineProps<{ constellation: ConstellationAtlas }>()

// ============= § 你是谁 =============

function hemisphereLabel(h?: Hemisphere): string | null {
  if (h === 'N') return '北天'
  if (h === 'S') return '南天'
  if (h === 'B') return '跨天球'
  return null
}

interface WhoChip {
  key: string
  label: string
  variant?: 'gold' | 'default'
}

/** 你是谁段的 4 个数据 chip——任一字段缺则不渲染该 chip */
const whoChips = computed<WhoChip[]>(() => {
  const c = props.constellation
  const chips: WhoChip[] = []
  if (c.season) chips.push({ key: 'season', label: `当令 ${c.season}` })
  const hem = hemisphereLabel(c.hemisphere)
  if (hem) chips.push({ key: 'hemisphere', label: hem })
  if (c.glyph) chips.push({ key: 'glyph', label: `拜耳 ${c.glyph}`, variant: 'gold' })
  if (c.bright_stars != null) {
    chips.push({ key: 'bright', label: `最亮 ${c.bright_stars} 颗`, variant: 'gold' })
  }
  return chips
})

// ============= § 怎么找你 =============

/** 按 magnitude 升序取前 3 颗（数字星等小者更亮） */
const brightestStars = computed(() => {
  const stars = props.constellation?.stars
  if (!stars) return []
  return Object.values(stars)
    .filter((s) => Number.isFinite(s.magnitude))
    .sort((a, b) => a.magnitude - b.magnitude)
    .slice(0, 3)
})

/** 中西对照：name_zh 存在且与 name 不同 → 收集成去重列表 */
const crossRefs = computed<string[]>(() => {
  const stars = props.constellation?.stars
  if (!stars) return []
  const set = new Set<string>()
  for (const s of Object.values(stars)) {
    if (s.name_zh && s.name && s.name_zh !== s.name) set.add(s.name_zh)
  }
  return Array.from(set)
})

/** 该段是否有任何可见内容（亮星 + 中西对照）；都没有则显兜底 */
const howToFindEmpty = computed(
  () => brightestStars.value.length === 0 && crossRefs.value.length === 0,
)

// ============= § 星座简介 =============
// commit D：状态机 idle / loading / ready / error，接 /api/atlas-nota。
type IntroStatus = 'idle' | 'loading' | 'ready' | 'error'

interface IntroState {
  status: IntroStatus
  text: string
  degraded: boolean
  source: string | null
}

const introState = ref<IntroState>({
  status: 'idle',
  text: '',
  degraded: false,
  source: null,
})

/** 跳选中星座/切 tradition 都重置为 idle（不继承上一段的简介） */
watch(
  () => `${props.constellation?.abbr ?? ''}|${props.constellation?.tradition ?? ''}`,
  () => {
    introState.value = { status: 'idle', text: '', degraded: false, source: null }
  },
)

/** SSE 流控制器（连续点“讲讲/重新讲述”时取消上一个） */
let activeCtrl: AbortController | null = null
let activeSeq = 0

async function onGenerate(): Promise<void> {
  const c = props.constellation

  // 取消上一轮在飞的流，连点不会被半截旧字符覆盖
  activeSeq += 1
  const mySeq = activeSeq
  activeCtrl?.abort()
  const ctrl = new AbortController()
  activeCtrl = ctrl

  // P1-7：前端兑底总时长（后端 STORY_TOTAL_TIMEOUT 同预算）
  const timer = setTimeout(
    () => ctrl.abort(new Error('故事生成超时')),
    ATLAS_NOTA_STREAM_TIMEOUT_MS,
  )

  introState.value = { status: 'loading', text: '', degraded: false, source: null }

  try {
    await streamAtlasNota(
      {
        abbr: c.abbr,
        tradition: c.tradition ?? 'western',
        lang: 'zh',
      },
      (ev) => {
        // P0-5：过期请求的迟到事件不得写入状态
        if (mySeq !== activeSeq) return
        if (ev.type === 'char') {
          introState.value = {
            ...introState.value,
            status: 'loading',  // 还未 done，保持 loading 状态让用户看到按钮
            text: introState.value.text + ev.char,
          }
        } else if (ev.type === 'reset') {
          // AI 失败、后端准备发降级 caption——清空半截 AI 字符
          introState.value = { status: 'loading', text: '', degraded: false, source: null }
        } else if (ev.type === 'done') {
          introState.value = {
            status: 'ready',
            text: ev.meta.intro,
            degraded: ev.meta.degraded,
            source: ev.meta.source,
          }
        } else if (ev.type === 'error') {
          introState.value = {
            status: 'error',
            text: '暂无法访问 AI，请稍后再试。',
            degraded: false,
            source: null,
          }
        }
      },
      ctrl.signal,
    )
  } catch (e) {
    if (mySeq === activeSeq) {
      introState.value = {
        status: 'error',
        text: '暂无法访问 AI，请稍后再试。',
        degraded: false,
        source: null,
      }
      void e
    }
  } finally {
    clearTimeout(timer)
    if (mySeq === activeSeq && activeCtrl === ctrl) {
      activeCtrl = null
    }
  }
}

const introAuthorLabel = computed(() => {
  if (introState.value.degraded) return 'AI 暂不可用，降级'
  return 'Agent Arts'
})

// ============= 底部 chip =============
// commit D：chip 接线
//   - 重新讲述 → 等价于讲讲按钮（ready 时也重新发请求，服务端去重缓存）
//   - 生成分享卡 → 设 showShareCard = true（commit E 挂载 <AtlasShareCard>）
function onRetell(): void {
  void onGenerate()
}
const showShareCard = ref(false)
function onShare(): void {
  showShareCard.value = true
}

/** 分享卡生成功后或失败后，重置 flag 以便下一次能再次触发下载 */
function onShareDone(): void {
  showShareCard.value = false
}
function onShareError(_msg: string): void {
  showShareCard.value = false
}
</script>

<template>
  <section class="atlas-nota" data-testid="atlas-nota">
    <!-- § 你是谁 -->
    <div class="nota-section">
      <div class="nota-section-title">— 你是谁 —</div>
      <h4 class="nota-name">
        <span class="zh">{{ constellation.name }}</span>
        <span class="latin">{{ constellation.latin }}</span>
      </h4>
      <div v-if="whoChips.length > 0" class="nota-chips">
        <StarChip
          v-for="chip in whoChips"
          :key="chip.key"
          :label="chip.label"
          :variant="chip.variant ?? 'default'"
        />
      </div>
      <p v-else class="nota-empty">该星座信息暂未补全。</p>
    </div>

    <!-- § 怎么找你 -->
    <div class="nota-section">
      <div class="nota-section-title">— 怎么找你 —</div>
      <ul v-if="!howToFindEmpty" class="nota-list">
        <li v-for="(star, idx) in brightestStars" :key="idx">
          ◆ 找 <b>{{ star.name ?? '—' }}</b>
          <span v-if="star.bayer" class="mono">（{{ star.bayer }}）</span>
          ，星等 <b>{{ star.magnitude.toFixed(1) }}ᵐ</b>
        </li>
        <li v-if="crossRefs.length > 0">
          ◆ 中西对照：{{ constellation.name }} ↔ {{ crossRefs.join(' / ') }}（部分星）
        </li>
      </ul>
      <p v-else class="nota-empty">请打开夜空，去寻一方属于你的星座。</p>
    </div>

    <!-- § 星座简介：状态机 idle / loading / ready / error -->
    <div class="nota-section">
      <div class="nota-section-title">— 星座简介 —</div>
      <div class="nota-intro">
        <!-- idle: 讲讲按钮（删除了之前的提示文案“点一下，让 AgentArts 给你讲讲 ...”） -->
        <template v-if="introState.status === 'idle'">
          <StarBtn
            label="✦ 讲讲这个星座"
            variant="gold"
            data-testid="nota-btn-generate"
            @click="onGenerate"
          />
        </template>

        <!-- loading: 显示已流到的字符 + disable 按钮 -->
        <template v-else-if="introState.status === 'loading'">
          <p
            v-if="introState.text"
            class="nota-body nota-body-streaming"
            data-testid="nota-intro-streaming"
          >{{ introState.text }}<span class="nota-cursor">▌</span></p>
          <StarBtn label="✦ 正在讲述…" variant="gold" disabled />
        </template>

        <!-- ready: 简介正文 + 署名 + 重讲链接 -->
        <template v-else-if="introState.status === 'ready'">
          <p class="nota-body" data-testid="nota-intro-body">{{ introState.text }}</p>
          <p class="nota-meta">
            — {{ introAuthorLabel }} 创作 · {{ new Date().toISOString().slice(0, 10) }}
            <a
              class="nota-relink"
              data-testid="nota-relink"
              @click.prevent="onGenerate"
            >↻ 重新讲述</a>
          </p>
        </template>

        <!-- error: 降级文字 + 重试按钮 -->
        <template v-else>
          <p class="nota-error">{{ introState.text }}</p>
          <StarBtn label="↻ 重试" variant="ghost" @click="onGenerate" />
        </template>
      </div>
    </div>

    <!-- 底部 2 chip（切换视角 chip 已删除，commit L） -->
    <div class="nota-foot">
      <StarChip label="重新讲述" @click="onRetell" />
      <StarChip variant="gold" label="生成分享卡" @click="onShare" />
    </div>

    <!-- 离屏分享卡渲染器：showShareCard false→true 触发下载 -->
    <AtlasShareCard
      v-if="showShareCard"
      :constellation="constellation"
      :intro="introState.text"
      :show-share-card="showShareCard"
      @done="onShareDone"
      @error="onShareError"
    />
  </section>
</template>

<style scoped>
.atlas-nota {
  font-family: var(--cn);
  color: var(--ink);
}

.nota-section {
  margin: 14px 0;
}

.nota-section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 12px;
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.22em;
  color: var(--gold);
  font-weight: 700;
}
.nota-section-title::before,
.nota-section-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--line-soft), transparent);
  opacity: 0.7;
}
.nota-section-title::after {
  background: linear-gradient(90deg, transparent, var(--line-soft));
}

/* .nota-sep 已不再使用（页面上不要段间分隔线，仅靠标题自带 fade 线） */

/* § 你是谁 */
.nota-name {
  margin: 0 0 12px;
  font-family: var(--cn);
  font-weight: 900;
  letter-spacing: 0.14em;
  line-height: 1.3;
}
.nota-name .zh {
  font-size: 22px;
  color: var(--ink);
  margin-right: 8px;
}
.nota-name .latin {
  font-family: var(--disp);
  font-size: 13px;
  letter-spacing: 0.32em;
  color: var(--gold);
  font-weight: 500;
}
.nota-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* § 怎么找你 */
.nota-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-family: var(--cn);
  font-size: 13.5px;
  line-height: 1.95;
  color: var(--ink-soft);
}
.nota-list li {
  padding: 2px 0;
}
.nota-list li b {
  color: var(--ink);
  font-weight: 700;
}
.nota-list .mono {
  font-family: var(--disp);
  font-size: 12px;
  color: var(--gold);
  letter-spacing: 0.06em;
  margin: 0 2px;
}

/* § 星座简介 */
.nota-intro {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}
.nota-hint {
  /* 已不再使用（提示文案被删除），但保留选择器防 jinjia 误报未使用。 */
  display: none;
}
.nota-body {
  font-size: 14.5px;
  line-height: 1.95;
  color: var(--ink);
  margin: 4px 0 0;
  white-space: pre-wrap;
}
.nota-body-streaming {
  font-family: var(--cn);
}
.nota-cursor {
  display: inline-block;
  margin-left: 1px;
  color: var(--gold);
  animation: nota-blink 1s steps(2, start) infinite;
}
@keyframes nota-blink {
  to { visibility: hidden; }
}
.nota-meta {
  font-family: var(--cn);
  font-size: 11.5px;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
  margin: 4px 0 0;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.nota-relink {
  font-family: var(--cn);
  font-size: 12px;
  color: var(--gold);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 3px;
}
.nota-relink:hover {
  color: var(--ink);
}
.nota-error {
  font-size: 13px;
  color: var(--seal);
  margin: 0;
  letter-spacing: 0.06em;
}

/* § 兜底 */
.nota-empty {
  font-size: 12.5px;
  color: var(--ink-faint);
  font-style: italic;
  margin: 0;
  letter-spacing: 0.06em;
}

/* 底部 chip */
.nota-foot {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
</style>