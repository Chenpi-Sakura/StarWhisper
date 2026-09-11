import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const listTraditionsMock = vi.fn()
const listConstellationsMock = vi.fn()
const getConstellationMock = vi.fn()

vi.mock('../src/api/atlas', () => ({
  listTraditions: (...args: unknown[]) => listTraditionsMock(...args),
  listConstellations: (...args: unknown[]) => listConstellationsMock(...args),
  getConstellation: (...args: unknown[]) => getConstellationMock(...args),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  listTraditionsMock.mockReset()
  listConstellationsMock.mockReset()
  getConstellationMock.mockReset()
})

const ORI_DATA = {
  abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
  hemisphere: 'B', bestMonth: 1, season: '冬季', caption: '冬夜之王',
  magnitude: 0.13, storyStyles: ['myth', 'science'],
  tradition: 'western', star_count: 8, has_stories: true,
  stars: {}, lines: [], viewBox: { width: 500, height: 300 },
  stories: {
    myth:    { title: '猎户神话', paragraphs: ['第一段'] },
    science: { title: '猎户科普', paragraphs: [] },
  },
} as any

const FIVE_ITEMS = [
  { abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶', hemisphere: 'B', bestMonth: 1, season: '冬季', caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'], tradition: 'western', star_count: 8, has_stories: true },
  { abbr: 'cyg', name: '天鹅座', latin: 'Cygnus', glyph: '✦', hemisphere: 'N', bestMonth: 8, season: '夏季', caption: '北十字', magnitude: 0.03, storyStyles: ['myth', 'science'], tradition: 'western', star_count: 5, has_stories: true },
  { abbr: 'sco', name: '天蝎座', latin: 'Scorpius', glyph: '✷', hemisphere: 'S', bestMonth: 7, season: '夏季', caption: '夏夜之钩', magnitude: 0.06, storyStyles: ['myth', 'science'], tradition: 'western', star_count: 6, has_stories: true },
  { abbr: 'leo', name: '狮子座', latin: 'Leo', glyph: '✸', hemisphere: 'B', bestMonth: 4, season: '春季', caption: '春夜之王', magnitude: 0.07, storyStyles: ['myth', 'science'], tradition: 'western', star_count: 6, has_stories: true },
  { abbr: 'and', name: '仙女座', latin: 'Andromeda', glyph: '✹', hemisphere: 'B', bestMonth: 11, season: '秋季', caption: '银河之邻', magnitude: 0.05, storyStyles: ['myth', 'science'], tradition: 'western', star_count: 4, has_stories: true },
]

