import { describe, it, expect, afterEach, vi } from 'vitest'

import { streamPhotoStory } from '../src/api/story'

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

afterEach(() => vi.unstubAllGlobals())

describe('streamPhotoStory 请求 shape', () => {
  it('POST /api/story body 含 lang/style/cache_bust/context', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeSSEResponse([
      'event: title\ndata: {"title":"T"}',
      `event: done\ndata: {"ok":true,"degraded":false}`,
    ]))
    vi.stubGlobal('fetch', fetchMock)

    await streamPhotoStory(
      {
        lang: 'zh', style: 'myth', cache_bust: false,
        context: {
          constellations: [{ abbr: 'ori', tradition: 'western', name: '猎户座', latin: 'Orion' }],
          bright_stars: [],
          center: { ra: 84, dec: -1 },
          field: { width_deg: 12.5, height_deg: 8.3 },
        },
      },
      () => {},
    )

    expect(fetchMock).toHaveBeenCalledWith('/api/story', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }))
    const sentBody = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(sentBody.lang).toBe('zh')
    expect(sentBody.style).toBe('myth')
    expect(sentBody.cache_bust).toBe(false)
    expect(sentBody.context.constellations[0].abbr).toBe('ori')
  })

  it('parseSSE char 事件 → onEvent({type:"char", char})', async () => {
    const onEvent = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse([
      'event: title\ndata: {"title":"标题"}',
      'event: char\ndata: {"char":"星"}',
      'event: char\ndata: {"char":"空"}',
    ])))

    await streamPhotoStory(
      {
        lang: 'zh', style: 'myth', cache_bust: false,
        context: { constellations: [{ abbr: 'ori', tradition: 'western', name: '猎户座' }] },
      },
      onEvent,
    )

    const types = onEvent.mock.calls.map((c) => c[0].type)
    expect(types).toEqual(['title', 'char', 'char'])
    expect(onEvent.mock.calls[1][0]).toEqual({ type: 'char', char: '星' })
    expect(onEvent.mock.calls[2][0]).toEqual({ type: 'char', char: '空' })
  })

  it('parseSSE error 事件 → onEvent({type:"error", code, message})', async () => {
    const onEvent = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeSSEResponse([
      'event: error\ndata: {"code":"AI_DISABLED","message":"AI 未配置"}',
    ])))

    await streamPhotoStory(
      {
        lang: 'zh', style: 'myth', cache_bust: false,
        context: { constellations: [{ abbr: 'ori', tradition: 'western', name: '猎户座' }] },
      },
      onEvent,
    )

    expect(onEvent).toHaveBeenCalledWith({
      type: 'error', code: 'AI_DISABLED', message: 'AI 未配置',
    })
  })
})
