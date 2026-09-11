import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  buildCityIndex,
  hitToOption,
  loadCityIndex,
  resetCityIndexCache,
} from '../src/utils/cityTrie'
import { FIXTURE_PRIORITY, FIXTURE_ROWS, fixtureFetch } from './fixtures/cityFile'

/** 生产配置：预设城市参与同分优先。 */
const index = buildCityIndex(FIXTURE_ROWS, FIXTURE_PRIORITY)
/** 不带预设优先：用于验证「同分时按数据序（adcode 序）」的基线行为。 */
const plain = buildCityIndex(FIXTURE_ROWS)

const names = (q: string, limit?: number) => index.search(q, limit).map((h) => h.name)

describe('cityTrie 中文前缀查询', () => {
  it('中文前缀命中，层级高的优先（成都市 地级市 > 成县/成安县 区县）', () => {
    const hits = index.search('成')
    expect(hits.map((h) => h.name)).toEqual(['成都市', '成县', '成安县'])
    expect(hits[0].level).toBe(1)
  })

  it('完整名称 exact 最优先（成县 虽为区县，输入「成县」时排第一）', () => {
    const hits = index.search('成县')
    expect(hits[0]).toMatchObject({ name: '成县', exact: true })
    expect(hits.map((h) => h.name)).toEqual(['成县'])
    expect(index.search('锦江区')[0].name).toBe('锦江区')
  })

  it('exact 优先于层级：输入完整名「成安县」时不被 成都市 挤下去', () => {
    // 「成」前缀下有 成都市（地级市，预设）与 成安县（区县），但输入完整名时 exact 胜出
    expect(names('成安县')).toEqual(['成安县'])
  })

  it('省 / 市 / 区县三级都能按前缀命中', () => {
    expect(names('四川')).toEqual(['四川省'])
    expect(names('锦江')).toEqual(['锦江区'])
    expect(index.search('成')[0].label).toBe('四川省 · 地级市')
    expect(index.search('锦江')[0].label).toBe('四川省 · 成都市 · 区县')
  })

  it('输入首尾空格被归一化', () => {
    expect(names('  成  ')).toEqual(['成都市', '成县', '成安县'])
  })

  it('同分时预设城市优先（同为地级市时 贵阳市 在 贵港市 前）', () => {
    // 夹具里贵港市（adcode 更靠前）排在贵阳市之前 → 无预设优先时按数据序
    expect(plain.search('贵').map((h) => h.name)).toEqual(['贵港市', '贵阳市'])
    expect(names('贵')).toEqual(['贵阳市', '贵港市'])
  })

  it('limit 生效；空查询与无匹配返回空数组', () => {
    expect(names('成', 1)).toEqual(['成都市'])
    expect(names('')).toEqual([])
    expect(names('   ')).toEqual([])
    expect(names('不存在的城市')).toEqual([])
    expect(names('chengdu')).toEqual([]) // 不做拼音匹配（按需求）
  })

  it('单字符查询有界（不会因子树遍历过大卡住）', () => {
    const t0 = Date.now()
    const hits = index.search('成')
    expect(Date.now() - t0).toBeLessThan(50)
    expect(hits.length).toBe(3)
  })

  it('面包屑来自父级链，省级无路径', () => {
    const [h] = index.search('锦江')
    expect(h.path).toEqual(['四川省', '成都市'])
    const [prov] = index.search('四川')
    expect(prov.path).toEqual([])
    expect(prov.label).toBe('省级')
  })

  it('search 返回的坐标可直接用于加载指数', () => {
    const [h] = index.search('成都')
    expect(h.lat).toBe(30.66)
    expect(h.lng).toBe(104.06)
  })

  it('limit=0 返回全部候选', () => {
    expect(index.search('成', 0)).toHaveLength(3)
  })
})

describe('hitToOption', () => {
  it('本地结果带高亮前缀', () => {
    const [hit] = index.search('成')
    expect(hitToOption(hit, '成')).toMatchObject({
      source: 'local',
      name: '成都市',
      prefix: '成',
      label: '四川省 · 地级市',
    })
  })

  it('前缀去空白后传给高亮', () => {
    const [hit] = index.search('成')
    expect(hitToOption(hit, '  成 ').prefix).toBe('成')
  })
})

describe('loadCityIndex 懒加载', () => {
  afterEach(() => {
    resetCityIndexCache()
    vi.unstubAllGlobals()
  })

  it('加载并建索引；重复调用复用同一 Promise（只 fetch 一次）', async () => {
    const fetchMock = vi.fn(fixtureFetch())
    vi.stubGlobal('fetch', fetchMock)

    const a = await loadCityIndex()
    const b = await loadCityIndex()
    expect(a).toBe(b)
    expect(a.size).toBe(9)
    expect(a.search('成都')[0].name).toBe('成都市')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('传入预设城市后生效', async () => {
    vi.stubGlobal('fetch', vi.fn(fixtureFetch()))
    const idx = await loadCityIndex({ priorityNames: FIXTURE_PRIORITY })
    expect(idx.search('成')[0].name).toBe('成都市')
  })

  it('HTTP 失败抛错且不缓存（reset 后可重试成功）', async () => {
    const bad = vi.fn(() => Promise.resolve({ ok: false, status: 500 }))
    vi.stubGlobal('fetch', bad)
    await expect(loadCityIndex()).rejects.toThrow('500')

    resetCityIndexCache()
    const good = vi.fn(fixtureFetch())
    vi.stubGlobal('fetch', good)
    await expect(loadCityIndex()).resolves.toMatchObject({ size: 9 })
  })

  it('数据文件缺 items 时建出空索引（不抛错）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ v: 1 }) })),
    )
    const idx = await loadCityIndex()
    expect(idx.size).toBe(0)
    expect(idx.search('成')).toEqual([])
  })
})
