<script setup lang="ts">
import { computed, watch } from 'vue'

import { useScanStore } from '../stores/scan'
import { useStoryStore } from '../stores/story'
import type { PhotoConstellation, PhotoStar, PhotoStoryContext } from '../types'

const scan = useScanStore()
const story = useStoryStore()

// 本期（spec §4.1）：不再有 abbr prop / 视角 tabs；
// 触发键 = scanStore.solveId（每次新 solve 完成刷新一次）。

const state = computed<'loading' | 'error' | 'ready'>(() => {
  if (story.error || story.streamError) return 'error'
  const hasContent = Boolean(story.streamTitle) || story.streamText.length > 0
  if (story.streaming) return hasContent ? 'ready' : 'loading'
  // streamText 已有内容（流已结束但 store 还没清空）→ 视为 ready，
  // 即便后端 done 事件载荷缺 style 字段也不应该回退到 loading。
  if (hasContent) return 'ready'
  if (story.current && story.current.style === scan.selectedStyle) return 'ready'
  return 'loading'
})

const displayTitle = computed(() => story.streamTitle || story.current?.title || '')
const displayText = computed(() => {
  if (story.streamText.length > 0) return story.streamText
  // I1：缓存命中（refetch + style 匹配）时 streamText 为空，
  // 但 current 里有完整 paragraphs；这里兜底让 UI 不会短暂空。
  return story.current?.paragraphs?.join('\n\n') ?? ''
})

function buildContext(): PhotoStoryContext | null {
  const r = scan.result
  if (!r) return null
  const constellations: PhotoConstellation[] = (r.constellations ?? []).map((c) => ({
    abbr: c.abbr,
    tradition: (c.tradition ?? 'western') as 'western' | 'chinese',
    name: c.name,
    latin: c.latin,
    confidence: c.confidence,
  }))
  const bright_stars: PhotoStar[] = (r.stars_overlay ?? []).map((s) => ({
    bayer: s.bayer,
    name: s.name,
    name_zh: s.name_zh,
    magnitude: s.magnitude,
    // Task 5 review ruling：s.constellations 是 optional，必须 ?? [] 兜底防 narrowing trap
    constellations: s.constellations ?? [],
  }))
  return {
    constellations,
    bright_stars,
    // SolveResult 用 ra/dec 直接平铺（spec §3.1）+ field_width/field_height（snake_case）
    center: r.ra != null && r.dec != null ? { ra: r.ra, dec: r.dec } : undefined,
    field: r.field_width != null && r.field_height != null
      ? { width_deg: r.field_width, height_deg: r.field_height }
      : undefined,
  }
}

watch(
  () => scan.solveId,
  async (sid) => {
    if (!sid) return
    const ctx = buildContext()
    if (!ctx) return
    try {
      await story.fetchPhotoStory(ctx, scan.selectedStyle, 'refetch')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') console.error('[StoryPanel]', e)
    }
  },
  { immediate: true },
)

async function onRefresh() {
  const ctx = buildContext()
  if (!ctx) return
  try {
    await story.fetchPhotoStory(ctx, scan.selectedStyle, 'fresh')
  } catch (e) {
    if ((e as Error).name !== 'AbortError') console.error('[StoryPanel]', e)
  }
}
</script>

<template>
  <section class="story-panel">
    <!-- 本期：仅 refresh tab（spec §4.1：style tabs 移除） -->
    <div class="vtabs">
      <button
        class="vtab refresh"
        :disabled="story.loading || story.streaming"
        type="button"
        @click="onRefresh"
      >↻ 重新讲述</button>
    </div>

    <article v-if="state === 'ready'" class="ready" data-testid="story-ready">
      <h2>{{ displayTitle }}</h2>
      <div class="story-body">{{ displayText }}</div>
    </article>

    <div v-else-if="state === 'error'" class="error" data-testid="story-error">
      <p>故事暂不可用：{{ story.error || story.streamError }}</p>
      <button @click="onRefresh">重试</button>
    </div>

    <div v-else class="skeleton" data-testid="story-loading">
      <div class="bar title" />
      <div class="bar" />
      <div class="bar short" />
    </div>
  </section>
