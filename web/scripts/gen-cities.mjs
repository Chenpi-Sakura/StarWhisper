/**
 * 生成中国城市前缀索引数据：`public/data/cn-cities.json`
 *
 * 用法：`pnpm gen:cities`（需联网一次）
 *
 * 数据源：DataV.GeoAtlas 行政区划（单请求返回全部省/市/区县 + 经纬度）。
 * 只做**中文名**前缀匹配（按需求不引入拼音/首字母，无第三方依赖）。
 *
 * 产物格式（紧凑元组，省字节）：
 * ```json
 * { "v": 1, "generated": "2026-09-12", "src": "...", "items": [
 *   ["成都市", 104.0657, 30.6595, 1, 21]
 * ]}
 * ```
 * 元组含义：`[名称, 经度, 纬度, 层级, 父级下标]`
 * - 层级：2=省级 1=地级市 0=区县
 * - 父级下标：指向同一 `items` 数组中的省/市条目，-1 表示无父级（省级）
 *   注意必须用**过滤后**的数组下标（原始数组含国级，直接用会整条链错位）
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC_URL = 'https://geo.datav.aliyun.com/areas_v3/bound/all.json'
const OUT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'public',
  'data',
  'cn-cities.json',
)

/** DataV 的 level → 数字层级（国级被过滤掉）。 */
const LEVELS = { province: 2, city: 1, district: 0 }

/** 经纬度保留 4 位小数（≈11m，足够城市级定位），显著减小文件体积。 */
const round4 = (x) => Math.round(x * 10000) / 10000

async function main() {
  const r = await fetch(SRC_URL)
  if (!r.ok) throw new Error(`拉取行政区划失败：HTTP ${r.status}`)
  const raw = await r.json()
  if (!Array.isArray(raw)) throw new Error('行政区划数据格式异常：期望数组')

  const kept = raw.filter((it) => LEVELS[it.level] !== undefined)
  const rowIndex = new Map(kept.map((it, i) => [it.adcode, i]))

  const rows = kept.map((it) => [
    it.name,
    round4(it.lng),
    round4(it.lat),
    LEVELS[it.level],
    it.parent == null ? -1 : (rowIndex.get(it.parent) ?? -1),
  ])

  // 自检：父级必须存在、层级更高，且省级无父级
  rows.forEach(([name, , , level, parent], i) => {
    if (level === 2) {
      if (parent !== -1) throw new Error(`省级条目不应有父级：${name}`)
      return
    }
    if (parent < 0 || parent >= rows.length) {
      throw new Error(`父级下标越界：${name} → ${parent}（行 ${i}）`)
    }
    if (rows[parent][3] <= level) {
      throw new Error(`父级层级不高于自身：${name} → ${rows[parent][0]}`)
    }
    if (parent === i) throw new Error(`父级指向自己：${name}`)
  })

  const out = {
    v: 1,
    generated: new Date().toISOString().slice(0, 10),
    src: 'DataV.GeoAtlas areas_v3/bound/all.json',
    items: rows,
  }
  const json = JSON.stringify(out)
  mkdirSync(dirname(OUT), { recursive: true })
  writeFileSync(OUT, json, 'utf8')

  const counts = rows.reduce((acc, row) => {
    const key = ['县区', '地级市', '省级'][row[3]]
    acc[key] = (acc[key] ?? 0) + 1
    return acc
  }, {})
  console.log(`✓ 写入 ${OUT}`)
  console.log(`  条目 ${rows.length}（${JSON.stringify(counts)}）`)
  console.log(`  体积 ${(json.length / 1024).toFixed(1)} KB`)
}

main().catch((e) => {
  console.error('✗ 生成失败：', e.message)
  process.exit(1)
})
