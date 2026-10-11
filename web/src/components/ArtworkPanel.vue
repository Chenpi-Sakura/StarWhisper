<script setup lang="ts">
/**
 * ArtworkPanel — 星纹：把 AI 故事画成一幅配图。
 *
 * 触发：故事流跑完（`story.streaming` 落 false 且正文非空）后自动发起一次
 * job 轮询。不在解算阶段并行发起，是因为 prompt 的内容就是这段故事，
 * 必须等它成形；实测故事 13.8s + 配图 32–38s，串在故事之后。
 *
 * 一次出多张候选：提示词已按五臂实验定稿（故事在前、规则在后），但单张仍有
 * 约 1/4 概率冒出星座连线或伪文字——方差是这个功能的固有属性，所以让用户
 * 挑一张，比继续调措辞有效。上游出图耗时与张数无关（n=1 与 n=4 都是 ~33s），
 * 所以多要几张只多花钱、不多等时间。
 */
import { computed, onMounted, ref, watch } from 'vue'

import { useArtworkStore } from '../stores/artwork'
import { useScanStore } from '../stores/scan'
import { useStoryStore } from '../stores/story'

const scan = useScanStore()
const story = useStoryStore()
const art = useArtworkStore()

/** 故事正文（流式累加优先，缓存命中时回退到 current.paragraphs） */
const storyText = computed(() => {
  const body = (story.streamText || (story.current?.paragraphs ?? []).join('\n\n')).trim()
  if (!body) return ''
  const title = (story.streamTitle || story.current?.title || '').trim()
  return title ? `${title}\n${body}` : body
})

/** 同一篇故事不重复烧钱；换一篇（含「重新讲述」产生新文本）才重新生成。 */
function fingerprint(text: string): string {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0
  return `${text.length}:${h >>> 0}`
}

// store 是跨组件挂载存活的：ScanView 在解算期间会卸载本组件（status 离开 done），
// 若 lastFp 从空开始，回到 done 时会对同一篇故事再发一次生成。
let lastFp =
  art.phase === 'ready' && art.storyKey ? fingerprint(art.storyKey.trim()) : ''

function maybeGenerate(): void {
  if (story.streaming || scan.loading) return
  const text = storyText.value
  if (!text) return
  const fp = fingerprint(text)
  if (fp === lastFp) return
  lastFp = fp
  void art.generate(text)
}

watch(
  () => [storyText.value, story.streaming, scan.solveId] as const,
  () => maybeGenerate(),
  { immediate: true },
)

// 换照片：清掉指纹，让新故事必然触发一次生成
watch(() => scan.solveId, () => { lastFp = '' })

// 实测上游单次出图 33–37s（与张数无关），文案按真实量级写，不写成"半分钟"
const hint = ref('正在为这段故事绘制配图，约需 40 秒')

/**
 * 上游文本审核（1026）会误杀完全正常的故事——实测同一条七夕 prompt 连打 10 次
 * 全通过，所以服务端已静默重投过一次。走到这里说明重投也没救回来，此时再点
 * 「重试」发的是同一条 prompt，不如换一篇故事。
 */
const errorAdvice = computed(() =>
  art.errorCode === 'IMAGE_UNSAFE_CONTENT'
    ? '上游把这段故事误判成了敏感内容，已自动重试过一次。可以「换一批」再赌一次，或回上面「重新讲述」换一种说法。'
    : '',
)

onMounted(() => maybeGenerate())

async function onSave(): Promise<void> {
  const url = art.current
  if (!url) return
  try {
    const r = await fetch(url)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const blob = await r.blob()
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = `starwhisper-${scan.activeAbbr ?? 'artwork'}.jpg`
    a.click()
    URL.revokeObjectURL(href)
  } catch {
    // 上游签名 URL 跨域时 fetch 会被拦掉，退化成开新窗口自行另存
    window.open(url, '_blank', 'noopener')
  }
}
</script>

<template>
  <section class="artwork-panel">
    <div class="vtabs">
      <button
        class="vtab refresh"
        type="button"
        :disabled="art.loading || !art.storyKey"
        @click="art.reroll()"
      >↻ 换一批</button>
    </div>

    <div v-if="art.loading" class="skeleton" data-testid="artwork-loading">
      <div class="frame" />
      <p>{{ hint }}</p>
    </div>

    <div v-else-if="art.phase === 'error'" class="error" data-testid="artwork-error">
      <p>配图暂不可用：{{ art.errorMessage }}</p>
      <p v-if="errorAdvice" class="advice" data-testid="artwork-error-advice">{{ errorAdvice }}</p>
      <button type="button" @click="art.reroll()">重试</button>
    </div>

    <article v-else-if="art.phase === 'ready'" class="ready" data-testid="artwork-ready">
      <div class="stage">
        <img :src="art.current ?? undefined" alt="根据本段故事生成的星纹配图" />
      </div>

      <ul v-if="art.images.length > 1" class="cands">
        <li v-for="(url, i) in art.images" :key="url + i">
          <button
            type="button"
            :class="{ on: i === art.picked }"
            :aria-label="`选用第 ${i + 1} 张候选`"
            @click="art.pick(i)"
          >
            <img :src="url" :alt="`候选 ${i + 1}`" />
          </button>
        </li>
      </ul>

      <div class="acts">
        <button type="button" @click="onSave">存图</button>
        <span class="note">艺术演绎 · AI 生成，非科学星图</span>
      </div>
    </article>
  </section>
</template>

<style scoped>
.artwork-panel {
  font-family: var(--cn);
}
.vtabs {
  display: flex;
  gap: 0;
  margin: 0 0 14px;
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
  cursor: pointer;
}
.vtab:disabled {
  opacity: 0.45;
  cursor: default;
}
.skeleton .frame {
  aspect-ratio: 16 / 9;
  max-width: 560px;
  margin: 0 auto;
  border: 1px dashed var(--line);
  background: linear-gradient(180deg, var(--paper-hi), transparent);
  animation: breathe 1.8s ease-in-out infinite alternate;
}
.skeleton p {
  margin: 12px 0 0;
  text-align: center;
  font-size: 12px;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}
@keyframes breathe {
  from { opacity: 0.45; }
  to { opacity: 0.9; }
}
.error {
  text-align: center;
  font-size: 13px;
  color: var(--ink-faint);
}
.error .advice {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-faint);
}
.error button {
  margin-top: 10px;
  background: none;
  border: 1px solid var(--line);
  padding: 6px 16px;
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.18em;
  color: var(--gold);
  cursor: pointer;
}
.stage {
  border: 1px solid var(--line);
  padding: 6px;
  background: var(--paper-hi);
}
.stage img {
  display: block;
  width: 100%;
  /* 出图改成 16:9（见 server/config.py 的 IMAGE_GEN_WIDTH/HEIGHT），
     420px 宽的方框配 16:9 只有 236px 高，太小；按新比例放宽一档。 */
  max-width: 560px;
  margin: 0 auto;
}
.cands {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.cands button {
  padding: 0;
  border: 1px solid var(--line-soft);
  background: none;
  cursor: pointer;
  line-height: 0;
}
.cands button.on {
  border-color: var(--gold);
  box-shadow: 0 0 0 2px rgba(191, 155, 78, 0.35);
}
.cands img {
  display: block;
  width: 96px;
  height: 54px;
  object-fit: cover;
}
.acts {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
}
.acts button {
  background: none;
  border: 1px solid var(--line);
  padding: 7px 18px;
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--gold);
  cursor: pointer;
}
.note {
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}
@media (max-width: 620px) {
  .stage img {
    max-width: 100%;
  }
  .acts {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
  }
}
</style>
