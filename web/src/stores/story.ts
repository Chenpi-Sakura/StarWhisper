import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { StoryRequest, StoryResponse, StoryStyle } from '../types'
import { postStory, STORY_STREAM_TIMEOUT_MS, streamStory } from '../api/story'

export const useStoryStore = defineStore('story', () => {
  const current = ref<StoryResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // P2-16：字符级流式状态——一个 streamText 字符串累加所有 char 事件（含 \n）。
  // UI 用 white-space: pre-wrap 把 \n 自然渲染成换行、\n\n 自然成段间距。
  const streaming = ref(false)
  const streamTitle = ref('')
  const streamText = ref('')
  const streamError = ref<string | null>(null)

  // P0-5：并发流竞态保护——只允许最新一个请求写 store；
  // 新请求开始前 abort 旧请求，过期响应一律丢弃。
  let activeSeq = 0
  let activeCtrl: AbortController | null = null

  /**
   * 缓存命中判定：abbr + style 两维度都匹配才命中。
   */
  function isHit(abbr: string, style: StoryStyle): boolean {
    const s = current.value
    if (s == null || s.degraded) return false
    if (s.abbr !== abbr) return false
    return s.style === style
  }

  async function fetchStory(
    abbr: string,
    style: StoryStyle,
    action: 'refetch' | 'fresh',
  ): Promise<void> {
    if (action === 'refetch' && isHit(abbr, style)) return

    loading.value = true
    error.value = null
    try {
      const req: StoryRequest = { abbr, style, lang: 'zh' }
      if (action === 'fresh') req.cacheBust = 1
      current.value = await postStory(req)
    } catch (e) {
      error.value = (e as Error).message
      current.value = null
    } finally {
      loading.value = false
    }
  }

  /**
   * P2-16 字符级流：后端逐字 yield event:char，前端 streamText 字符串累积；
   * UI 把 \n 自然渲染成换行、\n\n 自然成段间距；不再有段落数组结构。
   * 调用方显式带 tradition 则透传，否则缺省 = 后端按首命中兜底。
   */
  async function fetchStoryStream(
    abbr: string,
    style: StoryStyle,
    action: 'refetch' | 'fresh' = 'fresh',
    tradition?: string,
  ): Promise<StoryResponse> {
    // 缓存命中：current 已经是完整数据，直接返回——不走流式、不动
    // streamTitle/streamText。StoryPanel 的 displayParagraphs 会在
    // streamText 为空时回退到 current.paragraphs 一次性渲染。
    if (action === 'refetch' && isHit(abbr, style)) {
      return current.value as StoryResponse
    }

    // P0-5：中止上一个还在跑的流（连点视角 tab / 快速切星座时，
    // 两个 SSE 往同一字符串 push 会字符交错）
    activeSeq += 1
    const mySeq = activeSeq
    activeCtrl?.abort()
    const ctrl = new AbortController()
    activeCtrl = ctrl

    // P1-7：前端端到端总时长兜底（后端 STORY_TOTAL_TIMEOUT 同预算）
    const timer = setTimeout(() => ctrl.abort(new Error('故事生成超时')), STORY_STREAM_TIMEOUT_MS)

    streaming.value = true
    streamError.value = null
    streamTitle.value = ''
    streamText.value = ''
    error.value = null
    // P0-4：清掉旧星座故事，避免新流首屏先渲染上一个星座的内容
    current.value = null

    const req: StoryRequest = { abbr, style, lang: 'zh' }
    if (tradition) req.tradition = tradition
    if (action === 'fresh') req.cacheBust = 1

    let finalMeta: StoryResponse | null = null

    try {
      await streamStory(req, (ev) => {
        // P0-5：过期请求的迟到事件不得写入 store
        if (mySeq !== activeSeq) return
        if (ev.type === 'title') {
          streamTitle.value = ev.title
        } else if (ev.type === 'char') {
          // 字符串拼接：Vue 异步批量更新，多 char 在同一 microtask 合并为一次重渲染
          streamText.value += ev.char
        } else if (ev.type === 'done') {
          finalMeta = ev.meta
          current.value = ev.meta
        } else if (ev.type === 'reset') {
          // P0-3：后端降级前先发 reset——清空半截 AI 字符，等 preset 全量重放
          streamTitle.value = ''
          streamText.value = ''
        } else if (ev.type === 'error') {
          streamError.value = ev.message
        }
      }, ctrl.signal)
    } catch (e) {
      // P0-5：被新请求 abort（而非超时）→ 静默丢弃，不写错误状态
      if (mySeq === activeSeq) {
        streamError.value = (e as Error).message
      }
    } finally {
      clearTimeout(timer)
      if (mySeq === activeSeq) {
        streaming.value = false
        if (activeCtrl === ctrl) activeCtrl = null
      }
    }

    if (mySeq !== activeSeq) {
      // 已被更新的请求取代：不抛错、不返回，由新请求负责收尾
      throw new DOMException('Aborted', 'AbortError')
    }
    if (streamError.value) throw new Error(streamError.value)
    if (!finalMeta) {
      throw new Error(streamError.value ?? '故事流未完成')
    }
    return finalMeta
  }

  function clear() {
    activeSeq += 1
    activeCtrl?.abort()
    activeCtrl = null
    current.value = null
    error.value = null
    streaming.value = false
    streamTitle.value = ''
    streamText.value = ''
    streamError.value = null
  }

  return {
    current, loading, error,
    streaming, streamTitle, streamText, streamError,
    isHit, fetchStory, fetchStoryStream, clear,
  }
})