</template>

<style scoped>
.story-panel {
  font-family: var(--cn);
}
/* P2-16：vtabs 与 AtlasStoryStatic / AtlasTraditionTabs 统一为「line-style」——
   透明背景 + 底部 2px line + active 用 ::before 金条覆盖；
   去掉了原来 plate-style 的 sticky top / paper-hi 切换，与 atlas 视觉语言对等 */
.vtabs {
  display: flex;
  gap: 0;
  margin: 0;
  border-bottom: 2px solid var(--line);
  flex-shrink: 0;
}
.vtab {
  flex: 1;
  background: none;
  border: none;
  padding: 10px 0;
  font-family: var(--cn);
  font-size: 14px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
  transition: 0.25s;
  position: relative;
  cursor: pointer;
}
.vtab.active {
  color: var(--ink);
  font-weight: 700;
  z-index: 2;
}
.vtab.active::before {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gold);
  z-index: 3;
}
.vtab.active::after {
  content: '✦';
  position: absolute;
  top: -9px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--gold);
}
.vtab.refresh {
  flex: 0 0 auto;
  padding: 10px 18px;
  font-size: 12.5px;
  letter-spacing: 0.14em;
  color: var(--ink-soft);
  /* 与普通 tab 同一底边线：金条覆盖只在 active 的两个视角 tab 上呈现 */
  border-left: 1px dashed var(--line);
}
.vtab.refresh:hover:not(:disabled) {
  color: var(--ink);
}
.vtab.refresh:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.skeleton {
  margin-top: 14px;
  padding: 22px 24px;
  border: 1px solid var(--line-soft);
  background: var(--paper-hi);
  flex-shrink: 0;
}
.skeleton .bar {
  height: 0.8rem;
  background: #eee;
  margin: 0.6rem 0;
  border-radius: 4px;
}
.skeleton .bar.title {
  width: 40%;
  height: 1.4rem;
}
.skeleton .bar.short {
  width: 60%;
}

.error {
  margin-top: 14px;
  padding: 16px 18px;
  border: 1px solid rgba(156, 59, 42, 0.45);
  background: rgba(156, 59, 42, 0.07);
  color: #7a2f20;
  flex-shrink: 0;
}

.ready {
  /* P2-16：与 AtlasStoryStatic .story-body 视觉对等——同样 padding / border / bg */
  margin-top: 16px;
  padding: 22px 24px;
  border: 1px solid var(--line);
  background: var(--paper-hi);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.ready h2 {
  /* P2-16：与 AtlasStoryStatic .story-title 对齐 */
  font-family: var(--cn);
  font-weight: 900;
  font-size: 20px;
  letter-spacing: 0.14em;
  margin: 0 0 14px;
  color: var(--ink);
}
/* P2-16 字符级渲染：单 div + white-space: pre-wrap 让 \n 自然换行、\n\n 自然段间距；
   保留原字号/行距/字色/对齐，与 AtlasStoryStatic .story-body 视觉对等。 */
.ready .story-body {
  font-family: var(--cn);
  font-size: 16px;
  line-height: 2.05;
  color: #3d3120;
  text-align: justify;
  white-space: pre-wrap;
  word-break: break-word;
  animation: fade-in 0.5s ease;
}
.ready p {
  /* 兼容旧的 displayParagraphs 路径（如 atlas StoryStatic 复用本组件） */
  font-family: var(--cn);
  font-size: 16px;
  line-height: 2.05;
  color: #3d3120;
  margin: 0 0 10px;
  text-align: justify;
  animation: fade-in 0.5s ease;
}
.ready .badge-offline {
  color: var(--seal);
  font-size: 0.85rem;
  margin-top: 0.5rem;
}
@keyframes fade-in {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: none; }
}
</style>
