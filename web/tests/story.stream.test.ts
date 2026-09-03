import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useStoryStore } from '../src/stores/story'
import type { StoryResponse } from '../src/types'

function makeSSEResponse(frames: string[]): Response {
  const body = frames.join('\n\n') + '\n\n'
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

const sampleMeta: StoryResponse = {
  ok: true, abbr: 'ori', style: 'myth', title: 'T', paragraphs: ['p1', 'p2'],
  provider: 'mock', model: 'm', latency_ms: 1, cached: false, degraded: false,
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('fetchStoryStream SSE 聚合', () => {
  it('title → paragraph ×N → done 聚合到 current', async () => {
    const frames = [
      'event: title\ndata: {"title":"猎户神话"}',
      'event: paragraph\ndata: {"index":0,"text":"第一段"}',
      'event: paragraph\ndata: {"index":1,"text":"第二段"}',
      `event: done\ndata: ${JSON.stringify(sampleMeta)}`,
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))

    const story = useStoryStore()
    await story.fetchStoryStream('ori', 'myth', 'fresh')
    expect(story.current).toEqual(sampleMeta)
    expect(story.streamTitle).toBe('猎户神话')
    expect(story.streamParagraphs).toHaveLength(2)
    expect(story.streaming).toBe(false)
  })

  it('error 事件 → streamError + throw', async () => {
    const frames = ['event: error\ndata: {"message":"AI 失败"}']
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))

    const story = useStoryStore()
    await expect(story.fetchStoryStream('ori', 'myth', 'fresh')).rejects.toThrow('AI 失败')
    expect(story.streamError).toBe('AI 失败')
    expect(story.streaming).toBe(false)
  })

  it('refetch 命中缓存直接返回，不调 fetch，不走伪流式', async () => {
    const story = useStoryStore()
    const cached: StoryResponse = {
      ...sampleMeta,
      title: '猎户座：冬夜之戒',
      paragraphs: ['段一', '段二', '段三'],
      cached: true,
    }
    story.current = cached
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const result = await story.fetchStoryStream('ori', 'myth', 'refetch')
    expect(result).toEqual(cached)
    expect(fetchMock).not.toHaveBeenCalled()
    // 缓存命中不走伪流式——streamTitle/streamParagraphs 保持默认空，
    // UI 会从 current.paragraphs 一次性渲染。
    expect(story.streamTitle).toBe('')
    expect(story.streamParagraphs).toEqual([])
    expect(story.streaming).toBe(false)
  })

  it('HTTP 错误 → error 事件 + throw', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: 'HTTP 500' } }), { status: 500 }),
    ))
    const story = useStoryStore()
    await expect(story.fetchStoryStream('ori', 'myth', 'fresh')).rejects.toThrow('HTTP 500')
    expect(story.streamError).toBe('HTTP 500')
  })

  it('P0-3: reset 事件清空半截 title/paragraph，等待 preset 重放', async () => {
    const frames = [
      'event: title\ndata: {"title":"半截标题"}',
      'event: paragraph\ndata: {"index":0,"text":"半截段落"}',
      'event: reset\ndata: {}',
      'event: title\ndata: {"title":"预设标题"}',
      'event: paragraph\ndata: {"index":0,"text":"预设第一段"}',
      `event: done\ndata: ${JSON.stringify({ ...sampleMeta, degraded: true, provider: 'fallback' })}`,
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse(frames)))

    const story = useStoryStore()
    await story.fetchStoryStream('ori', 'myth', 'fresh')
    // reset 之后的 preset 内容完整落地，半截内容被清掉
    expect(story.streamTitle).toBe('预设标题')
    expect(story.streamParagraphs.map((p) => p.text)).toEqual(['预设第一段'])
    expect(story.current?.degraded).toBe(true)
  })

  it('P0-5: 新请求开始前 abort 旧流，旧流迟到事件不写入 store', async () => {
    const signals: AbortSignal[] = []
    let resolveA!: (r: Response) => void
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal)
      if (fetchMock.mock.calls.length === 1) {
        return new Promise<Response>((res) => { resolveA = res })  // 旧流挂起
      }
      return Promise.resolve(makeSSEResponse([
        'event: title\ndata: {"title":"新流标题"}',
        `event: done\ndata: ${JSON.stringify({ ...sampleMeta, style: 'science' })}`,
      ]))
    })
    vi.stubGlobal('fetch', fetchMock)

    const story = useStoryStore()
    const p1 = story.fetchStoryStream('ori', 'myth', 'fresh')
    const p2 = story.fetchStoryStream('ori', 'science', 'fresh')
    await p2

    // 旧流被 abort
    expect(signals[0].aborted).toBe(true)
    expect(story.streamTitle).toBe('新流标题')
    expect(story.current?.style).toBe('science')

    // 旧流此后才返回完整事件——不得写入 store
    resolveA(makeSSEResponse([
      'event: title\ndata: {"title":"旧流迟到标题"}',
      `event: done\ndata: ${JSON.stringify(sampleMeta)}`,
    ]))
    await p1.catch(() => {})  // 被取代的请求以 AbortError 收场
    await new Promise((r) => setTimeout(r, 0))
    expect(story.streamTitle).toBe('新流标题')
    expect(story.current?.style).toBe('science')
  })
})
