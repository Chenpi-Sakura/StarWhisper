import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useArtworkStore } from '../src/stores/artwork'

const startMock = vi.fn()
const pollMock = vi.fn()

// 类声明不能放在 vi.mock 工厂之外：工厂会被提升到文件顶部（hoisting）
vi.mock('../src/api/artwork', () => ({
  // 真实实现是 2s 一轮，测试里压到 1ms 以免拖慢
  ARTWORK_POLL_INTERVAL_MS: 1,
  ARTWORK_DEADLINE_MS: 5_000,
  ARTWORK_REQUEST_TIMEOUT_MS: 120_000,
  ArtworkApiError: class extends Error {
    code: string
    constructor(code: string, message: string) {
      super(message)
      this.code = code
    }
  },
  startArtwork: (...a: unknown[]) => startMock(...a),
  pollArtwork: (...a: unknown[]) => pollMock(...a),
}))

function apiError(code: string, message: string): Error {
  return Object.assign(new Error(message), { code })
}

beforeEach(() => {
  setActivePinia(createPinia())
  startMock.mockReset()
  pollMock.mockReset()
})

const ready = (images: string[], cached = false) => ({
  ok: true, job_id: 'j1', status: 'ready' as const, model: 'image-01', cached, images,
  latency_ms: 33_000,
})

describe('artworkStore.generate', () => {
  it('走完 pending → ready 并写入候选与选中项', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'image-01' })
    pollMock
      .mockResolvedValueOnce({ ok: false, job_id: 'j1', status: 'pending', model: 'image-01', cached: false, images: [] })
      .mockResolvedValueOnce(ready(['a.jpg', 'b.jpg']))

    const art = useArtworkStore()
    const p = art.generate('一段故事')
    expect(art.phase).toBe('loading')
    await p

    expect(art.phase).toBe('ready')
    expect(art.images).toEqual(['a.jpg', 'b.jpg'])
    expect(art.current).toBe('a.jpg')
    expect(art.picked).toBe(0)
    expect(art.errorCode).toBeNull()
  })

  it('空故事直接不发请求', async () => {
    const art = useArtworkStore()
    await art.generate('   ')
    expect(startMock).not.toHaveBeenCalled()
    expect(art.phase).toBe('idle')
  })

  it('pick 切换选中项，越界忽略', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue(ready(['a.jpg', 'b.jpg', 'c.jpg']))
    const art = useArtworkStore()
    await art.generate('故事')

    art.pick(2)
    expect(art.current).toBe('c.jpg')
    art.pick(9)
    expect(art.picked).toBe(2)
    art.pick(-1)
    expect(art.picked).toBe(2)
  })

  it('job 以 error 收尾时写业务码而不是抛异常', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue({
      ok: false, job_id: 'j1', status: 'error', model: 'm', cached: false, images: [],
      error_code: 'IMAGE_NO_BALANCE', error_message: '账号余额不足',
    })
    const art = useArtworkStore()
    await art.generate('故事')
    expect(art.phase).toBe('error')
    expect(art.errorCode).toBe('IMAGE_NO_BALANCE')
    expect(art.errorMessage).toBe('账号余额不足')
  })

  it('HTTP 异常按 code 归类', async () => {
    startMock.mockRejectedValue(apiError('IMAGE_DISABLED', '未配置图片生成密钥'))
    const art = useArtworkStore()
    await art.generate('故事')
    expect(art.phase).toBe('error')
    expect(art.errorCode).toBe('IMAGE_DISABLED')
  })

  it('返回零张图判为 ARTWORK_EMPTY', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue(ready([]))
    const art = useArtworkStore()
    await art.generate('故事')
    expect(art.phase).toBe('error')
    expect(art.errorCode).toBe('ARTWORK_EMPTY')
  })
})

describe('artworkStore.reroll 与竞态', () => {
  it('换一批沿用同一故事但带 cache_bust', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue(ready(['a.jpg']))
    const art = useArtworkStore()
    await art.generate('同一个故事')
    expect(startMock).toHaveBeenLastCalledWith('同一个故事', false)

    art.reroll()
    await vi.waitFor(() => expect(art.phase).toBe('ready'))
    expect(startMock).toHaveBeenLastCalledWith('同一个故事', true)
  })

  it('没有历史故事时 reroll 是空操作', async () => {
    const art = useArtworkStore()
    art.reroll()
    await vi.waitFor(() => expect(art.phase).toBe('idle'))
    expect(startMock).not.toHaveBeenCalled()
  })

  it('新请求会丢弃旧轮询的结果', async () => {
    // 先把 promise 与 resolver 建好：若写成 `let r: Fn | null = null` 再在闭包里
    // 赋值，TS 会把调用点窄化成 never
    let resolveStart: (v: unknown) => void = () => {}
    const firstStart = new Promise((r) => { resolveStart = r })
    startMock
      .mockImplementationOnce(() => firstStart)
      .mockResolvedValue({ ok: true, job_id: 'j2', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue(ready(['late.jpg']))

    const art = useArtworkStore()
    const first = art.generate('第一个故事')
    const second = art.generate('第二个故事')

    resolveStart({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    await Promise.all([first, second])

    // 只有最后一次请求的故事留在 store 上
    expect(art.storyKey).toBe('第二个故事')
    expect(art.phase).toBe('ready')
  })

  it('reset 清空全部状态并让在途结果失效', async () => {
    startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'm' })
    pollMock.mockResolvedValue(ready(['a.jpg']))
    const art = useArtworkStore()
    await art.generate('故事')
    art.reset()
    expect(art.phase).toBe('idle')
    expect(art.images).toEqual([])
    expect(art.storyKey).toBe('')
  })
})
