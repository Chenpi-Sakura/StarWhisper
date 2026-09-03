<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { useScanStore } from '../stores/scan'
import { useStoryStore } from '../stores/story'
import type { StoryStyle } from '../types'

const scan = useScanStore()
const story = useStoryStore()

const props = defineProps<{ abbr: string }>()

/** 视角 tab（神话 / 科普）— 后端 style 字段 */
const views: { value: StoryStyle; label: string }[] = [
  { value: 'myth', label: '神话视角' },
  { value: 'science', label: '科普视角' },
]

const state = computed<'loading' | 'degraded' | 'ready'>(() => {
  if (story.error || story.streamError) return 'degraded'
  // P0-4：流式进行中——已有内容才进 ready（打字机），还没有首段则先出骨架屏
  const hasStreamContent = Boolean(story.streamTitle) || story.streamParagraphs.length > 0
  if (story.streaming) return hasStreamContent ? 'ready' : 'loading'
  if (
    story.current &&
    story.current.abbr === props.abbr &&
    story.current.style === scan.selectedStyle
  ) {
    return 'ready'
  }
  return 'loading'
})

// 打字机流式优先；无流式内容（缓存/degraded 一次性返回）时取 current.paragraphs
const displayTitle = computed(() => story.streamTitle || story.current?.title || '')
const displayParagraphs = computed(() => {
  const streamed = story.streamParagraphs.map((p) => p.text)
  if (streamed.length > 0) return streamed
  return story.current?.paragraphs ?? []
})

watch(
  () => [props.abbr, scan.selectedStyle] as const,
  async ([abbr, style]) => {
    if (!abbr) return
    try {
      await story.fetchStoryStream(abbr, style as StoryStyle, 'refetch')
    } catch (e) {
      // 被更新的请求 abort（P0-5）属正常流程，静默；其余只记日志不上屏
      if ((e as Error).name !== 'AbortError') console.error('[StoryPanel]', e)
    }
  },
  { immediate: true },
)

async function onViewChange(view: StoryStyle) {
  // 只改 scan.selectedStyle；watch 会随后自动触发 fetchStoryStream refetch。
  if (!props.abbr) return
  scan.setStyle(view)
}

async function onRefresh() {
  if (!props.abbr) return
  try {
    await story.fetchStoryStream(
      props.abbr,
      scan.selectedStyle,
      'fresh',
    )
  } catch (e) {
    if ((e as Error).name !== 'AbortError') console.error('[StoryPanel]', e)
  }
}
</script>

<template>
  <section class="story-panel">
    <!-- 视角 vtabs -->
    <div class="vtabs">
      <button
        v-for="v in views"
        :key="v.value"
        class="vtab"
        :class="{ active: scan.selectedStyle === v.value }"
        type="button"
        @click="onViewChange(v.value)"
      >{{ v.label }}</button>
      <button
        class="vtab refresh"
        :disabled="story.loading || story.streaming"
        type="button"
        @click="onRefresh"
      >↻ 重新讲述</button>
    </div>

    <!-- P0-4：流式进行中（有内容即打字机）或缓存命中都渲染正文；
         首屏流式尚未出首段时走骨架屏，不再出现三分支全落空的空白 -->
    <article v-if="state === 'ready'" class="ready" data-testid="story-ready">
      <h2>{{ displayTitle }}</h2>
      <p v-for="(p, i) in displayParagraphs" :key="i">{{ p }}</p>
      <p
        v-if="story.current?.degraded"
        class="badge-offline"
        :title="story.current.degraded_reason ?? ''"
      >离线故事</p>
    </article>

    <div v-else-if="state === 'degraded'" class="degraded" data-testid="story-degraded">
      <p>故事生成暂不可用：{{ story.error || story.streamError }}</p>
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
.vtabs {
  display: flex;
  gap: 0;
  margin: 0;
  border: 1px solid var(--line);
  border-bottom: none;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  background: var(--paper-hi);
  z-index: 1;
}
.vtab {
  flex: 1;
  background: #efe4c4;
  border: none;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 10px 0 8px;
  font-family: var(--cn);
  font-size: 14px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
  transition: 0.25s;
  position: relative;
  cursor: pointer;
}
.vtab:last-child {
  border-right: none;
}
.vtab.active {
  background: var(--paper-hi);
  color: var(--ink);
  font-weight: 700;
  z-index: 2;
  /* 选中态不改变底边线：与未选中保持一致 */
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

.degraded {
  margin-top: 14px;
  padding: 16px 18px;
  border: 1px solid rgba(156, 59, 42, 0.45);
  background: rgba(156, 59, 42, 0.07);
  color: #7a2f20;
  flex-shrink: 0;
}

.ready {
  margin-top: 14px;
  padding: 22px 26px;
  border: 1px solid var(--line);
  background: var(--paper-hi);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.ready h2 {
  font-family: var(--cn);
  font-weight: 900;
  font-size: 22px;
  letter-spacing: 0.16em;
  margin: 0 0 14px;
  color: var(--ink);
}
.ready p {
  font-family: var(--cn);
  font-size: 16px;
  line-height: 2.15;
  color: #3d3120;
  margin: 0 0 12px;
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
