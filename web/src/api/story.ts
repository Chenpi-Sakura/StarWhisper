import type { HealthResponse, StoryRequest, StoryResponse, StoryStreamEvent } from '../types'

export async function postStory(req: StoryRequest): Promise<StoryResponse> {
  const r = await fetch('/api/story', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<StoryResponse>
}

/** 流式总时长预算（ms）：后端也有同预算，这里前端兜底（P1-7）。 */
export const STORY_STREAM_TIMEOUT_MS = 60_000

export async function streamStory(
  req: StoryRequest,
  onEvent: (ev: StoryStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // 真 SSE：后端逐段 yield。Vue reactivity 是异步批量更新——若同步连改多个
  // ref（同一 microtask），浏览器只会渲染最后一次结果。所以每个事件回调后
  // await 一个 microtask，让 Vue 能 flush 一次重渲染，前端才会看到逐段出来。
  // 后端事件间隔本身就是 1-2 秒（AI 生成节奏），这个 microtask hop 不增加可见延迟。
  const r = await fetch('/api/story/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!r.ok || !r.body) {
    const body = (await r.json().catch(() => null)) as { detail?: { message?: string } } | null
    onEvent({ type: 'error', message: body?.detail?.message ?? `HTTP ${r.status}` })
    return
  }
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      const ev = parseSSE(frame)
      if (!ev) continue
      onEvent(ev)
      // 让 Vue 重渲染一次（microtask hop）
      await new Promise<void>((resolve) => setTimeout(resolve, 0))
    }
  }
  // 处理 buffer 末尾不完整帧
  const tail = buf.trim()
  if (tail) {
    const ev = parseSSE(tail)
    if (ev) onEvent(ev)
  }
}

function parseSSE(frame: string): StoryStreamEvent | null {
  const evLine = /^event:(.*)$/m.exec(frame)
  const dataLine = /^data:(.*)$/m.exec(frame)
  if (!dataLine) return null
  const type = (evLine?.[1] ?? '').trim()
  const data = JSON.parse(dataLine[1].trim()) as Record<string, unknown>
  if (type === 'title') return { type: 'title', title: String(data.title ?? '') }
  if (type === 'paragraph') {
    return { type: 'paragraph', index: Number(data.index ?? 0), text: String(data.text ?? '') }
  }
  if (type === 'done') return { type: 'done', meta: data as unknown as StoryResponse }
  if (type === 'reset') return { type: 'reset' }
  if (type === 'error') return { type: 'error', message: String(data.message ?? '') }
  return null
}

export async function getHealth(): Promise<HealthResponse> {
  const r = await fetch('/api/health')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<HealthResponse>
}