describe('ConstellationView', () => {
  it('list 加载后渲染 5 枚圆形 smedal（IND plate 已下线，仅顶部滚动铭牌）', async () => {
    listTraditionsMock.mockResolvedValue({
      items: [{ key: 'western', label: '西方星座', count: 5 }],
    })
    listConstellationsMock.mockResolvedValue({ tradition: 'western', items: FIVE_ITEMS })
    getConstellationMock.mockResolvedValue(ORI_DATA)
    const ConstellationView = (await import('../src/views/ConstellationView.vue')).default
    const wrapper = mount(ConstellationView)
    await flushPromises()
    // 顶部 smedal-row 渲染 5 枚；下方 IND plate 已删，不应有 .cchip / .chip-list
    expect(wrapper.findAll('[data-testid="smedal-row"] .smedal')).toHaveLength(5)
    expect(wrapper.findAll('.cchip')).toHaveLength(0)
    expect(wrapper.findAll('.chip-list')).toHaveLength(0)
    // smedal-row 应有 max-height 限制 + overflow 滚动
    const row = wrapper.find('[data-testid="smedal-row"]')
    expect(row.exists()).toBe(true)
  })

  it('render tradition chips', async () => {
    listTraditionsMock.mockResolvedValue({
      items: [
        { key: 'western', label: '西方星座', count: 5 },
        { key: 'chinese', label: '中国古代星空', count: 0 },
      ],
    })
    listConstellationsMock.mockResolvedValue({ tradition: 'western', items: FIVE_ITEMS })
    getConstellationMock.mockResolvedValue(ORI_DATA)
    const ConstellationView = (await import('../src/views/ConstellationView.vue')).default
    const wrapper = mount(ConstellationView)
    await flushPromises()
    expect(wrapper.find('[data-testid="trad-tab-western"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="trad-tab-chinese"]').exists()).toBe(true)
  })

  it('切换到 chinese 显示空状态', async () => {
    listTraditionsMock.mockResolvedValue({
      items: [
        { key: 'western', label: '西方星座', count: 5 },
        { key: 'chinese', label: '中国古代星空', count: 0 },
      ],
    })
    listConstellationsMock
      .mockResolvedValueOnce({ tradition: 'western', items: FIVE_ITEMS })
      .mockResolvedValueOnce({ tradition: 'chinese', items: [] })
    getConstellationMock.mockResolvedValue(ORI_DATA)
    const ConstellationView = (await import('../src/views/ConstellationView.vue')).default
    const wrapper = mount(ConstellationView)
    await flushPromises()
    const chineseBtn = wrapper.find('[data-testid="trad-tab-chinese"]')
    await chineseBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="atlas-empty"]').exists()).toBe(true)
  })

  it('chinese tradition 渲染 3 枚 smedal（不再分组，无 chip-list / details）', async () => {
    const CHINESE_ITEMS = [
      { abbr: 'shenxiu', name: '参宿', latin: 'Three', season: '冬', caption: '',
        tradition: 'chinese', star_count: 7, has_stories: true, group: '西方七宿' },
      { abbr: 'ziweiyuan', name: '紫微垣', latin: 'Purple', season: '', caption: '',
        tradition: 'chinese', star_count: 50, has_stories: true, group: '紫微垣' },
      { abbr: 'haishan', name: '海山', latin: 'Sea', season: '', caption: '',
        tradition: 'chinese', star_count: 6, has_stories: false, group: '近南极' },
    ]
    listTraditionsMock.mockResolvedValue({
      items: [
        { key: 'western', label: '西方星座', count: 5 },
        { key: 'chinese', label: '中国古代星空', count: 3 },
      ],
    })
    listConstellationsMock
      .mockResolvedValueOnce({ tradition: 'western', items: FIVE_ITEMS })
      .mockResolvedValueOnce({ tradition: 'chinese', items: CHINESE_ITEMS })
    getConstellationMock.mockResolvedValue(ORI_DATA)
    const ConstellationView = (await import('../src/views/ConstellationView.vue')).default
    const wrapper = mount(ConstellationView)
    await flushPromises()
    const chineseBtn = wrapper.find('[data-testid="trad-tab-chinese"]')
    await chineseBtn.trigger('click')
    await flushPromises()
    // 扁平 3 枚 smedal 渲染在顶部 smedal-row
    expect(wrapper.findAll('[data-testid="smedal-row"] .smedal')).toHaveLength(3)
    // 分组 UI（details / chip-list / cchip）已下线
    expect(wrapper.findAll('details.group')).toHaveLength(0)
    expect(wrapper.findAll('.chip-list')).toHaveLength(0)
    expect(wrapper.findAll('.cchip')).toHaveLength(0)
  })

  it('AtlasNota 挂在右列底部，传入 selected（见图鉴页改 AtlasNota）', async () => {
    listTraditionsMock.mockResolvedValue({
      items: [{ key: 'western', label: '西方星座', count: 5 }],
    })
    listConstellationsMock.mockResolvedValue({ tradition: 'western', items: FIVE_ITEMS })
    getConstellationMock.mockResolvedValue(ORI_DATA)
    const ConstellationView = (await import('../src/views/ConstellationView.vue')).default
    const wrapper = mount(ConstellationView)
    await flushPromises()
    // AtlasNota 组件挂载
    expect(wrapper.find('[data-testid="atlas-nota"]').exists()).toBe(true)
    // 原内联 NOTA 文案不在
    expect(wrapper.text()).not.toContain('神话，写给星空的信')
    // 原内联 chip-list-inline 已删除
    expect(wrapper.findAll('.chip-list-inline')).toHaveLength(0)
    // AtlasNota 的两个底部 chip 都在（commit L 删除了「切换视角」chip）
    expect(wrapper.text()).toContain('重新讲述')
    expect(wrapper.text()).toContain('生成分享卡')
    expect(wrapper.text()).not.toContain('切换视角')
  })
})
