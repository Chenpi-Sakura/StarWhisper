import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { StargazeIndex } from '../types'
import { fetchStargazeIndex } from '../api/stargaze'
import { searchCity } from '../api/geocoding'
import {
  DEFAULT_LIMIT,
  hitToOption,
  loadCityIndex,
  type CityIndex,
  type CityOption,
} from '../utils/cityTrie'
import { currentHourOffset, MAX_HOUR_OFFSET } from '../utils/stargazeRange'

export type StargazeStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface StargazeLocation {
  lat: number
  lon: number
  label: string
}

/** 定位失败时的兜底城市（北京）。 */
export const DEFAULT_LOCATION: StargazeLocation = {
  lat: 39.9042,
  lon: 116.4074,
  label: '北京',
}

/** 预设城市列表（用于下拉选择）。 */
export const PRESET_CITIES: StargazeLocation[] = [
  { lat: 39.9042, lon: 116.4074, label: '北京' },
  { lat: 31.2304, lon: 121.4737, label: '上海' },
  { lat: 23.1291, lon: 113.2644, label: '广州' },
  { lat: 22.5431, lon: 114.0579, label: '深圳' },
  { lat: 30.5728, lon: 104.0668, label: '成都' },
  { lat: 30.2741, lon: 120.1551, label: '杭州' },
  { lat: 32.0603, lon: 118.7969, label: '南京' },
  { lat: 34.7466, lon: 113.6254, label: '郑州' },
  { lat: 34.2658, lon: 108.9541, label: '西安' },
  { lat: 36.6512, lon: 116.9972, label: '济南' },
  { lat: 28.2282, lon: 112.9388, label: '长沙' },
  { lat: 26.0745, lon: 119.2965, label: '福州' },
  { lat: 45.7500, lon: 126.6500, label: '哈尔滨' },
  { lat: 43.8171, lon: 87.6169, label: '乌鲁木齐' },
  { lat: 29.5630, lon: 106.5516, label: '重庆' },
  { lat: 25.0389, lon: 102.7183, label: '昆明' },
  { lat: 26.6470, lon: 106.6302, label: '贵阳' },
  { lat: 36.0671, lon: 120.3826, label: '青岛' },
  { lat: 38.0428, lon: 114.5149, label: '石家庄' },
  { lat: 37.8706, lon: 112.5489, label: '太原' },
]

export const ONLINE_FALLBACK_DELAY_MS = 250

/** 在线兜底前的防抖等待。 */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

