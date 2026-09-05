import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { StargazeIndex } from '../types'
import { fetchStargazeIndex } from '../api/stargaze'

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
  const rangeDays = ref<1 | 7>(1)
  const location = ref<StargazeLocation>({ ...DEFAULT_LOCATION })

  async function load(lat: number, lon: number, days: 1 | 7 = rangeDays.value): Promise<void> {
    status.value = 'loading'
    errorMessage.value = null
    try {
      const result = await fetchStargazeIndex(lat, lon, { days })
      data.value = result
      location.value = { lat, lon, label: result.city }
      status.value = 'ready'
    } catch {
      status.value = 'error'
      errorMessage.value = '天气服务暂不可用，请稍后重试'
    }
  }

  /** 切 24h / 7 天曲线：用当前坐标重新拉取。 */
  async function setRange(days: 1 | 7): Promise<void> {
    rangeDays.value = days
    await load(location.value.lat, location.value.lon, days)
  }

  /** 浏览器定位；失败（无权限/超时）回退默认城市。 */
  function locate(): void {
    if (!('geolocation' in navigator)) {
      load(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        load(pos.coords.latitude, pos.coords.longitude)
      },
      () => {
        load(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon)
      },
      { timeout: 6000, maximumAge: 300000 },
    )
  }

  /** 通过预设城市选择。 */
  async function selectCity(city: StargazeLocation): Promise<void> {
    await load(city.lat, city.lon)
  }

  return {
    status, data, errorMessage, rangeDays, location,
    load, setRange, locate, selectCity,
  }
})