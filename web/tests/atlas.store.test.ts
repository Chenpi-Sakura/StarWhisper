import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import type { AtlasListItem, ConstellationAtlas } from '../src/types'

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

describe('atlasStore', () => {
  it('listFor(tradition) 二次调用命中内存缓存', async () => {
    listConstellationsMock.mockResolvedValue({
      tradition: 'western',
      items: [
        {
          abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
          hemisphere: 'B', bestMonth: 1, season: '冬季',
          caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'],
          tradition: 'western', star_count: 8, has_stories: true,
        } as AtlasListItem,
      ],
    })

    const { useAtlasStore } = await import('../src/stores/atlas')
    const atlas = useAtlasStore()
    await atlas.listFor('western')
    await atlas.listFor('western')
    expect(listConstellationsMock).toHaveBeenCalledTimes(1)
    expect(atlas.currentItems).toHaveLength(1)
  })

  it('getAtlas(tradition, abbr) 第二次同 key 命中缓存', async () => {
    const sample = {
      ok: true, abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
      hemisphere: 'B', bestMonth: 1, season: '冬季',
      caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'],
      tradition: 'western',
      stars: {}, lines: [], viewBox: { width: 640, height: 460 },
    } as unknown as ConstellationAtlas
    getConstellationMock.mockResolvedValue(sample)

    const { useAtlasStore } = await import('../src/stores/atlas')
    const atlas = useAtlasStore()
    const a = await atlas.getAtlas('western', 'ori')
    const b = await atlas.getAtlas('western', 'ori')
    expect(a).toStrictEqual(b)
    expect(getConstellationMock).toHaveBeenCalledTimes(1)
  })
})
