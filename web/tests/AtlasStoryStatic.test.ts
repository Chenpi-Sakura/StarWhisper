import { describe, it, expect, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import AtlasStoryStatic from '../src/components/AtlasStoryStatic.vue'
import { useAtlasStore } from '../src/stores/atlas'

const ORI_STORIES = {
  myth:    { title: '猎户 · 神话',    paragraphs: ['第一段', '第二段'] },
  science: { title: '猎户 · 科普',    paragraphs: ['科技1'] },
} as any

const CYG_STORIES = {
  myth:    { title: '天鹅 · 神话',    paragraphs: ['x1'] },
  science: { title: '天鹅 · 科普',    paragraphs: ['y1'] },
} as any

beforeEach(() => {
  setActivePinia(createPinia())
  // 预填 store 的 atlasCache，模拟已加载
  const store = useAtlasStore()
  store.atlasCache['western/ori'] = { abbr: 'ori', tradition: 'western', stars: {}, stories: ORI_STORIES } as any
  store.atlasCache['western/cyg'] = { abbr: 'cyg', tradition: 'western', stars: {}, stories: CYG_STORIES } as any
})

describe('AtlasStoryStatic 预设文稿组件', () => {
  it('默认渲染神话视角段，预设标题出现', () => {
    const wrapper = mount(AtlasStoryStatic, { props: { tradition: 'western', abbr: 'ori' } })
    expect(wrapper.find('[data-testid="atlas-story"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(ORI_STORIES.myth.title)
  })

  it('切到科普视角显示对应预设', async () => {
    const wrapper = mount(AtlasStoryStatic, { props: { tradition: 'western', abbr: 'cyg' } })
    await wrapper.findAll('.vtab')[1].trigger('click')
    expect(wrapper.text()).toContain(CYG_STORIES.science.title)
  })

  it('切视角 × 2 星座 = 4 条不同', async () => {
    const titles = new Set<string>()
    for (const abbr of ['ori', 'cyg']) {
      const wrapper = mount(AtlasStoryStatic, { props: { tradition: 'western', abbr } })
      for (const v of wrapper.findAll('.vtab')) {
        await v.trigger('click')
        await flushPromises()
        titles.add(wrapper.find('.story-title').text())
      }
    }
    expect(titles.size).toBe(4)
  })

  it('未知 abbr → 显示空提示', () => {
    const wrapper = mount(AtlasStoryStatic, { props: { tradition: 'western', abbr: 'draco' } })
    expect(wrapper.text()).toContain('尚未加载')
  })

  it('空维度显示空状态', async () => {
    const store = useAtlasStore()
    store.atlasCache['western/empty'] = {
      abbr: 'empty', tradition: 'western', stars: {},
      stories: {
        myth:    { title: '尚未撰写', paragraphs: [] },
        science: { title: '尚未撰写', paragraphs: [] },
      },
    } as any
    const wrapper = mount(AtlasStoryStatic, { props: { tradition: 'western', abbr: 'empty' } })
    await flushPromises()
    expect(wrapper.find('[data-testid="story-empty"]').exists()).toBe(true)
  })
})
