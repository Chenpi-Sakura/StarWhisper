/**
 * 中国城市前缀索引（trie）—— 只做**中文名**前缀匹配
 *
 * 数据文件由 `pnpm gen:cities` 生成到 `public/data/cn-cities.json`，运行时按需 fetch
 * （不进首屏 bundle）。3237 条省/地级市/区县名称挂在同一棵前缀树上：
 * 输入「成」即时得到 成都市 / 成县 / 成安县…，输入「四川省」得到省级条目。
 *
 * 本模块是纯函数 + 单例缓存，不依赖 Vue，便于单测。
 */
/** 层级：2=省级 1=地级市 0=区县。 */
export type CityLevel = 2 | 1 | 0

/**
 * 数据文件中的紧凑元组：`[名称, 经度, 纬度, 层级, 父级下标]`
 * （由 `scripts/gen-cities.mjs` 生成，见 `docs/plans/2026-09-12-city-search-trie.md`）
 */
export type CityRow = [string, number, number, CityLevel, number]

/** 数据文件顶层结构。 */
export interface CityFile {
  v: number
  generated: string
  src: string
  items: CityRow[]
}

/** 单条命中的展示信息。 */
export interface CityHit {
  /** 数据源坐标顺序号（排序稳定用） */
  order: number
  name: string
  lng: number
  lat: number
  level: CityLevel
  /** 面包屑（不含自身），如 ['四川省','成都市'] */
  path: string[]
  /** 输入恰好等于该城市名（排序最优先） */
  exact: boolean
  /** 预设城市优先级（越小越优先；非预设排最后） */
  priority: number
  /** 展示用副标题，如 '四川省 · 成都市 · 区县' */
  label: string
}

/** 下拉列表统一选项（本地结果 + 在线兜底结果）。 */
export interface CityOption {
  name: string
  lng: number
  lat: number
  /** 副标题（层级 / 省份信息） */
  label: string
  source: 'local' | 'online'
  /** 需要高亮的输入前缀（仅本地结果） */
  prefix?: string
}

interface TrieNode {
  children: Map<string, TrieNode>
  /** 以该节点结尾的条目下标 */
  hits: number[]
}

const LEVEL_LABEL: Record<CityLevel, string> = {
  2: '省级',
  1: '地级市',
  0: '区县',
}

/** 单次查询最多收集的候选数（防「单字符」查询遍历整棵子树；排序后只取前几条）。 */
const MAX_CANDIDATES = 400

/** 下拉默认条数。 */
export const DEFAULT_LIMIT = 8

function makeNode(): TrieNode {
  return { children: new Map(), hits: [] }
}

function insert(root: TrieNode, key: string, id: number): void {
  if (!key) return
  let node = root
  for (const ch of key) {
    let next = node.children.get(ch)
    if (!next) {
      next = makeNode()
      node.children.set(ch, next)
    }
    node = next
  }
  if (node.hits[node.hits.length - 1] !== id) node.hits.push(id)
}

/** 从匹配节点出发收集子树内的全部条目下标（深度优先，幂等去重）。 */
function collectIds(node: TrieNode): number[] {
  const out: number[] = []
  const seen = new Set<number>()
  const stack: TrieNode[] = [node]
  while (stack.length) {
    const cur = stack.pop() as TrieNode
    for (const id of cur.hits) {
      if (!seen.has(id)) {
        seen.add(id)
        out.push(id)
      }
    }
    if (out.length >= MAX_CANDIDATES) break
    for (const child of cur.children.values()) stack.push(child)
  }
  return out
}

export interface CityIndex {
  rows: CityRow[]
  /** 条目数 */
  size: number
  /** 前缀查询；`query` 为空返回 [] */
  search(query: string, limit?: number): CityHit[]
}

/**
 * 构建前缀索引。3237 条约 5ms，只在数据加载完成后执行一次。
 *
 * @param priorityNames 预设城市名（写「成都」或「成都市」都能匹配），同分时它们排前——
 *   例如「南」这类歧义前缀，优先给出预设里的 南京市 / 南昌市。
 */
