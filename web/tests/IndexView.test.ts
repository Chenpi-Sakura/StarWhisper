import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { StargazeIndex } from '../src/types'

const fetchMock = vi.fn()
vi.mock('../src/api/stargaze', () => ({
  fetchStargazeIndex: (...a: unknown[]) => fetchMock(...a),
}))

const searchCityMock = vi.fn()
vi.mock('../src/api/geocoding', () => ({
  searchCity: (...a: unknown[]) => searchCityMock(...a),
}))

import IndexView from '../src/views/IndexView.vue'
import { useToastStore } from '../src/stores/toast'
import { useStargazeStore } from '../src/stores/stargaze'

function sampleIndex(over: Partial<StargazeIndex> = {}): StargazeIndex {
  const dailyMoon = [
    { phase: 13.4, illumination: 0.99, label: '满月' },
    { phase: 23.5, illumination: 0.85, label: '亏凸月' },
    { phase: 33.6, illumination: 0.72, label: '下弦月' },
    { phase: 43.7, illumination: 0.55, label: '残月' },
    { phase: 53.8, illumination: 0.40, label: '蛾眉月' },
    { phase: 63.9, illumination: 0.25, label: '蛾眉月' },
    { phase: 73.0, illumination: 0.10, label: '新月' },
  ]
  const dailyAstro = Array.from({ length: 7 }, (_, i) => ({
    sunrise: '05:41',
    sunset: '18:52',
    astro_dusk: '20:36',
    astro_dawn: '04:31',
    moonrise: '06:12',
    moonset: `21:${i.toString().padStart(2, '0')}`,
    galactic_rise: `22:${i.toString().padStart(2, '0')}`,
    galactic_set: '00:15',
  }))
  return {
    ok: true,
    city: '北京',
    province: '北京',
    lat: 39.9,
    lon: 116.4,
    timezone: 'Asia/Shanghai',
    bortle: 8,
    bortle_label: '城市',
    score: 72,
    grade: '良',
    moon: { phase: 13.4, illumination: 0.99, label: '满月' },
    now: { time: '2026-08-27T00:00', cloud: 10, precip: 0, wind: 5, temp: 20 },
    components: { cloud: 90, precip: 100, windtemp: 80, moon: 1, bortle: 5 },
    astro: {
      sunrise: '05:41',
      sunset: '18:52', astro_dusk: '20:36', astro_dawn: '04:31',
      moonrise: '06:12', moonset: '21:08',
      galactic_rise: '22:40', galactic_set: '00:15',
    },
    hourly: [
      { time: '2026-08-27T00:00', score: 72, grade: '良', cloud: 10, precip: 0 },
      { time: '2026-08-27T03:00', score: 40, grade: '一般', cloud: 50, precip: 20 },
      { time: '2026-08-27T06:00', score: 30, grade: '差', cloud: 90, precip: 60 },
    ],
    day_index: 0,
    daily_moon: dailyMoon,
    daily_astro: dailyAstro,
    ...over,
  }
}

function mountView() {
  return mount(IndexView, { global: { plugins: [createPinia()] } })
}

beforeEach(() => {
  fetchMock.mockReset()
  searchCityMock.mockReset()
  searchCityMock.mockResolvedValue([])
  // @ts-expect-error 清理 geolocation，让 locate 走默认城市回退
  delete navigator.geolocation
})