export const useStargazeStore = defineStore('stargaze', () => {
  const status = ref<StargazeStatus>('idle')
  const data = ref<StargazeIndex | null>(null)
  const errorMessage = ref<string | null>(null)
  /**
   * FIG.2 区间起点（相对今日 00:00 的小时偏移，0-167）。
   * 默认 = 当前整点（不是 0 点）：进页面先看「此刻起」的夜空条件。
   */
  const rangeStartHour = ref(
    Math.max(0, Math.min(MAX_HOUR_OFFSET, currentHourOffset())),
  )
  /** FIG.2 区间长度（整点数，1-168）。 */
  const rangeHours = ref(24)
  /**
   * 当前区间起点所在自然日（0=今天…最大 6）——FIG.3 月相 / astro chips 按此取 daily 切片。
   * 由 rangeStartHour 派生，保证「区间起点 / 月相 / 标题」三者永远一致。
   */
  const selectedDayIndex = computed(() =>
    Math.max(0, Math.min(6, Math.floor(rangeStartHour.value / 24))),
  )
  const location = ref<StargazeLocation>({ ...DEFAULT_LOCATION })

  /** 请求序号守卫：快速切换区间/城市时丢弃过期响应，避免慢响应覆盖新结果。 */
  let loadSeq = 0

  async function load(
    lat: number,
    lon: number,
    options: {
      startHour?: number
      hours?: number
      signal?: AbortSignal
    } = {},
  ): Promise<void> {
    const seq = ++loadSeq
    const startHour = options.startHour ?? rangeStartHour.value
    const hours = options.hours ?? rangeHours.value
    status.value = 'loading'
    errorMessage.value = null
    try {
      const result = await fetchStargazeIndex(lat, lon, {
        startHour,
        hours,
        signal: options.signal,
      })
      if (seq !== loadSeq) return // 过期响应丢弃
      data.value = result
      location.value = { lat, lon, label: result.city }
      status.value = 'ready'
    } catch (e) {
      if (seq !== loadSeq || (e as Error).name === 'AbortError') return
      status.value = 'error'
      errorMessage.value = '天气服务暂不可用，请稍后重试'
    }
  }

  /**
   * 设定任意小时粒度区间 `[startHour, startHour + hours - 1]` 并重新拉取。
   * 入参按 7 天窗口 clamp（startHour 0-167，hours 至少 1 且不越过窗口末尾）。
   */
  async function setRange(startHour: number, hours: number): Promise<void> {
    const s = Math.max(0, Math.min(MAX_HOUR_OFFSET, Math.floor(startHour)))
    const h = Math.max(1, Math.min(168 - s, Math.floor(hours)))
    rangeStartHour.value = s
    rangeHours.value = h
    await load(location.value.lat, location.value.lon, {
      startHour: s,
      hours: h,
    })
  }

  /**
   * 快捷预设：
   * - `24h` → 此刻起 24 小时（默认视图，起点跟随当前整点）
   * - `7d`  → 今日 00:00 起整 7 日（168 个整点）
   */
  async function applyPreset(preset: '24h' | '7d'): Promise<void> {
    if (preset === '7d') {
      await setRange(0, 168)
      return
    }
    const s = Math.max(0, Math.min(MAX_HOUR_OFFSET, currentHourOffset()))
    await setRange(s, 24)
  }

  /** 浏览器定位；失败（无权限/超时）回退默认城市。当前区间选择保持不变。 */
  function locate(): void {
    const range = { startHour: rangeStartHour.value, hours: rangeHours.value }
    if (!('geolocation' in navigator)) {
      load(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon, range)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        load(pos.coords.latitude, pos.coords.longitude, range)
      },
      () => {
        load(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon, range)
      },
      { timeout: 6000, maximumAge: 300000 },
    )
  }

  const searchResults = ref<CityOption[]>([])
  /** 本地城市表加载态（首次聚焦搜索框时懒加载）。 */
  const cityIndexStatus = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  /** 是否正在等在线兜底结果（本地命中时为 false——本地查询无需等待）。 */
  const searching = ref(false)

  let cityIndex: CityIndex | null = null
  let onlineController: AbortController | null = null
  /** 查询代次：防抖窗口内出现新查询时，旧查询直接放弃（防止旧响应/旧请求覆盖新结果）。 */
  let searchGen = 0

  /** 懒加载本地城市前缀索引（单例，重复调用复用）。 */
  async function ensureCityIndex(): Promise<void> {
    if (cityIndexStatus.value === 'ready' || cityIndexStatus.value === 'loading') return
    cityIndexStatus.value = 'loading'
    try {
      cityIndex = await loadCityIndex({ priorityNames: PRESET_CITIES.map((c) => c.label) })
      cityIndexStatus.value = 'ready'
    } catch {
      cityIndexStatus.value = 'error'
    }
  }

  /**
   * 城市搜索：本地前缀索引优先（零延迟、无网络）。
   *
   * - 本地有命中 → 直接返回，**不发任何请求**
   * - 本地 0 命中且输入 ≥ 2 字 → 在线兜底（限中国），覆盖行政区划表外的镇/景区
   */
  async function search(query: string): Promise<void> {
    const q = query.trim()
    const gen = ++searchGen
    if (onlineController) {
      onlineController.abort()
      onlineController = null
    }
    if (!q) {
      searchResults.value = []
      searching.value = false
      return
    }
    if (!cityIndex) await ensureCityIndex()
    if (gen !== searchGen) return // 其间又有新查询 → 丢弃本次
    const local = cityIndex ? cityIndex.search(q, DEFAULT_LIMIT) : []
    if (local.length) {
      searchResults.value = local.map((h) => hitToOption(h, q))
      searching.value = false
      return
    }
    searchResults.value = []
    if (q.length < 2) {
      searching.value = false
      return
    }
    // 本地 0 命中 → 等防抖窗口再走在线兜底（避免逐字敲打时刷接口）
    searching.value = true
    await delay(ONLINE_FALLBACK_DELAY_MS)
    if (gen !== searchGen) return
    onlineController = new AbortController()
    try {
      const online = await searchCity(q, onlineController.signal)
      searchResults.value = online.map((r) => ({
        name: r.name,
        lng: r.longitude,
        lat: r.latitude,
        label: ['在线', r.admin1, r.admin2].filter(Boolean).join(' · '),
        source: 'online' as const,
      }))
    } catch {
      searchResults.value = []
    } finally {
      searching.value = false
      onlineController = null
    }
  }

  /** 选中搜索结果并加载该坐标指数（区间选择保持不变）。 */
  async function selectSearchResult(o: CityOption): Promise<void> {
    searchResults.value = []
    await load(o.lat, o.lng, {
      startHour: rangeStartHour.value,
      hours: rangeHours.value,
    })
  }

  return {
    status, data, errorMessage, rangeStartHour, rangeHours, selectedDayIndex,
    location, load, setRange, applyPreset, locate,
    searchResults, searching, search, selectSearchResult,
    cityIndexStatus, ensureCityIndex,
  }
})