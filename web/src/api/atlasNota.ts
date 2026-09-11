/**
 * 图鉴页「识读小笺 · 星座导读」AI 简介 fetch 封装（2026-09-16 新增）。
 *
 * 后端端点：
 * - `POST /api/atlas-nota`         纯非流式，一次 JSON 返回（向后兼容）
 * - `POST /api/atlas-nota/stream`  SSE 字符级流（与 /api/atlas-story/stream 同协议）
 *
 * AtlasNota 详情页主路径用流式（与 ScanView 的 StoryPanel 同套机制）：
 * - 边生成边显示，逐字累加
 * - AI 失败时后端先发 `reset` 清空半截字符，再发 caption 降级
 * - 10 分钟 LRU 缓存，degraded 不写缓存
 *
 * 保留 `fetchAtlasNota`（非流式）作为低层 API，但不供 AtlasNota 主路径使用。
 */

import type { AtlasNotaRequest, AtlasNotaResponse } from '../types'

/** 流式事件（与 story.ts 的 StoryStreamEvent 类似：title/char/done/reset/error） */
export type AtlasNotaStreamEvent =
  | { type: 'char'; char: string }
  | { type: 'done'; meta: AtlasNotaResponse }
  | { type: 'reset' }
  | { type: 'error'; message: string }

export async function fetchAtlasNota(
  req: AtlasNotaRequest,
  signal?: AbortSignal,
): Promise<AtlasNotaResponse> {
  const r = await fetch('/api/atlas-nota', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!r.ok) {
    const body = await r.json().catch(() => null) as
      | { detail?: { code?: string; message?: string } }
      | null
    throw new Error(body?.detail?.message ?? body?.detail?.code ?? `HTTP ${r.status}`)
  }
  return r.json() as Promise<AtlasNotaResponse>
}

/** 流式总时长预算（ms）：后端也有同预算，这里前端兑底。 */
export const ATLAS_NOTA_STREAM_TIMEOUT_MS = 60_000

/**
 * SSE 字符级流。与 `streamStory` 同套机制（getReader + TextDecoder + 帧解析）。
 * onEvent 逐个调用：char、reset、done、error。
 */
export async function streamAtlasNota(
  req: AtlasNotaRequest,
  onEvent: (ev: AtlasNotaStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch('/api/atlas-nota/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!r.ok || !r.body) {
    const body = (await r.json().catch(() => null)) as
      | { detail?: { code?: string; message?: string } }
      | null
    onEvent({
      type: 'error',
      message: body?.detail?.message ?? body?.detail?.code ?? `HTTP ${r.status}`,
    })
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
      const ev = parseSSENota(frame)
      if (ev) onEvent(ev)
    }
  }
  const tail = buf.trim()
  if (tail) {
    const ev = parseSSENota(tail)
    if (ev) onEvent(ev)
  }
}

function parseSSENota(frame: string): AtlasNotaStreamEvent | null {
  const evLine = /^event:(.*)$/m.exec(frame)
  const dataLine = /^data:(.*)$/m.exec(frame)
  if (!dataLine) return null
  const type = (evLine?.[1] ?? '').trim()
  const data = JSON.parse(dataLine[1].trim()) as Record<string, unknown>
  if (type === 'char') return { type: 'char', char: String(data.char ?? '') }
  if (type === 'done') return { type: 'done', meta: data as unknown as AtlasNotaResponse }
  if (type === 'reset') return { type: 'reset' }
  if (type === 'error') return { type: 'error', message: String(data.message ?? '') }
  return null
}