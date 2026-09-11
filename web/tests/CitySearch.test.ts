import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

import CitySearch from '../src/components/index/CitySearch.vue'
import { useToastStore } from '../src/stores/toast'
import { resetCityIndexCache } from '../src/utils/cityTrie'
import { fixtureFetch } from './fixtures/cityFile'

function sampleIndex(): StargazeIndex {
  return {
    ok: true,
    city: '成都',
    province: '四川',
    lat: 30.66,
    lon: 104.06,
    timezone: 'Asia/Shanghai',
    bortle: 8,
    bortle_label: '城市',
    score: 72,
    grade: '良',
    moon: { phase: 13.4, illumination: 0.99, label: '满月' },
    now: { time: '2026-09-11T22:00', cloud: 10, precip: 0, wind: 5, temp: 20 },
    components: { cloud: 90, precip: 100, windtemp: 80, moon: 1, bortle: 5 },
    astro: {
      sunrise: '06:45', sunset: '19:14', astro_dusk: '20:36', astro_dawn: '05:24',
      moonrise: '06:43', moonset: '19:09', galactic_rise: '14:46', galactic_set: '00:15',
    },
    hourly: [{ time: '2026-09-11T22:00', score: 72, grade: '良', cloud: 10, precip: 0 }],
    day_index: 0,
    daily_moon: [{ phase: 13.4, illumination: 0.99, label: '满月' }],
    daily_astro: [{
      sunrise: '06:45', sunset: '19:14', astro_dusk: '20:36', astro_dawn: '05:24',
      moonrise: '06:43', moonset: '19:09', galactic_rise: '14:46', galactic_set: '00:15',
    }],
  } as StargazeIndex
}

function mountSearch() {
  return mount(CitySearch, { global: { plugins: [createPinia()] } })
}

/** 模拟真实输入（含输入法组合态：直接改 value 后派发 input）。 */
async function type(wrapper: ReturnType<typeof mountSearch>, text: string) {
  const input = wrapper.find('input.field')
  ;(input.element as HTMLInputElement).value = text
  await input.trigger('input')
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  resetCityIndexCache()
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(sampleIndex())
  searchCityMock.mockReset()
  searchCityMock.mockResolvedValue([])
  vi.stubGlobal('fetch', vi.fn(fixtureFetch())) // 城市数据文件
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CitySearch', () => {
  it('输入中文前缀即时出下拉，并高亮命中前缀', async () => {
    const w = mountSearch()
    await type(w, '成')

    const items = w.findAll('.cs-list .cs-item')
    expect(items.length).toBeGreaterThan(0)
    expect(items[0].text()).toContain('成都市')
    expect(items[0].text()).toContain('四川省 · 地级市')
    // 高亮 <mark> 只包住输入的前缀
    expect(items[0].find('mark').text()).toBe('成')
  })

  it('完整名称精确命中排第一（成县 虽为区县）', async () => {
    const w = mountSearch()
    await type(w, '成县')
    expect(w.findAll('.cs-list .cs-item')[0].text()).toContain('成县')
  })

  it('IME 组合态（只派发 input，不触发 change）也能出结果', async () => {
    const w = mountSearch()
    await type(w, '成都')
    expect(w.findAll('.cs-list .cs-item').length).toBeGreaterThan(0)
  })

  it('本地 0 命中且有 2 字以上 → 走在线兜底并标「在线」', async () => {
    searchCityMock.mockResolvedValue([
      { name: '冷湖', admin1: '青海省', latitude: 38.0, longitude: 93.4 },
    ])
    const w = mountSearch()
    await type(w, '冷湖')
    // 在线兜底有 250ms 防抖
    await new Promise((r) => setTimeout(r, 320))
    await flushPromises()

    const items = w.findAll('.cs-list .cs-item')
    expect(items).toHaveLength(1)
    expect(items[0].text()).toContain('冷湖')
    expect(items[0].text()).toContain('在线')
    expect(searchCityMock).toHaveBeenCalledWith('冷湖', expect.anything())
  })

  it('「查阅」取下拉首条命中（不再要求先点下拉）', async () => {
    const w = mountSearch()
    await type(w, '成都')
    const btn = w.findAll('button').find((b) => b.text().trim() === '查阅')!
    await btn.trigger('click')
    await flushPromises()

    // 成都（夹具）坐标加载指数
    expect(fetchMock).toHaveBeenLastCalledWith(30.66, 104.06, {
      startHour: expect.any(Number),
      hours: 24,
      signal: undefined,
    })
    // 选中后下拉收起、输入框回填名称
    expect(w.find('.cs-list').exists()).toBe(false)
    expect((w.find('input.field').element as HTMLInputElement).value).toBe('成都市')
  })

  it('键盘 ↑↓ 移动高亮，Enter 选中高亮项', async () => {
    const w = mountSearch()
    await type(w, '成')
    const input = w.find('input.field')
    const items = () => w.findAll('.cs-list .cs-item')

    expect(items()[0].classes()).not.toContain('on')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(items()[0].classes()).toContain('on')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(items()[1].classes()).toContain('on')
    await input.trigger('keydown', { key: 'ArrowUp' })
    expect(items()[0].classes()).toContain('on')

    // 高亮第 2 条 → Enter 选中它（成县）
    await input.trigger('keydown', { key: 'ArrowDown' })
    const second = items()[1].text()
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(second).toContain('成县')
    expect(fetchMock.mock.calls[0][0]).toBeCloseTo(33.7, 3) // 成县纬度
  })

  it('Esc 收起下拉；点击外部也收起', async () => {
    const w = mountSearch()
    await type(w, '成')
    expect(w.find('.cs-list').exists()).toBe(true)
    await w.find('input.field').trigger('keydown', { key: 'Escape' })
    expect(w.find('.cs-list').exists()).toBe(false)

    await type(w, '成')
    expect(w.find('.cs-list').exists()).toBe(true)
    document.body.click()
    await flushPromises()
    expect(w.find('.cs-list').exists()).toBe(false)
  })

  it('点击下拉项直接选中', async () => {
    const w = mountSearch()
    await type(w, '成')
    await w.findAll('.cs-list .cs-item')[0].trigger('mousedown')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBeCloseTo(30.66, 3)
  })

  it('空输入点「查阅」→ 提示先输入城市名', async () => {
    const w = mountSearch()
    const toast = useToastStore()
    const btn = w.findAll('button').find((b) => b.text().trim() === '查阅')!
    await btn.trigger('click')
    expect(toast.items.at(-1)?.message).toContain('请输入')
  })

  it('本地与在线都无匹配 → 提示未找到', async () => {
    const w = mountSearch()
    const toast = useToastStore()
    await type(w, '不存在的城市名')
    await new Promise((r) => setTimeout(r, 320))
    await flushPromises()

    expect(w.find('.cs-empty').exists()).toBe(true)
    const btn = w.findAll('button').find((b) => b.text().trim() === '查阅')!
    await btn.trigger('click')
    expect(toast.items.at(-1)?.message).toContain('未找到')
  })

  it('下拉收起后不再显示候选；输入框保留选中城市名', async () => {
    const w = mountSearch()
    await type(w, '成都')
    await w.findAll('.cs-list .cs-item')[0].trigger('mousedown')
    await flushPromises()
    expect(w.find('.cs-list').exists()).toBe(false)
    expect(w.find('select.preset-select').exists()).toBe(false) // 预设城市下拉已删除
    expect((w.find('input.field').element as HTMLInputElement).value).toBe('成都市')
  })
})
