import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import type { StargazeIndex } from '../src/types'

const fetchMock = vi.fn()
vi.mock('../src/api/stargaze', () => ({
  fetchStargazeIndex: (...a: unknown[]) => fetchMock(...a),
}))

const searchCityMock = vi.fn()
vi.mock('../src/api/geocoding', () => ({
  searchCity: (...a: unknown[]) => searchCityMock(...a),
}))

import { useStargazeStore, DEFAULT_LOCATION } from '../src/stores/stargaze'
import { resetCityIndexCache } from '../src/utils/cityTrie'
import { fixtureFetch } from './fixtures/cityFile'

/** 桩掉城市数据文件请求（本地前缀索引），返回 fetch spy。 */
function stubCityFetch() {
  const spy = vi.fn(fixtureFetch())
  vi.stubGlobal('fetch', spy)
  return spy
}

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
    sunrise: `05:${10 + i}`,
    sunset: `${18 + (i % 2)}:${30 + i}`,
    astro_dusk: `20:${30 + i}`,
    astro_dawn: `04:${10 + i}`,
    moonrise: `06:${10 + i}`,
    moonset: `21:${i.toString().padStart(2, '0')}`,
    galactic_rise: `22:${i.toString().padStart(2, '0')}`,
    galactic_set: `00:${10 + i}`,
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
    hourly: [{ time: '2026-08-27T00:00', score: 72, grade: '良', cloud: 10, precip: 0 }],
    day_index: 0,
    daily_moon: dailyMoon,
    daily_astro: dailyAstro,
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  fetchMock.mockReset()
  searchCityMock.mockReset()
  resetCityIndexCache() // 城市索引是模块级单例，跨用例必须清
  // @ts-expect-error 清理可能的 geolocation 桩
  delete navigator.geolocation
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('stargaze store', () => {
  it('load 成功写入 data 并更新 location', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    expect(store.status).toBe('ready')
    expect(store.data?.score).toBe(72)
    expect(store.location.label).toBe('北京')
  })

  it('load 失败进入 error 态并给出文案', async () => {
    fetchMock.mockRejectedValue(new Error('HTTP 502'))
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('天气服务暂不可用，请稍后重试')
  })

  it('默认区间：起点 = 当前整点（非 0 点），长度 24 小时', async () => {
    const store = useStargazeStore()
    expect(store.rangeStartHour).toBe(new Date().getHours())
    expect(store.rangeHours).toBe(24)
    expect(store.selectedDayIndex).toBe(0)

    fetchMock.mockResolvedValue(sampleIndex())
    await store.load(39.9, 116.4)
    expect(fetchMock).toHaveBeenCalledWith(39.9, 116.4, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
  })

  it('setRange 支持任意小时粒度区间并重新拉取', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    fetchMock.mockClear()

    await store.setRange(30, 6) // 明天 06:00 → 明天 11:00
    expect(store.rangeStartHour).toBe(30)
    expect(store.rangeHours).toBe(6)
    expect(store.selectedDayIndex).toBe(1)
    expect(fetchMock).toHaveBeenLastCalledWith(39.9, 116.4, {
      startHour: 30,
      hours: 6,
      signal: undefined,
    })
  })

  it('setRange 入参按 7 天窗口 clamp（起点 ≤167、长度不越过窗口末尾）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    fetchMock.mockClear()

    await store.setRange(999, 168)
    expect(store.rangeStartHour).toBe(167)
    expect(store.rangeHours).toBe(1)

    await store.setRange(-5, 0)
    expect(store.rangeStartHour).toBe(0)
    expect(store.rangeHours).toBe(1)
  })

  it('applyPreset：24h = 此刻起 24 小时；7d = 今日 00:00 起整 7 日', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)

    fetchMock.mockClear()
    await store.applyPreset('7d')
    expect(store.rangeStartHour).toBe(0)
    expect(store.rangeHours).toBe(168)
    expect(store.selectedDayIndex).toBe(0)
    expect(fetchMock).toHaveBeenLastCalledWith(39.9, 116.4, {
      startHour: 0,
      hours: 168,
      signal: undefined,
    })

    fetchMock.mockClear()
    await store.applyPreset('24h')
    expect(store.rangeStartHour).toBe(new Date().getHours())
    expect(store.rangeHours).toBe(24)
    expect(fetchMock).toHaveBeenLastCalledWith(39.9, 116.4, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
  })

  it('selectedDayIndex 由区间起点派生（月相 / 标题 / 数据三者一致）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)

    await store.setRange(0, 168)
    expect(store.selectedDayIndex).toBe(0)

    await store.setRange(47, 24) // 明天 23:00 起
    expect(store.selectedDayIndex).toBe(1)

    await store.setRange(144, 24) // 第 7 天 00:00 起
    expect(store.selectedDayIndex).toBe(6)

    await store.setRange(167, 1) // 窗口最后一小时
    expect(store.selectedDayIndex).toBe(6)
  })

  it('契约：响应为后端 snake_case（day_index/daily_moon/daily_astro）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    expect(store.data?.day_index).toBe(0)
    expect(store.data?.daily_moon).toHaveLength(7)
    expect(store.data?.daily_astro).toHaveLength(7)
    // 响应 day_index 与区间起点派生值一致（startHour=0 → 0）
    expect(store.selectedDayIndex).toBe(0)
  })

  it('I5 load 竞态：过期慢响应被丢弃，不覆盖新结果', async () => {
    const store = useStargazeStore()
    let resolveSlow: ((v: StargazeIndex) => void) | undefined
    fetchMock.mockReturnValueOnce(new Promise<StargazeIndex>((r) => { resolveSlow = r }))
    const slow = store.load(39.9, 116.4)

    fetchMock.mockResolvedValueOnce(sampleIndex({ city: '上海', score: 90 }))
    await store.load(31.2304, 121.4737)
    expect(store.data?.city).toBe('上海')

    resolveSlow!(sampleIndex({ city: '北京', score: 5 }))
    await slow
    expect(store.data?.city).toBe('上海')
    expect(store.data?.score).toBe(90)
    expect(store.status).toBe('ready')
  })

  it('I5 load 竞态：过期失败响应不置 error', async () => {
    const store = useStargazeStore()
    let rejectSlow: ((e: unknown) => void) | undefined
    fetchMock.mockReturnValueOnce(new Promise<StargazeIndex>((_, rej) => { rejectSlow = rej }))
    const slow = store.load(39.9, 116.4)

    fetchMock.mockResolvedValueOnce(sampleIndex({ city: '上海', score: 90 }))
    await store.load(31.2304, 121.4737)

    rejectSlow!(new Error('HTTP 502'))
    await slow
    expect(store.status).toBe('ready')
    expect(store.data?.city).toBe('上海')
  })

  it('locate 无 geolocation 时回退默认城市', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    store.locate()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
  })

  it('locate geolocation 成功时用真实坐标', async () => {
    // @ts-expect-error 注入 geolocation 成功回调
    navigator.geolocation = {
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 25.0, longitude: 121.0 } } as GeolocationPosition),
    }
    fetchMock.mockResolvedValue(sampleIndex({ city: '台北', lat: 25.0, lon: 121.0 }))
    const store = useStargazeStore()
    store.locate()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(25.0, 121.0, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
    expect(store.location.label).toBe('台北')
  })

  it('locate 保留当前自定义区间（不重置为 0 点）', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    await store.setRange(48, 12) // 后天 00:00 → 后天 11:00
    expect(store.selectedDayIndex).toBe(2)

    fetchMock.mockClear()
    // @ts-expect-error 注入 geolocation 成功回调
    navigator.geolocation = {
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 30.0, longitude: 120.0 } } as GeolocationPosition),
    }
    store.locate()
    await flushPromises()
    expect(store.rangeStartHour).toBe(48)
    expect(store.rangeHours).toBe(12)
    expect(fetchMock).toHaveBeenLastCalledWith(30.0, 120.0, {
      startHour: 48,
      hours: 12,
      signal: undefined,
    })
  })

  it('本地前缀命中：不发任何网络请求，searching 保持 false', async () => {
    stubCityFetch()
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()

    await store.search('成都')
    expect(store.searchResults.length).toBeGreaterThan(0)
    expect(store.searchResults[0]).toMatchObject({
      name: '成都市',
      source: 'local',
      prefix: '成都',
    })
    expect(store.searching).toBe(false)
    expect(searchCityMock).not.toHaveBeenCalled() // 关键：本地命中不碰网络

    await store.selectSearchResult(store.searchResults[0])
    expect(fetchMock).toHaveBeenLastCalledWith(30.66, 104.06, {
      startHour: store.rangeStartHour,
      hours: 24,
      signal: undefined,
    })
    expect(store.searchResults).toEqual([]) // 选中后收起
  })

  it('本地 0 命中且输入 ≥2 字 → 走在线兜底（限中国），结果标 source=online', async () => {
    stubCityFetch()
    fetchMock.mockResolvedValue(sampleIndex({ city: '冷湖' }))
    searchCityMock.mockResolvedValue([
      { name: '冷湖', admin1: '青海省', latitude: 38.0, longitude: 93.4 },
    ])
    const store = useStargazeStore()

    await store.search('冷湖')
    expect(searchCityMock).toHaveBeenCalledTimes(1)
    expect(searchCityMock.mock.calls[0][0]).toBe('冷湖')
    expect(store.searchResults).toEqual([
      {
        name: '冷湖',
        lng: 93.4,
        lat: 38.0,
        label: '在线 · 青海省',
        source: 'online',
      },
    ])
    expect(store.searching).toBe(false)
  })

  it('本地 0 命中但只有 1 个字 → 不发在线请求', async () => {
    stubCityFetch()
    const store = useStargazeStore()
    await store.search('黔')
    expect(searchCityMock).not.toHaveBeenCalled()
    expect(store.searching).toBe(false)
  })

  it('空查询清空结果；在线失败静默清空（不影响本地能力）', async () => {
    stubCityFetch()
    const store = useStargazeStore()
    await store.search('')
    expect(searchCityMock).not.toHaveBeenCalled()
    expect(store.searchResults).toEqual([])

    searchCityMock.mockRejectedValue(new Error('down'))
    await store.search('某不存在的城')
    expect(store.searching).toBe(false)
    expect(store.searchResults).toEqual([])

    // 在线失败后本地依然可用
    await store.search('成都')
    expect(store.searchResults[0].name).toBe('成都市')
  })

  it('ensureCityIndex 只加载一次，状态 idle → loading → ready', async () => {
    const fetchSpy = stubCityFetch()
    const store = useStargazeStore()
    expect(store.cityIndexStatus).toBe('idle')
    await store.ensureCityIndex()
    expect(store.cityIndexStatus).toBe('ready')
    await store.ensureCityIndex()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('城市数据加载失败：状态置 error，搜索不报错（仅返回空）', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500 })))
    const store = useStargazeStore()
    await store.search('成都')
    expect(store.cityIndexStatus).toBe('error')
    expect(store.searchResults).toEqual([])
  })
})