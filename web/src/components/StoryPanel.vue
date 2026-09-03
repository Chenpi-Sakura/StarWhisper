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
  // P2-16：字符级流式——已有内容（任意 char / title）即进 ready（打字机）。
  // 还没有任何内容时仍先出骨架屏（首屏白闪规避）。
  const hasStreamContent = Boolean(story.streamTitle) || story.streamText.length > 0
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

// P2-16 字符级：流式时把 streamText（单字符串含 \n）一次性渲染；缓存命中则用
// current.paragraphs 拼回（段落间补 \n\n，与服务端 yield 一致）。
const displayTitle = computed(() => story.streamTitle || story.current?.title || '')
const displayText = computed(() => {
  if (story.streamText.length > 0) return story.streamText
  const paras = story.current?.paragraphs
  return paras && paras.length > 0 ? paras.join('\n\n') : ''
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

    <!-- P2-16 字符级：单 div + white-space: pre-wrap 把 \n 自然渲染成换行、\n\n
         成段间距；保持原 text-align/line-height/font 视觉风格。 -->
    <article v-if="state === 'ready'" class="ready" data-testid="story-ready">
      <h2>{{ displayTitle }}</h2>
      <div class="story-body">{{ displayText }}</div>
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

.degraded {
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
