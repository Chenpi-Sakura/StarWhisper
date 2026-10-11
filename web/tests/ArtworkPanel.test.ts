import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ArtworkPanel from '../src/components/ArtworkPanel.vue'
import { useArtworkStore } from '../src/stores/artwork'
import { useScanStore } from '../src/stores/scan'
import { useStoryStore } from '../src/stores/story'

const startMock = vi.fn()
const pollMock = vi.fn()

// 类声明必须在 vi.mock 工厂内部：工厂会被提升到文件顶部
vi.mock('../src/api/artwork', () => ({
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

const STORY_TEXT = '玉衡引路\n北天那头巨大的铁熊探出脊背。'

function primeStores() {
  const scan = useScanStore()
  const story = useStoryStore()
  scan.solveId = 'solve-1'
  story.streamTitle = '玉衡引路'
  story.streamText = '北天那头巨大的铁熊探出脊背。'
  story.streaming = false
}

beforeEach(() => {
  setActivePinia(createPinia())
  startMock.mockReset()
  pollMock.mockReset()
  startMock.mockResolvedValue({ ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'image-01' })
  pollMock.mockResolvedValue({
    ok: true, job_id: 'j1', status: 'ready', model: 'image-01', cached: false,
    images: ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg'], latency_ms: 33_000,
  })
})

describe('ArtworkPanel 触发时机', () => {
  it('故事流已跑完时挂载即发起一次生成', async () => {
    primeStores()
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).toHaveBeenCalledTimes(1)
    // 送出去的是「标题 + 正文」拼起来的故事全文
    expect(startMock.mock.calls[0][0]).toBe(STORY_TEXT)
  })

  it('故事还在流式输出时不抢跑', async () => {
    primeStores()
    useStoryStore().streaming = true
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).not.toHaveBeenCalled()
  })

  it('没有故事正文时不发起', async () => {
    useScanStore().solveId = 'solve-1'
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).not.toHaveBeenCalled()
  })

  it('同一段故事重复挂载只生成一次', async () => {
    primeStores()
    const first = mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).toHaveBeenCalledTimes(1)
    first.unmount()

    // 回到 done 时组件会重新挂载；store 里已有同一篇故事的结果就不该再烧一次
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).toHaveBeenCalledTimes(1)
  })

  it('换了故事正文则会重新生成', async () => {
    primeStores()
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).toHaveBeenCalledTimes(1)

    useStoryStore().streamText = '全新的一篇故事内容。'
    await flushPromises()
    expect(startMock).toHaveBeenCalledTimes(2)
  })
})

describe('ArtworkPanel 状态渲染', () => {
  it('loading 显示骨架与耗时提示', () => {
    primeStores()
    pollMock.mockResolvedValue({
      ok: false, job_id: 'j1', status: 'pending', model: 'm', cached: false, images: [],
    })
    startMock.mockImplementation(() => new Promise(() => {})) // 挂住
    const wrapper = mount(ArtworkPanel)
    expect(wrapper.find('[data-testid="artwork-loading"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('约需 40 秒')
  })

  it('ready 显示主图、候选缩略图与"艺术演绎"标识', async () => {
    primeStores()
    const wrapper = mount(ArtworkPanel)
    await flushPromises()
    const ready = wrapper.find('[data-testid="artwork-ready"]')
    expect(ready.exists()).toBe(true)
    expect(ready.find('.stage img').attributes('src')).toBe('a.jpg')
    expect(ready.findAll('.cands button')).toHaveLength(4)
    // 准确性承诺的一部分：生成图必须与真实星图区分开
    expect(wrapper.text()).toContain('艺术演绎')
    expect(wrapper.text()).toContain('非科学星图')
  })

  it('点候选缩略图切换主图', async () => {
    primeStores()
    const wrapper = mount(ArtworkPanel)
    await flushPromises()
    await wrapper.findAll('.cands button')[2].trigger('click')
    expect(wrapper.find('.stage img').attributes('src')).toBe('c.jpg')
    expect(wrapper.findAll('.cands button')[2].classes()).toContain('on')
  })

  it('error 显示业务码文案并可重试', async () => {
    primeStores()
    pollMock.mockResolvedValue({
      ok: false, job_id: 'j1', status: 'error', model: 'm', cached: false, images: [],
      error_code: 'IMAGE_NO_BALANCE', error_message: '账号余额不足',
    })
    const wrapper = mount(ArtworkPanel)
    await flushPromises()
    const box = wrapper.find('[data-testid="artwork-error"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('账号余额不足')
    await box.find('button').trigger('click')
    await vi.waitFor(() => expect(startMock).toHaveBeenCalledTimes(2))
  })

  it('审核误判（IMAGE_UNSAFE_CONTENT）额外给出可操作提示', async () => {
    primeStores()
    pollMock.mockResolvedValue({
      ok: false, job_id: 'j1', status: 'error', model: 'm', cached: false, images: [],
      error_code: 'IMAGE_UNSAFE_CONTENT', error_message: '画面描述涉及敏感内容',
    })
    const wrapper = mount(ArtworkPanel)
    await flushPromises()
    const advice = wrapper.find('[data-testid="artwork-error-advice"]')
    expect(advice.exists()).toBe(true)
    expect(advice.text()).toContain('已自动重试过一次')
  })

  it('其它错误码不给审核提示', async () => {
    primeStores()
    pollMock.mockResolvedValue({
      ok: false, job_id: 'j1', status: 'error', model: 'm', cached: false, images: [],
      error_code: 'IMAGE_NO_BALANCE', error_message: '账号余额不足',
    })
    const wrapper = mount(ArtworkPanel)
    await flushPromises()
    expect(wrapper.find('[data-testid="artwork-error-advice"]').exists()).toBe(false)
  })

  it('换一批按钮在 loading 时禁用', () => {
    primeStores()
    startMock.mockImplementation(() => new Promise(() => {}))
    const wrapper = mount(ArtworkPanel)
    const btn = wrapper.findAll('.vtab')[0]
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('store 已有结果时组件复用，不重复请求', async () => {
    primeStores()
    const art = useArtworkStore()
    await art.generate(STORY_TEXT)
    startMock.mockClear()
    mount(ArtworkPanel)
    await flushPromises()
    expect(startMock).not.toHaveBeenCalled()
    expect(useArtworkStore().images).toHaveLength(4)
  })
})
