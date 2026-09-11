/**
 * 生成产物 `public/data/cn-cities.json` 的完整性测试
 *
 * 直接读磁盘文件（而非 import），确保**实际发布的那份数据**结构正确、
 * 坐标在中国境内、父级链可回溯、中文前缀查询可用。
 * 数据由 `pnpm gen:cities` 生成，见 `docs/plans/2026-09-12-city-search-trie.md`。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { buildCityIndex, type CityFile } from '../src/utils/cityTrie'
import { PRESET_CITIES } from '../src/stores/stargaze'

const FILE = resolve(__dirname, '..', 'public', 'data', 'cn-cities.json')
const file = JSON.parse(readFileSync(FILE, 'utf8')) as CityFile

/** 生产同款索引（带预设城市优先）。 */
const index = buildCityIndex(file.items, PRESET_CITIES.map((c) => c.label))

describe('cn-cities.json 数据完整性', () => {
  it('结构元信息齐全', () => {
    expect(file.v).toBe(1)
    expect(file.src).toContain('DataV.GeoAtlas')
    expect(file.generated).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('覆盖省 / 地级市 / 区县三级，总量约 3000+', () => {
    const byLevel = file.items.reduce<Record<number, number>>((acc, r) => {
      acc[r[3]] = (acc[r[3]] ?? 0) + 1
      return acc
    }, {})
    expect(file.items.length).toBeGreaterThan(3000)
    expect(byLevel[2]).toBe(34) // 省级
    expect(byLevel[1]).toBeGreaterThan(300) // 地级市
    expect(byLevel[0]).toBeGreaterThan(2000) // 区县
  })

  it('每行字段合法：名称非空、坐标在中国境内、层级合法', () => {
    for (const [name, lng, lat, level, parent] of file.items) {
      expect(typeof name).toBe('string')
      expect(name.length).toBeGreaterThan(1)
      expect([0, 1, 2]).toContain(level)
      expect(lng).toBeGreaterThanOrEqual(73)
      expect(lng).toBeLessThanOrEqual(136)
      expect(lat).toBeGreaterThanOrEqual(3)
      expect(lat).toBeLessThanOrEqual(54)
      expect(parent === -1 || (parent >= 0 && parent < file.items.length)).toBe(true)
    }
  })

  it('父级链正确：市/县可回溯到省，省级无父级', () => {
    file.items.forEach(([name, , , level, parent], i) => {
      if (level === 2) {
        expect(parent).toBe(-1)
        return
      }
      expect(parent).toBeGreaterThanOrEqual(0)
      expect(file.items[parent][3]).toBeGreaterThan(level) // 父级层级必须更高
      expect(file.items[parent][0]).not.toBe(name) // 不能指向自己
      expect(parent).not.toBe(i)
    })
  })

  it('区县条目的三级面包屑可回溯（锦江区 → 四川省 · 成都市）', () => {
    const [jinjiang] = index.search('锦江')
    expect(jinjiang.name).toBe('锦江区')
    expect(jinjiang.path).toEqual(['四川省', '成都市'])
    const [chengdu] = index.search('成都')
    expect(chengdu.name).toBe('成都市')
    expect(chengdu.path).toEqual(['四川省'])
    expect(chengdu.label).toBe('四川省 · 地级市')
  })

  it('中文前缀命中，且完整名称 exact 首位', () => {
    const hits = index.search('成')
    expect(hits.length).toBeGreaterThan(0)
    expect(hits.map((h) => h.name)).toContain('成都市')
    expect(index.search('成')[0].name).toBe('成都市')
    expect(index.search('成都市')[0]).toMatchObject({ name: '成都市', exact: true })
    expect(index.search('四川省')[0].name).toBe('四川省')
  })

  it('预设城市参与同分优先（南 → 南京市 与 南昌市 都在非预设的 南充市 前）', () => {
    const hits = index.search('南')
    const names = hits.map((h) => h.name)
    expect(names).toContain('南京市')
    expect(names.indexOf('南京市')).toBeLessThan(names.indexOf('南充市'))
  })

  it('不做拼音匹配（按需求只支持中文）', () => {
    expect(index.search('chengdu')).toEqual([])
    expect(index.search('cd')).toEqual([])
  })

  it('建索引耗时可控（3237 条 < 100ms）', () => {
    const t0 = Date.now()
    buildCityIndex(file.items)
    expect(Date.now() - t0).toBeLessThan(100)
  })

  it('单字符查询有界（不会因子树过大卡住）', () => {
    const t0 = Date.now()
    const hits = index.search('新') // 「新」开头的区县很多（新城区/新乐市/新和县…）
    expect(Date.now() - t0).toBeLessThan(50)
    expect(hits.length).toBe(8) // 默认 limit
  })
})
