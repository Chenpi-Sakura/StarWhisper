<script setup lang="ts">
import { computed, ref } from 'vue'

import { useAtlasStore } from '../stores/atlas'
import type { StoryStyle } from '../types'

interface StaticStory {
  title: string
  paragraphs: string[]
}

const props = defineProps<{ tradition: string; abbr: string }>()
const atlasStore = useAtlasStore()

const views: { value: StoryStyle; label: string }[] = [
  { value: 'myth', label: '神话视角' },
  { value: 'science', label: '科普视角' },
]

const selectedView = ref<StoryStyle>('myth')

const constellation = computed(() =>
  atlasStore.atlasCache[`${props.tradition}/${props.abbr}`],
)

/**
 * 当前 (abbr, view) 对应的预设条目。
 * view 缺失时回退到首个可用 view。
 */
const currentStory = computed<StaticStory | null>(() => {
  const stories = constellation.value?.stories
  if (!stories) return null
  return stories[selectedView.value]
    ?? Object.values(stories)[0]
    ?? null
})
</script>

<template>
  <div class="atlas-story-static">
    <!-- 视角 vtabs：切换 view 切内容 -->
    <div class="vtabs">
      <button
        v-for="v in views"
        :key="v.value"
        class="vtab"
        :class="{ active: selectedView === v.value }"
        type="button"
        @click="selectedView = v.value"
      >{{ v.label }}</button>
    </div>

    <div v-if="currentStory && currentStory.paragraphs.length > 0" class="story-body" data-testid="atlas-story">
      <h3 class="story-title">{{ currentStory.title }}</h3>
      <p v-for="(p, i) in currentStory.paragraphs" :key="i" class="story-para">{{ p }}</p>
    </div>
    <div v-else-if="constellation" class="story-empty" data-testid="story-empty">
      该视角暂无内容。试试另一个视图。
    </div>
    <div v-else class="story-empty">尚未加载星图数据。</div>
  </div>
</template>

<style scoped>
.atlas-story-static {
  font-family: var(--cn);
}
.vtabs {
  display: flex;
  gap: 0;
  margin: 18px 0 0;
  /* 仿 AtlasTraditionTabs：tab 透明无背景，line 才能直接透出 */
  border-bottom: 2px solid var(--line);
}
.vtab {
  flex: 1;
  /* 关键：tab 不要 background/border，否则会盖住容器的 border-bottom */
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
/* active tab 用 ::before 在底部覆盖 2px 金条，与 AtlasTraditionTabs ::after 同款：
   视觉上「捅破」下方 line，同时标识当前选中 tab */
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

.story-body {
  margin-top: 16px;
  padding: 22px 24px;
  border: 1px solid var(--line);
  background: var(--paper-hi);
}
.story-title {
  font-family: var(--cn);
  font-weight: 900;
  font-size: 20px;
  letter-spacing: 0.14em;
  color: var(--ink);
  margin: 0 0 14px;
}
.story-para {
  font-family: var(--cn);
  font-size: 16px;
  line-height: 2.05;
  color: #3d3120;
  margin: 0 0 10px;
  text-align: justify;
}

.story-empty {
  margin-top: 18px;
  padding: 22px;
  border: 1px dashed var(--line);
  background: var(--paper-lo);
  color: var(--ink-faint);
  text-align: center;
  font-family: var(--cn);
  font-size: 13.5px;
  letter-spacing: 0.12em;
}
</style>
