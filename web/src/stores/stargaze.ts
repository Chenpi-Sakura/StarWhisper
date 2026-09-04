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

  return {
    status, data, errorMessage, rangeDays, location,
    load, setRange, locate,
  }
})