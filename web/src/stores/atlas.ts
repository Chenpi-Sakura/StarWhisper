import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import type { AtlasListItem, ConstellationAtlas, TraditionListItem } from '../types'
import { listTraditions, listConstellations, getConstellation } from '../api/atlas'

export const useAtlasStore = defineStore('atlas', () => {
  const traditions = ref<TraditionListItem[]>([])
  const currentTradition = ref<string>('western')

  const itemsByTradition = ref<Record<string, AtlasListItem[]>>({})
  const atlasCache = ref<Record<string, ConstellationAtlas>>({}) // key: `${tradition}/${abbr}`

  async function loadTraditions(): Promise<void> {
    if (traditions.value.length > 0) return
    const r = await listTraditions()
    traditions.value = r.items
  }

  async function setTradition(key: string): Promise<void> {
    if (currentTradition.value === key && itemsByTradition.value[key]) return
    currentTradition.value = key
    if (!itemsByTradition.value[key]) {
      await listFor(key)
    }
  }

  async function listFor(tradition: string): Promise<void> {
    if (itemsByTradition.value[tradition]) return  // 缓存命中跳过
    const r = await listConstellations(tradition)
    itemsByTradition.value = { ...itemsByTradition.value, [tradition]: r.items }
  }

  async function getAtlas(tradition: string, abbr: string): Promise<ConstellationAtlas> {
    const cacheKey = `${tradition}/${abbr}`
    if (atlasCache.value[cacheKey]) return atlasCache.value[cacheKey]
    const data = await getConstellation(tradition, abbr)
    atlasCache.value = { ...atlasCache.value, [cacheKey]: data }
    return data
  }

  const currentItems = computed<AtlasListItem[]>(
    () => itemsByTradition.value[currentTradition.value] ?? [],
  )

  return {
    traditions, currentTradition, itemsByTradition, atlasCache,
    currentItems, loadTraditions, setTradition, listFor, getAtlas,
  }
})
