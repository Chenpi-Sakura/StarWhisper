import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { StargazeIndex } from '../types'
import { fetchStargazeIndex } from '../api/stargaze'
import { searchCity, type GeoResult } from '../api/geocoding'
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

  /** 通过预设城市选择（区间选择保持不变）。 */
  async function selectCity(city: StargazeLocation): Promise<void> {
    await load(city.lat, city.lon, {
      startHour: rangeStartHour.value,
      hours: rangeHours.value,
    })
  }

  const searchResults = ref<GeoResult[]>([])
  const searching = ref(false)

  /** 任意城市模糊搜索；空串清空，异常静默清空。 */
  async function search(query: string, signal?: AbortSignal): Promise<void> {
    const q = query.trim()
    if (!q) {
      searchResults.value = []
      return
    }
    searching.value = true
    try {
      searchResults.value = await searchCity(q, signal)
    } catch {
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  /** 选中搜索结果并加载该坐标指数（区间选择保持不变）。 */
  async function selectSearchResult(r: GeoResult): Promise<void> {
    searchResults.value = []
    await load(r.latitude, r.longitude, {
      startHour: rangeStartHour.value,
      hours: rangeHours.value,
    })
  }

  return {
    status, data, errorMessage, rangeStartHour, rangeHours, selectedDayIndex,
    location, load, setRange, applyPreset, locate, selectCity,
    searchResults, searching, search, selectSearchResult,
  }
})