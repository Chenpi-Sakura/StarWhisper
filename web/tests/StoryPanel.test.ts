import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import StoryPanel from '../src/components/StoryPanel.vue'
import { useScanStore } from '../src/stores/scan'
import { useStoryStore } from '../src/stores/story'

beforeEach(() => setActivePinia(createPinia()))

const sampleSolve = {
  ok: true, solved: true, ra: 84, dec: -1, constellations: [
    { abbr: 'ori', name: '猎户座', latin: 'Orion', confidence: 0.9, tradition: 'western' as const,
      total_bright_stars: 8 },
  ],
  stars_overlay: [],
  overlay_lines: [],
  image_width: 100, image_height: 100,
}

describe('StoryPanel photo-level 触发', () => {
  it('solveId 变化触发 fetchPhotoStory', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: ['p'],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    scan.result = sampleSolve
    scan.solveId = 'solve-1'
    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 0))

    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ constellations: expect.any(Array) }),
      'myth', 'refetch',
    )
  })

  it('chip 切换不触发 fetchPhotoStory（activeAbbr 变化不影响）', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: [],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    scan.result = sampleSolve
    scan.solveId = 'solve-1'
    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 0))
    spy.mockClear()

    // 切 chip
    scan.activeAbbr = 'cyg'
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 10))
    expect(spy).not.toHaveBeenCalled()
  })

  it('点击"重新讲述"按钮触发 fresh', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: [],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    scan.result = sampleSolve
    scan.solveId = 'solve-1'
    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 0))
    spy.mockClear()

    await wrapper.find('.vtab.refresh').trigger('click')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith(expect.anything(), 'myth', 'fresh')
  })

  it('error 状态显示"故事暂不可用" + 重试按钮', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: [],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    story.streamError = 'AI 未配置'
    story.streaming = false
    story.streamText = ''
    story.streamTitle = ''
    story.current = null

    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="story-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('故事暂不可用')
  })

  it('无 style tabs（本期移除神话/科普切换）', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: [],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    scan.result = sampleSolve
    scan.solveId = 'solve-1'
    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()

    // 只剩 refresh tab，没有 myth/science tab
    const vtabs = wrapper.findAll('.vtab')
    expect(vtabs.length).toBe(1)
    expect(vtabs[0].classes()).toContain('refresh')
  })

  // 回归：流结束后 streamText 仍有内容时，state 必须保持 ready，
  // 即便 current（done 事件载荷）的 style 与 selectedStyle 不一致也要可见。
  // 修前 bug：依赖 current.style === scan.selectedStyle → 后端 done 载荷
  // 只含 ok/degraded/provider/model/latency_ms/cached（无 style），
  // 跌回 loading，用户看到「故事输出完后变空白」。
  it('streamText 有内容时保持 ready（即便 current.style 不匹配）', async () => {
    const scan = useScanStore()
    const story = useStoryStore()
    vi.spyOn(story, 'fetchPhotoStory').mockResolvedValue({
      ok: true, abbr: '', style: 'myth', title: 'T', paragraphs: [],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: false,
    })

    scan.result = sampleSolve
    scan.solveId = 'solve-1'
    const wrapper = mount(StoryPanel)
    await wrapper.vm.$nextTick()

    // 模拟流结束但 done 载荷不含 style：streamText 有全文，current 是裸 meta
    story.streaming = false
    story.streamTitle = '古天文'
    story.streamText = '下客自起舞的古老回响。'
    story.streamError = null
    // current 故意写成缺 style 的 done meta（bug 现场的真实载荷）
    story.current = {
      ok: true,
      abbr: '',
      // style: undefined  ← 关键：后端 done 没发
      title: '古天文',
      paragraphs: [],
      provider: 'agentarts',
      model: '',
      latency_ms: 15288,
      cached: false,
      degraded: false,
    } as any

    await wrapper.vm.$nextTick()
    // 必须是 ready，不能因 style 缺失而跌回 loading
    expect(wrapper.find('[data-testid="story-ready"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="story-loading"]').exists()).toBe(false)
    expect(wrapper.find('.story-body').text()).toBe('下客自起舞的古老回响。')
  })
})
