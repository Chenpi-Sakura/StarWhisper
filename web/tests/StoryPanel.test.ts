import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import StoryPanel from '../src/components/StoryPanel.vue'
import { useStoryStore } from '../src/stores/story'
import type { StoryResponse } from '../src/types'

beforeEach(() => setActivePinia(createPinia()))

const sampleStory: StoryResponse = {
  ok: true, abbr: 'ori', style: 'myth', title: '猎户神话',
  paragraphs: ['第一段', '第二段'],
  provider: 'mock', model: 'm', latency_ms: 10,
  cached: false, degraded: false,
}

describe('StoryPanel 三态', () => {
  it('loading 渲染 skeleton', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.loading = true
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-loading"]').exists()).toBe(true)
  })

  it('ready 渲染段落列表', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.current = sampleStory
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-ready"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('猎户神话')
  })

  it('切换视角触发 fetchStoryStream refetch（仅一次，不并发）', async () => {
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    spy.mockClear()
    // vtabs 第二个 = 科普视角
    await wrapper.findAll('.vtab:not(.refresh)')[1].trigger('click')
    // 等 watch 响应 + onViewChange 完成
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 0))
    // 只调一次、且是 refetch（不是 fresh）：避免与 watch 并发两个流。
    const calls = spy.mock.calls.filter(
      (c) => c[0] === 'ori' && c[1] === 'science',
    )
    expect(calls).toHaveLength(1)
    expect(calls[0][2]).toBe('refetch')  // action = refetch
  })

  it('点击重新讲述触发 fresh fetch', async () => {
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    spy.mockClear()
    // 刷新按钮（vtab.refresh）
    await wrapper.find('.vtab.refresh').trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 0))
    // 调用一次、action='fresh'
    const calls = spy.mock.calls.filter(
      (c) => c[0] === 'ori' && c[1] === 'myth',
    )
    expect(calls).toHaveLength(1)
    expect(calls[0][2]).toBe('fresh')
  })

  it('degraded 渲染降级提示 + 重试按钮', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.streamError = 'HTTP 500'
    story.current = null
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-degraded"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('重试')
  })

  it('P0-4: 流式进行中但尚无内容 → 骨架屏（不再空白三分支落空）', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.streaming = true
    story.streamTitle = ''
    story.streamParagraphs = []
    story.current = null
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="story-ready"]').exists()).toBe(false)
  })

  it('P0-4: 流式进行中已有首段 → 打字机渲染（不依赖 current）', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.streaming = true
    story.streamTitle = '流式标题'
    story.streamParagraphs = [{ index: 0, text: '流式第一段' }]
    story.current = null
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-ready"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('流式标题')
    expect(wrapper.text()).toContain('流式第一段')
  })

  it('P0-4: 切星座时旧 current 不串台（current 已被 store 清空 → 骨架屏）', async () => {
    const story = useStoryStore()
    vi.spyOn(story, 'fetchStoryStream').mockResolvedValue(sampleStory)
    story.current = { ...sampleStory, abbr: 'cyg' }  // 上一个星座
    story.streaming = true
    story.streamTitle = ''
    story.streamParagraphs = []
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    // 旧星座内容不得渲染
    expect(wrapper.text()).not.toContain('猎户神话')
    expect(wrapper.find('[data-testid="story-loading"]').exists()).toBe(true)
  })
})
