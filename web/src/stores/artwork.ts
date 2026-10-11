import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  ARTWORK_DEADLINE_MS,
  ARTWORK_POLL_INTERVAL_MS,
  ArtworkApiError,
  pollArtwork,
  startArtwork,
} from '../api/artwork'

export type ArtworkPhase = 'idle' | 'loading' | 'ready' | 'error'

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 星纹配图状态机。
 *
 * 上游是同步接口且单次 ~33s（与张数无关），所以走「POST 起 job → GET 轮询」。
 * 一次拿回多张候选（后端 IMAGE_GEN_N）：实测提示词再怎么调，单张仍有约
 * 1/4 概率画出星座连线或伪文字，因此把选择权交给用户而不是继续调模板。
 *
 * 竞态保护沿用 story store 的 seq 方案：新请求会让旧轮询循环静默退出，
 * 过期结果一律不写回 store。
 */
export const useArtworkStore = defineStore('artwork', () => {
  const phase = ref<ArtworkPhase>('idle')
  const images = ref<string[]>([])
  const picked = ref(0)
  const cached = ref(false)
  const model = ref('')
  const errorCode = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  /** 最近一次提交的故事正文，供「换一批」复用（不必让 UI 再传一遍） */
  const storyKey = ref('')

  let seq = 0

  const loading = computed(() => phase.value === 'loading')
  const current = computed<string | null>(() => images.value[picked.value] ?? null)

  async function generate(story: string, opts: { bust?: boolean } = {}): Promise<void> {
    const text = story.trim()
    if (!text) return

    const mySeq = ++seq
    phase.value = 'loading'
    images.value = []
    picked.value = 0
    cached.value = false
    model.value = ''
    errorCode.value = null
    errorMessage.value = null
    storyKey.value = text

    try {
      const start = await startArtwork(text, !!opts.bust)
      const deadline = Date.now() + ARTWORK_DEADLINE_MS
      let job = null
      for (;;) {
        if (mySeq !== seq) return
        job = await pollArtwork(start.job_id)
        if (job.status !== 'pending') break
        if (Date.now() > deadline) {
          throw new ArtworkApiError('ARTWORK_TIMEOUT', '生成超时，请稍后再试')
        }
        await sleep(ARTWORK_POLL_INTERVAL_MS)
      }
      if (mySeq !== seq) return

      if (job.status === 'error') {
        errorCode.value = job.error_code ?? 'ARTWORK_FAILED'
        errorMessage.value = job.error_message ?? '生成失败'
        phase.value = 'error'
        return
      }
      images.value = job.images
      model.value = job.model
      cached.value = job.cached
      if (images.value.length === 0) {
        errorCode.value = 'ARTWORK_EMPTY'
        errorMessage.value = '没有拿到可用配图'
        phase.value = 'error'
        return
      }
      phase.value = 'ready'
    } catch (e) {
      if (mySeq !== seq) return
      const err = e as ArtworkApiError
      errorCode.value = err.code ?? 'ARTWORK_FAILED'
      errorMessage.value = err.message ?? '生成失败'
      phase.value = 'error'
    }
  }

  /** 「换一批」：同一故事重新向上游要一组候选，必须绕过后端 prompt 缓存。 */
  function reroll(): void {
    if (storyKey.value) void generate(storyKey.value, { bust: true })
  }

  function pick(index: number): void {
    if (index >= 0 && index < images.value.length) picked.value = index
  }

  function reset(): void {
    seq += 1
    phase.value = 'idle'
    images.value = []
    picked.value = 0
    cached.value = false
    model.value = ''
    errorCode.value = null
    errorMessage.value = null
    storyKey.value = ''
  }

  return {
    phase, images, picked, cached, model, errorCode, errorMessage, storyKey,
    loading, current, generate, reroll, pick, reset,
  }
})
