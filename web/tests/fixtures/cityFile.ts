/**
 * 城市前缀索引测试夹具（与 `public/data/cn-cities.json` 同格式的极小数据集）
 *
 * 元组含义：`[名称, 经度, 纬度, 层级, 父级下标]`
 * 层级：2=省级 1=地级市 0=区县
 */
import type { CityFile, CityRow } from '../../src/utils/cityTrie'

export const FIXTURE_ROWS: CityRow[] = [
  ['四川省', 104.07, 30.65, 2, -1],
  ['承德市', 117.94, 40.98, 1, -1],
  ['成都市', 104.06, 30.66, 1, 0],
  ['锦江区', 104.08, 30.65, 0, 2],
  ['成县', 105.7, 33.7, 0, -1],
  ['重庆市', 106.55, 29.56, 1, -1],
  ['成安县', 114.67, 36.44, 0, -1],
  // 同为地级市、同为 3 字、数据序靠前的非预设城市（验证同分时预设优先）
  ['贵港市', 109.6, 23.11, 1, -1],
  ['贵阳市', 106.63, 26.65, 1, -1],
]

/** 夹具里 20 个预设城市中的三个（用于验证同分时预设优先）。 */
export const FIXTURE_PRIORITY = ['成都市', '重庆市', '贵阳市']

export const FIXTURE_FILE: CityFile = {
  v: 1,
  generated: '2026-09-12',
  src: 'fixture',
  items: FIXTURE_ROWS,
}

/** 生成一个「返回夹具数据」的 fetch 桩。 */
export function fixtureFetch(): typeof fetch {
  return (() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(FIXTURE_FILE),
    })) as unknown as typeof fetch
}