export function buildCityIndex(items: CityRow[], priorityNames: string[] = []): CityIndex {
  const root = makeNode()
  for (let id = 0; id < items.length; id++) insert(root, items[id][0], id)

  const pathCache = new Map<number, string[]>()
  const priorityMap = new Map<string, number>()
  priorityNames.forEach((n, i) => priorityMap.set(n, i + 1))

  /** 预设城市序号（越小越优先）；非预设返回 undefined。 */
  function rankOf(name: string): number | undefined {
    for (const [n, rank] of priorityMap) {
      if (name === n || name.startsWith(n)) return rank
    }
    return undefined
  }

  // 预设优先级在建索引时算一次，查询时零开销（非预设排在所有预设之后）
  const NON_PRIORITY = priorityMap.size + 1
  const priorityRank: number[] = items.map((row) => rankOf(row[0]) ?? NON_PRIORITY)

  function pathOf(id: number): string[] {
    const cached = pathCache.get(id)
    if (cached) return cached
    const path: string[] = []
    let p = items[id][4]
    let guard = 0
    while (p >= 0 && p < items.length && guard++ < 4) {
      path.unshift(items[p][0])
      p = items[p][4]
    }
    pathCache.set(id, path)
    return path
  }

  function toHit(id: number, q: string): CityHit {
    const [name, lng, lat, level] = items[id]
    const path = pathOf(id)
    return {
      order: id,
      name,
      lng,
      lat,
      level,
      path,
      exact: name === q,
      priority: priorityRank[id],
      label: [...path, LEVEL_LABEL[level]].join(' · '),
    }
  }

  function compare(a: CityHit, b: CityHit): number {
    if (a.exact !== b.exact) return a.exact ? -1 : 1
    if (a.priority !== b.priority) return a.priority - b.priority
    if (a.level !== b.level) return b.level - a.level
    if (a.name.length !== b.name.length) return a.name.length - b.name.length
    return a.order - b.order
  }

  function search(query: string, limit: number = DEFAULT_LIMIT): CityHit[] {
    const q = query.trim()
    if (!q) return []
    let node: TrieNode | undefined = root
    for (const ch of q) {
      node = node.children.get(ch)
      if (!node) return []
    }
    const hits = collectIds(node).map((id) => toHit(id, q))
    hits.sort(compare)
    return limit > 0 ? hits.slice(0, limit) : hits
  }

  return { rows: items, size: items.length, search }
}

/** 本地索引 → 下拉选项（带上高亮前缀）。 */
export function hitToOption(hit: CityHit, query: string): CityOption {
  return {
    name: hit.name,
    lng: hit.lng,
    lat: hit.lat,
    label: hit.label,
    source: 'local',
    prefix: query.trim(),
  }
}

/** 城市数据文件地址（跟随 vite base，支持子路径部署）。 */
export const CITY_DATA_URL = `${import.meta.env.BASE_URL}data/cn-cities.json`

let cached: Promise<CityIndex> | null = null

/** 懒加载选项。 */
export interface LoadOptions {
  url?: string
  fetchImpl?: typeof fetch
  /** 预设城市名，同分时优先 */
  priorityNames?: string[]
}

/** 懒加载城市数据并建索引（模块级单例；失败不缓存，可重试）。 */
export function loadCityIndex(opts: LoadOptions = {}): Promise<CityIndex> {
  const { url = CITY_DATA_URL, fetchImpl = fetch, priorityNames = [] } = opts
  if (!cached) {
    cached = fetchImpl(url)
      .then((r) => {
        if (!r.ok) throw new Error(`城市数据加载失败：HTTP ${r.status}`)
        return r.json() as Promise<CityFile>
      })
      .then((file) => buildCityIndex(file.items ?? [], priorityNames))
      .catch((e) => {
        cached = null
        throw e
      })
  }
  return cached
}

/** 测试用：清空单例缓存。 */
export function resetCityIndexCache(): void {
  cached = null
}
