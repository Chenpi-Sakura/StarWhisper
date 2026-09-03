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
  // P2-16：字符级 SSE——同一 read() 内可能塞多个事件（典型 AI 流），交给 Vue
  // 自然 microtask flush 即可；下一次 await reader.read() 之间浏览器必 flush。
  // 原 paragraph-level 协议下每个事件手动 await setTimeout(0) 是为了逐段可见；
  // 现在单 char 不需要 hop（人眼看不见单个字），hop 反而成性能瓶颈（200+ 字/篇）。
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
      if (ev) onEvent(ev)
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
  // P2-16：字符级事件——逐字 char 流入前端
  if (type === 'char') return { type: 'char', char: String(data.char ?? '') }
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