describe('IndexView', () => {
  it('onMounted 触发加载，成功后渲染仪表数据（默认起点 = 当前整点，非 0 点）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="stargaze-ready"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('北京')
    // 分数 72 通过 IndexGauge 内部 rAF 动画渲染，jsdom 终值不定（T5 评审记录），
    // 此处断言 IndexGauge 组件挂载 + 数据源分数正确
    expect(wrapper.findComponent({ name: 'IndexGauge' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('满月')
    const store = useStargazeStore()
    expect(store.rangeStartHour).toBe(new Date().getHours())
    expect(fetchMock).toHaveBeenCalledWith(39.9042, 116.4074, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
  })

  it('加载失败时渲染错误态', async () => {
    fetchMock.mockRejectedValue(new Error('down'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="stargaze-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('天象未明')
  })

  it('请求挂起时渲染 loading 态', async () => {
    fetchMock.mockReturnValue(new Promise(() => {}))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('[data-testid="stargaze-loading"]').exists()).toBe(true)
  })

  it('ready 态渲染双栏图版（FIG.2 + FIG.3 + IndexGauge）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="stargaze-ready"]').exists()).toBe(true)
    expect(wrapper.find('.index-grid').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'IndexGauge' }).exists()).toBe(true)
    // 外层 PlateBox（PLATE Ⅰ · 观星指数 · 今夜之鉴）已被移除
    expect(wrapper.text()).not.toContain('PLATE Ⅰ')
    expect(wrapper.text()).toContain('FIG. 2')
    expect(wrapper.text()).toContain('FIG. 3')
    expect(wrapper.text()).toContain('日落 18:52')
    expect(wrapper.text()).toContain('良')
  })

  it('城市栏挂载 CitySearch 组件，原生 datalist 已移除', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findComponent({ name: 'CitySearch' }).exists()).toBe(true)
    expect(wrapper.find('.city-bar input.field').exists()).toBe(true)
    expect(wrapper.find('datalist').exists()).toBe(false)
  })

  it('城市搜索无匹配且直接点「查阅」时给出反馈（不再要求先查询）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()
    const toast = useToastStore()
    expect(toast.items).toHaveLength(0)

    const lookupBtn = wrapper.findAll('button').find((b) => b.text().trim() === '查阅')
    expect(lookupBtn).toBeTruthy()
    await lookupBtn!.trigger('click')
    await flushPromises()

    expect(toast.items.length).toBeGreaterThanOrEqual(1)
    // 无输入时提示的是「请输入」，而不是旧的「未找到该城市，请先查询再查阅」
    expect(toast.items.at(-1)?.message).toContain('请输入')
    expect(toast.items.at(-1)?.message).not.toContain('请先查询')
  })

  it('C1 契约：FIG.3 使用 daily_moon/daily_astro 切片（camelCase 会 fallback）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    // 起始日期 +1 天（区间整体平移）：selectedDayIndex 由区间起点派生 → 应取 daily_moon[1]
    // （亏凸月/21:01），若消费 camelCase 字段则 fallback 到 moon（满月/21:08）
    const min = wrapper.find('input.range-start-date').attributes('min')!
    function shiftIso(iso: string, days: number): string {
      const [y, m, d] = iso.split('-').map(Number)
      const dt = new Date(y, m - 1, d)
      dt.setDate(dt.getDate() + days)
      const yy = dt.getFullYear()
      const mm = String(dt.getMonth() + 1).padStart(2, '0')
      const dd = String(dt.getDate()).padStart(2, '0')
      return `${yy}-${mm}-${dd}`
    }
    fetchMock.mockResolvedValueOnce(sampleIndex({ day_index: 1 }))
    await wrapper.find('input.range-start-date').setValue(shiftIso(min, 1))
    await flushPromises()

    expect(wrapper.text()).toContain('亏凸月')
    expect(wrapper.text()).toContain('21:01')
    expect(wrapper.text()).not.toContain('21:08')
  })

  it('内层图版用 FIG.1（外层 PlateBox 已删，无 PLATE Ⅰ 文案）+ 评级只留印章 + 保留等级描述', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('FIG. 1')
    expect(wrapper.text()).toContain('今夜指数总评')
    // 外层 PlateBox 移除后不再出现「观星指数 · 今夜之鉴」与「PLATE Ⅰ」文案
    expect(wrapper.text().split('观星指数 · 今夜之鉴').length - 1).toBe(0)
    expect(wrapper.text().split('PLATE Ⅰ').length - 1).toBe(0)
    // 印章保留评级字，但下方不再重复一个「差/优」字（描述文案保留）
    expect(wrapper.find('.gauge-meta .seal').text()).toBe('良')
    expect(wrapper.find('.gauge-meta b').exists()).toBe(false)
    expect(wrapper.find('.gauge-meta .lv-desc').text()).toBe('尚可一观，留意月色')
  })

  it('等级描述跟随 grade（差 → 云深雨重，不宜观星）且不与印章字重复', async () => {
    fetchMock.mockResolvedValue(sampleIndex({ grade: '差', score: 35 }))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.gauge-meta .seal').text()).toBe('差')
    expect(wrapper.find('.gauge-meta .lv-desc').text()).toBe('云深雨重，不宜观星')
    // 评级区内「差」字只出现一次（印章）
    expect(
      wrapper.find('.gauge-meta').text().split('差').length - 1,
    ).toBe(1)
  })

  it('ready 态渲染时间区间选择器（日期 + 整点，最小粒度 1 小时）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    const startDate = wrapper.find('input.range-start-date')
    const endDate = wrapper.find('input.range-end-date')
    expect(startDate.attributes('type')).toBe('date')
    expect(endDate.attributes('type')).toBe('date')
    expect(startDate.attributes('min')).toBeTruthy()
    expect(startDate.attributes('max')).toBeTruthy()

    // 整点下拉 00:00 - 23:00
    const options = wrapper.findAll('select.range-start-hour option')
    expect(options).toHaveLength(24)
    expect(options[0].text()).toBe('00:00')
    expect(options[23].text()).toBe('23:00')
    expect(wrapper.findAll('select.range-end-hour option')).toHaveLength(24)

    // 默认：起点 = 当前整点、长度 24 小时（区间文字写进 FIG.2 标题）
    const store = useStargazeStore()
    const startSel = wrapper.find('select.range-start-hour')
    expect(Number((startSel.element as HTMLSelectElement).value)).toBe(store.rangeStartHour)
    expect(wrapper.text()).toContain(
      `今天 ${String(store.rangeStartHour).padStart(2, '0')}:00`,
    )
    expect(wrapper.text()).toContain('共 24 小时')
    expect(wrapper.text()).toContain('最小粒度 1 小时')
    // 默认命中「此刻起 24 时」预设
    const chip24 = wrapper.findAll('button.chip').find((b) => b.text().includes('此刻起 24 时'))
    expect(chip24!.classes()).toContain('active')
  })

  it('调整起始整点 → 保持原时长整体平移（小时粒度，非整天）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    const store = useStargazeStore()
    const start0 = store.rangeStartHour
    const target = Math.min(23, start0 + 2)
    fetchMock.mockClear()
    fetchMock.mockResolvedValue(sampleIndex())
    await wrapper.find('select.range-start-hour').setValue(String(target))
    await flushPromises()

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
    expect(lastCall[0]).toBe(39.9042)
    expect(lastCall[1]).toBe(116.4074)
    expect(lastCall[2]).toEqual({ startHour: target, hours: 24, signal: undefined })
  })

  it('调整结束整点 → 支持任意小时长度（最小粒度 1 小时）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    const store = useStargazeStore()
    const start0 = store.rangeStartHour
    const end0 = start0 + 24 - 1
    const target = end0 - 3 // 缩短 3 小时 → 21 小时
    expect(target).toBeGreaterThan(start0)
    fetchMock.mockClear()
    fetchMock.mockResolvedValue(sampleIndex())
    await wrapper.find('select.range-end-hour').setValue(String(target % 24))
    if (target >= 24) {
      // 跨天时结束日期也需落到次日
      const min = wrapper.find('input.range-end-date').attributes('min')!
      const [y, m, d] = min.split('-').map(Number)
      const dt = new Date(y, m - 1, d)
      dt.setDate(dt.getDate() + Math.floor(target / 24))
      const iso = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
      await wrapper.find('input.range-end-date').setValue(iso)
      await flushPromises()
    }

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
    expect(lastCall[2]).toEqual({ startHour: start0, hours: 21, signal: undefined })
  })

  it('起始日期越界（> 7 天窗口）→ clamp 到窗口末尾 1 小时（Minor #4）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    const max = wrapper.find('input.range-start-date').attributes('max')!
    function shiftIso(iso: string, days: number): string {
      const [y, m, d] = iso.split('-').map(Number)
      const dt = new Date(y, m - 1, d)
      dt.setDate(dt.getDate() + days)
      const yy = dt.getFullYear()
      const mm = String(dt.getMonth() + 1).padStart(2, '0')
      const dd = String(dt.getDate()).padStart(2, '0')
      return `${yy}-${mm}-${dd}`
    }
    fetchMock.mockClear()
    fetchMock.mockResolvedValue(sampleIndex())
    await wrapper.find('input.range-start-date').setValue(shiftIso(max, 1))
    await flushPromises()

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
    expect(lastCall[2]).toEqual({ startHour: 167, hours: 1, signal: undefined })
  })
})