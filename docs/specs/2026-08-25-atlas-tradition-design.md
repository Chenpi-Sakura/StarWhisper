# Atlas Tradition 架构设计规格

> **目的**：把星座图鉴从"5 个西方星座硬编码"扩展为"任意 tradition × 任意星座 JSON 可被自动识别"，为西方 88 + 中国二十八宿/三垣 数据补齐铺路。

**日期**：2026-08-25
**状态**：v3 — 二审后修订
**范围**：数据架构 / 后端 API / 前端 store+UI / 标注 / 测试

## 修订记录

- v3: `visible_stars` 按命中的 constellation 过滤；删 3.6 重复段；`displayNameFor` 统一用 `\|\|` 鬼底（防 `""` 失效）；`stories` 表述明确为“key 必存 + title 占位可 + paragraphs 可空”；`_load_all` double-check locking + docstring 改“显式调用 + idempotent”；端点无 tradition 明确 422；`build_star_catalog` 加精度说明；`_angular_separation` 加高赤纬 TODO；`AtlasListItem` 补 `star_count/has_stories`；RA wrap 测试用 mock fixture 构造跨零度数据
- v2: RA 跨零度修正、中国目录平铺、MVP 故事只 2 套、hit_stars→visible_stars、list 加 star_count/has_stories、fail-fast 改成 fail-soft、ScanView→StarCanvas tradition 链路、name_zh 兜底、validate_atlas 第一阶段末尾跑、_load_all startup 加载

---

## 1. 数据架构（单源集中）

### 1.1 目录结构（**平铺**，分组信息走字段）

> **决策**：MVP 阶段 `chinese/` 与 `western/` 都是单层平铺。分组信息（“三垣”、“二十八宿”）走 JSON 字段（`mansion` / `asterism_id`），不靠子目录。原因：
> - `_load_all` 只需要 `glob("*.json")`，实现简单
> - 字段里查“所有参宿”比走子目录遍历更直接
> - 若未来需要按子目录隔离，交给 `traditions/{name}/_group/{abbr}.json` 后续拓展点

```
server/data/traditions/
├── western/                          # 西方 88 星座（IAU 标准）
│   ├── and.json                      # 仙女座
│   ├── ori.json                      # 猎户座
│   ├── sco.json
│   ├── cyg.json
│   ├── leo.json
│   └── ...（要补到 88 个；MVP 阶段先做 5 个）
└── chinese/                          # 中国古代天文
    ├── ziweiyuan.json                # 紫微垣（asterism_id="ziweiyuan"）
    ├── taiweiyuan.json               # 太微垣
    ├── tianshiyuan.json              # 天市垣
    ├── shen.json                     # 参宿（mansion="shen"）
    ├── xin.json                      # 心宿
    ├── bi.json                       # 毕宿
    └── ...（28 宿 + 三垣主星；MVP 阶段空目录 + .gitkeep）
```

**自动发现规则**：
- 一级子目录名 = `tradition` 标签（`western` / `chinese`）
- 文件名（去 `.json` 后缀）= `abbr`
- 文件内 `abbr` 字段必须等于文件名（启动时 soft-fail，单文件坏不拄服务，详见 2.1）
- **不需要文件名带 tradition 前缀**——目录本身就是命名空间

### 1.2 JSON Schema（每个星座）

```jsonc
{
  "abbr": "ori",                                       // 必须等于文件名
  "name": "猎户座",                                     // 主显示名
  "latin": "Orion",                                    // 西方名；纯中国星座可空字符串
  "season": "冬",                                       // 主季节
  "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
  "viewBox": { "width": 500, "height": 300 },
  "center": {                                            // ★ 新增：WCS 反查用中心坐标
    "ra": 86.0,                                          //   赤经（deg，0-360；与 stars.*.ra 同坐标轴）
    "dec": -2.0                                          //   赤纬（deg，-90 到 +90）
  },                                                     // center 必须是真实天球坐标（IAU 边界中心或主星质心），不是手画图像中心

  "stars": {                                            // key = 内部星位 id
    "betelgeuse": {
      "x": 144, "y": 62,                                // 手画像素坐标（当前渲染用）
      "bayer": "α Ori",                                  // 拜尔编号（西方显示）
      "name": "Betelgeuse",                             // 西方常用名
      "name_zh": "参宿四",                                // 中国古名（按 tradition 切换显示）
      "magnitude": 0.42,                                // 星等
      "ra": 88.79,                                       // 赤经（deg）
      "dec": 7.41,                                       // 赤纬（deg）
      "label": true                                       // ★ 新增：是否常驻标注
    }
  },

  "lines": [
    ["betelgeuse", "bellatrix"],
    ["meissa", "betelgeuse"]
  ],

  "mansion": null,                                       // 中国二十八宿专用：本宿英文名（西方为 null）
  "asterism_id": null,                                  // 中国三垣专用：所属垣 id（西方为 null）

  "stories": {                                           // ★ 新增：故事内嵌
    "myth": {
      "epic":  { "title": "...", "paragraphs": ["..."] },    // MVP：epic 可只占位 title + 空 paragraphs
      "chat":  { "title": "...", "paragraphs": ["..."] },    // MVP：chat 同上
      "brief": { "title": "...", "paragraphs": ["..."] }     // brief 是 MVP 唯一完整填的
    },
    "science": {
      "epic":  { "title": "...", "paragraphs": ["..."] },
      "chat":  { "title": "...", "paragraphs": ["..."] },
      "brief": { "title": "...", "paragraphs": ["..."] }
    }
  }
}
```

### 1.3 字段缺省约定

| 字段 | 缺省语义 |
|---|---|
| `latin`/`name_zh` | 至少一个存在；纯西方星座无 `name_zh`（空串 `""`）、纯中国无 `latin`（空串 `""`）。前端按 tradition 切换显示，空串触发 `displayNameFor` 兜底逻辑 |
| `label` | `false`（不标）；为 `true` 时该星常驻标注名字 |
| `mansion`/`asterism_id` | 西方为 `null` |
| `stories` | **两个 view（`myth`/`science`）× 三个 narrative（`epic`/`chat`/`brief`）共 6 个 key 必须存在**；每条 `title` 必填（未撰写的可用占位 `"尚未撰写"`），`paragraphs` 可为空数组 `[]` |
| `center.ra` / `center.dec` | 必填；反查逻辑的核心输入 |
| `ra` / `dec` | 每个 star 必填；WCS 投影依赖 |

### 1.4 文件命名规范

> **说明**：`abbr` 只是**内部 slug**（文件名 + 缓存 key + 路由参数），**不要求与 IAU 国际缩写一致**。IAU 是 `Ori`，我们写 `ori`，仅此而已。

| 体系 | 命名规则 | 例 |
|---|---|---|
| 西方 | **优先用 IAU 3 字母缩写小写**；不足 3 字母（如室女座 Virgo 原本 3 个）取一致习惯 | `orion` → `ori.json`、`virgo` → `vir.json`、`canis-major` → `cma.json` |
| 中国 | 拼音或拼音缩写 | `shen` → 参、`xin` → 心、`bi` → 毕 |

### 1.5 删除的旧文件

| 删除 | 原因 |
|---|---|
| `server/data/constellations.json` | 拆成 5 个 `traditions/western/*.json` |
| `server/data/preset_stories.json` | stories 内嵌到各 constellation JSON |
| `server/data/bayer_index.json` | RA/Dec/name/magnitude 已搬入 stars.* 字段 |
| `web/src/data/constellations.json` | 前端不再直接 import 静态资源；走 API |
| `web/src/data/atlas_stories.json` | stories 内嵌到 constellation JSON |

### 1.6 复用 vs 扩展字段

**复用**（用现有字段承载新用途）：
- `stars.*.ra/dec`：既是 atlas 渲染数据、又是 WCS 投影数据、又是反查中心附近星座的输入
- `stars.*.name` / `name_zh`：按 tradition 切换显示

**新增字段**（实在无法复用才扩）：
- `center.{ra, dec}`：WCS 反查中心（不能从 stars 推；手画坐标无意义）。**语义**：真实天球坐标；推荐取“主星质心”或“IAU 边界中心”，需与 stars.*.ra 同坐标轴
- `label: bool`：标注开关（属于渲染行为，无既有字段承载）
- `mansion`/`asterism_id`：中国分类（西方不需要，标可选）

**center soft-check**（validate_atlas.py，warning 不报错）：
- center 到该 constellation 所有 stars 的平均角距 < 15°；超过则 warning（说明 center 偏了，但不拒收；MVP 阶段仅记日志）

---

## 2. 后端层

### 2.1 `server/services/traditions.py`（新增）

```python
"""tradition 数据自动发现 + 加载。

单源：server/data/traditions/{tradition_key}/{abbr}.json
- 一级子目录名 = tradition key
- 文件名 (去 .json) = abbr
- 启动时 lazy-scan，缓存到 _DATA: dict[str, dict[str, dict]]
"""
from pathlib import Path
from threading import Lock
import json
import logging
import math

_DATA_ROOT = Path(__file__).parent.parent / "data" / "traditions"
_DATA: dict[str, dict[str, dict]] = {}
_LOAD_LOCK = Lock()
_LOG = logging.getLogger(__name__)


def _load_all() -> None:
    """启动时由 main.py 显式调用；内部带 lock 防重复、保持 idempotent。

    **fail-soft**：单文件 JSON 坏不拄服务；记录错误后跳过该文件。
    严格 fail-fast 由 `scripts/validate_atlas.py` + CI 负责，不在运行时执行。

    **double-check locking**：无锁快速路径检查 `_DATA`，避免热路径（每个请求）争锁。
    """
    if _DATA:  # 无锁快速路径（绝大多数调用进这里）
        return
    with _LOAD_LOCK:
        if _DATA:  # 拿到锁后再次检查（另一个线程可能已完成）
            return
        for tradition_dir in sorted(_DATA_ROOT.iterdir()):
            if not tradition_dir.is_dir():
                continue
            key = tradition_dir.name
            entries: dict[str, dict] = {}
            for json_file in sorted(tradition_dir.glob("*.json")):
                abbr = json_file.stem
                try:
                    entry = json.loads(json_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    _LOG.error("traditions: %s JSON parse failed: %s", json_file, e)
                    continue
                if entry.get("abbr") != abbr:
                    _LOG.error(
                        "traditions: %s abbr=%r != filename=%r, skipped",
                        json_file, entry.get("abbr"), abbr,
                    )
                    continue
                entries[abbr] = entry
            _DATA[key] = entries


def list_traditions() -> list[dict]:
    _load_all()
    return [
        {"key": k, "label": _label(k), "count": len(v)}
        for k, v in sorted(_DATA.items())
    ]


def list_constellations(tradition: str) -> list[dict]:
    """返回该 tradition 全部星座的轻量 summary。"""
    _load_all()
    return [
        {
            "abbr": c.get("abbr", ""),
            "name": c.get("name", ""),
            "latin": c.get("latin", ""),
            "season": c.get("season", ""),
            "caption": c.get("caption", ""),
            "tradition": tradition,
            "star_count": len(c.get("stars", {})),
            "has_stories": bool(c.get("stories")),
        }
        for c in _DATA.get(tradition, {}).values()
    ]


def get_constellation(tradition: str, abbr: str) -> dict | None:
    _load_all()
    entry = _DATA.get(tradition, {}).get(abbr.lower())
    if entry is None:
        return None
    return {**entry, "tradition": tradition, "ok": True}


def find_nearest(ra: float, dec: float, max_sep_deg: float = 5.0) -> tuple[str, str, float] | None:
    """按 (ra, dec) 反查最近的 constellation。

    Returns:
        (tradition, abbr, separation_deg) 或 None（无命中）。
    """
    _load_all()
    best: tuple[str, str, float] | None = None
    for trad_key, consts in _DATA.items():
        for abbr, c in consts.items():
            center = c.get("center")
            if not center:
                continue
            sep = _angular_separation(ra, dec, center["ra"], center["dec"])
            if best is None or sep < best[2]:
                best = (trad_key, abbr, sep)
    if best and best[2] <= max_sep_deg:
        return best
    return None


def build_star_catalog() -> list[dict]:
    """为 identify.py 的 WCS 投影构造标准星表。

    **去重**：同颗物理星可能在多个 tradition 中出现（参宿四 在 western/ori 和 chinese/shen 中 RA/Dec 相同）。
    以 `(round(ra, 2), round(dec, 2))` 为 key 去重，重复时保留首个出现。

    **去重精度**：`round(..., 2)` 约 0.01° ≈ 36″。两颗独立星角距 < 36″ 会被误合并。
    MVP 5 星座不含密集星团可接受。第二期可改为 `round(..., 3)` ≈ 3.6″ 或加 magnitude 辅助判断；
    进一步可改用 Hipparcos/HIP 号作为去重 key。
    """
    _load_all()
    catalog: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for trad_key, consts in _DATA.items():
        for abbr, c in consts.items():
            for star_key, star in c.get("stars", {}).items():
                ra, dec = star["ra"], star["dec"]
                key = (round(ra, 2), round(dec, 2))
                if key in seen:
                    continue
                seen.add(key)
                catalog.append({
                    "bayer": star.get("bayer", ""),
                    "name": star.get("name", ""),
                    "name_zh": star.get("name_zh", ""),
                    "magnitude": star.get("magnitude", 0),
                    "ra": ra,
                    "dec": dec,
                    "constellation": abbr,
                    "tradition": trad_key,
                })
    return catalog


def _angular_separation(ra1, dec1, ra2, dec2) -> float:
    """简化球面角距（度），处理 RA 环绕。

    处理要点：
    - RA 跨 0°/360° 时取最近一侧：`(dra + 180) % 360 - 180`
    - cos(dec) 中点近似，|dec| < 60° 误差 < 5%

    **TODO**（高赤纬精度问题）：高赤纬（如小熊座 Dec ≈ 85°）时 cos(Dec) → 0，
    RA 微小扰动被过度压缩，欧氏距离近似畸变。第二期加小熊/大熊/仙后等极区星座时
    切换为 3D 向量点积：cos θ = sin δ₁ sin δ₂ + cos δ₁ cos δ₂ cos Δα。
    MVP 5 星座猎户/天蝎/天鹅/狮子/仙女均不在极区，不影响。
    """
    dra = (ra1 - ra2 + 180) % 360 - 180
    dra *= math.cos(math.radians((dec1 + dec2) / 2))
    ddec = dec1 - dec2
    return math.sqrt(dra * dra + ddec * ddec)


def _label(tradition_key: str) -> str:
    return {
        "western": "西方星座",
        "chinese": "中国古代星空",
    }.get(tradition_key, tradition_key)
```

### 2.2 端点

| Method | Path | 返回 |
|---|---|---|
| GET | `/api/traditions` | `[{key, label, count}]` |
| GET | `/api/constellations?tradition=western` | `{tradition, items: [...]}` |
| GET | `/api/constellation/{tradition}/{abbr}` | 完整 entry（含 stars/lines/stories） |

**错误码**：
- `CONSTELLATION_NOT_FOUND` 404（保留现有 envelope）— 星座/tradition 不存在
- `422 Unprocessable Entity` — `/api/constellations` 缺少 `tradition` query 参数（FastAPI `Query(...)` 自动产生）

明确**不提供**无 `tradition` 参数的 `/api/constellations`（不默认 western；明示错误避免误调）。

### 2.3 `routers/identify.py` 改造（删硬编码）

**旧**（写死猎户）：
```python
constellations.append({
    "abbr": "ori",
    "name": "猎户座",
    "latin": "Orion",
    ...
})
```

**新**（按 wcs 中心反查）：
```python
ra = float(wcs_header["CRVAL1"])
dec = float(wcs_header["CRVAL2"])
nearest = traditions.find_nearest(ra, dec)
constellations: list[dict] = []
if nearest is not None:
    trad, abbr, sep_deg = nearest
    entry = traditions.get_constellation(trad, abbr)
    total = len(entry["stars"])
    # ★ 过滤：只统计命中星座（abbr）的投影星，其他星座的可见星不计。
    # projected_stars 来自 build_star_catalog()，含全 tradition 星点。
    visible_stars = sum(
        1 for s in projected_stars
        if s["constellation"] == abbr
        and 0 <= s["pixel_x"] <= display_w
        and 0 <= s["pixel_y"] <= display_h
    )
    constellations.append({
        "tradition": trad,
        "abbr": abbr,
        "name": entry["name"],
        "latin": entry.get("latin", ""),
        "confidence": round(1 - sep_deg / 5.0, 3),
        "visible_stars": visible_stars,         # ★ 改名：命中星座在画面内的星点数
        "total_bright_stars": total,
    })
# 无命中：constellations = []，前端走 empty 分支
```

`project_stars` 数据源改为调用 `traditions.build_star_catalog()`：预构建标准星表 + RA/Dec 去重。MVP 5 星座 ~29 颗星，去重后 ~29 颗；上 88 后 ~1000 颗。O(N) 投影开销可接受。

> **名称语义**：`visible_stars` = “**当前命中星座** 在画面内的投影星点数”（已按 constellation 过滤）；前端展示“命中度”应使 confidence 字段。`total_bright_stars` 为该 constellation JSON `stars.*` 总数（供参考）。

### 2.4 故事端点（不动）

- `/api/story` + `/api/story/stream`：ScanView 路径，仍走真 AI + 缓存
- `preset_stories.json` 删除后，**fallback 逻辑也删**——AI 失败时直接发 `done` event with `degraded:true`（已有行为）

### 2.5 删除的旧端点

| 旧 | 新 |
|---|---|
| `GET /api/constellations`（无 tradition） | `GET /api/constellations?tradition=X` |
| `GET /api/constellation/{abbr}` | `GET /api/constellation/{tradition}/{abbr}` |

---

## 3. 前端层

### 3.1 `web/src/api/atlas.ts`

```typescript
export interface TraditionListItem {
  key: string
  label: string
  count: number
}
export interface TraditionListResponse {
  items: TraditionListItem[]
}

export async function listTraditions(): Promise<TraditionListResponse>
export async function listConstellations(tradition: string): Promise<AtlasListResponse>
export async function getConstellation(tradition: string, abbr: string): Promise<ConstellationAtlas>
```

### 3.2 `web/src/stores/atlas.ts`

```typescript
export const useAtlasStore = defineStore('atlas', () => {
  const traditions = ref<TraditionListItem[]>([])
  const currentTradition = ref<string>('western')

  const itemsByTradition = ref<Record<string, AtlasListItem[]>>({})
  const atlasCache = ref<Record<string, ConstellationAtlas>>({})  // key: `${trad}/${abbr}`

  async function loadTraditions(): Promise<void> {
    if (traditions.value.length > 0) return
    const r = await listTraditions()
    traditions.value = r.items
  }

  async function setTradition(key: string): Promise<void> {
    if (currentTradition.value === key) return
    currentTradition.value = key
    if (!itemsByTradition.value[key]) {
      await list(key)
    }
  }

  async function list(tradition: string): Promise<void> {
    const r = await listConstellationsApi(tradition)
    itemsByTradition.value = { ...itemsByTradition.value, [tradition]: r.items }
  }

  async function getAtlas(tradition: string, abbr: string): Promise<ConstellationAtlas> {
    const cacheKey = `${tradition}/${abbr}`
    if (atlasCache.value[cacheKey]) return atlasCache.value[cacheKey]
    const data = await getConstellationApi(tradition, abbr)
    atlasCache.value = { ...atlasCache.value, [cacheKey]: data }
    return data
  }

  const currentItems = computed<AtlasListItem[]>(
    () => itemsByTradition.value[currentTradition.value] ?? []
  )

  return {
    traditions, currentTradition, itemsByTradition, atlasCache,
    currentItems, loadTraditions, setTradition, list, getAtlas,
  }
})
```

### 3.3 `web/src/views/ScanView.vue` 改造（删静态 import + tradition 透传）

```diff
- import orionData from '../data/constellations.json'
+ const atlasStore = useAtlasStore()
+ const hit = result.constellations[0]
+ const atlas = await atlasStore.getAtlas(hit.tradition, hit.abbr)
+ // tradition 必须透传给 StarCanvas（详见 3.6）
+ <StarCanvas :mode="'scan-atlas'" :constellation-data="atlas" :tradition="hit.tradition" />
```

本地 `AtlasMap` 类型也删除。

### 3.4 `web/src/views/ConstellationView.vue` 顶部加 tradition chips + 空状态

```vue
<template>
  <div class="atlas-page">
    <!-- ★ 新增：tradition 切换 chips -->
    <nav class="tradition-tabs" role="tablist">
      <button
        v-for="t in atlasStore.traditions"
        :key="t.key"
        :class="['trad-tab', {active: t.key === atlasStore.currentTradition}]"
        role="tab"
        :aria-selected="t.key === atlasStore.currentTradition"
        @click="atlasStore.setTradition(t.key)"
      >
        <span class="trad-glyph">{{ t.key === 'western' ? '✦' : '☷' }}</span>
        <span class="trad-label">{{ t.label }}</span>
        <span class="trad-count">{{ t.count }}</span>
      </button>
    </nav>

    <!-- 空状态（MVP chinese/ 为空时出现） -->
    <div v-if="atlasStore.currentItems.length === 0" class="atlas-empty" data-testid="atlas-empty">
      <p class="atlas-empty-glyph">☷</p>
      <h3>该体系暂无星座数据</h3>
      <p>后续版本将逐步加入。</p>
    </div>

    <!-- smedal-row 按当前 tradition 过滤 -->
    <div v-else class="smedal-row">
      <button v-for="item in atlasStore.currentItems" :key="item.abbr" class="smedal">...</button>
    </div>

    <AtlasStoryStatic :tradition="atlasStore.currentTradition" :abbr="selected.abbr" />
  </div>
</template>
```

**视觉**：chip 沿用 concept 的 `.seg`/`.vtab` design token。空状态采用 plate 包裹，与首页 placeholder 一致。

### 3.5 `web/src/components/AtlasStoryStatic.vue` 改造

```diff
- import atlasStories from '../data/atlas_stories.json'
+ const props = defineProps<{ tradition: string; abbr: string }>()
+ const atlasStore = useAtlasStore()
+ const constellation = computed(() =>
+   atlasStore.atlasCache[`${props.tradition}/${props.abbr}`]
+ )
+
+ const currentStory = computed(() => {
+   const stories = constellation.value?.stories
+   if (!stories) return null
+   const viewEntry = stories[selectedView.value]
+   if (!viewEntry) return null
+   return viewEntry[selectedNarrative.value] ?? Object.values(viewEntry)[0] ?? null
+ })
```

接受 `tradition` prop，按 tradition 决定星点名字显示（西方 `star.name` / 中国 `star.name_zh`）。

**空状态处理**：
- `stories` 缺位 → 显示“该星座暂无预存文稿”（不白屏）
- `viewEntry` 缺位 → fallback 到该 view 下任意一个 narrative
- 段落为空数组 → 显示“（该维度暂无内容）”，不报错

### 3.6 `web/src/components/StarCanvas.vue` 加标注

```vue
<g class="labels">
  <text
    v-for="s in labeledStars"
    :key="s.id"
    :x="s.x + offset"
    :y="s.y - offset"
    :class="['star-label', {chinese: tradition === 'chinese'}]"
    :font-size="fontSize(s.magnitude)"
  >
    {{ displayNameFor(s, tradition) }}
  </text>
</g>
```

```typescript
function displayNameFor(star, tradition) {
  // 兜底链：
  //   - chinese tradition：优先 name_zh（可能被数据填为 ""），空则 name，再空则 '未命名'
  //   - western tradition：优先 name，空则 name_zh，再空则 '未命名'
  // 用 `||` 而非 `??` 因为空字符串 `""` 在 `??` 下不触发 fallback，会出现空白标注。
  // 额外判断 `.trim()` 防数据填了 `" "`（空格）这种伪非空。
  if (tradition === 'chinese') {
    const zh = (star.name_zh ?? '').trim()
    return zh || (star.name ?? '').trim() || '未命名'
  }
  const en = (star.name ?? '').trim()
  return en || (star.name_zh ?? '').trim() || '未命名'
}
function fontSize(mag) {
  return 8 + Math.max(0, (4 - mag)) * 1.5
}
const labeledStars = computed(() =>
  Object.entries(props.constellationData.stars)
    .filter(([_, s]) => s.label)
    .map(([id, s]) => ({id, ...s}))
)
```

> **ScanView → StarCanvas tradition 链路**：ScanView 拿到 `result.constellations[0]` 后，`tradition` 字段必须一并传入 StarCanvas（见 3.3）。以防识别出非西方星座时出现名子显示混乱。

**视觉**：
- 字号随亮度自适应（亮星字号大）
- 颜色：西方 `var(--ink)`、中国 `var(--seal)`（赭红色调区分体系）
- 位置：星点右上方 8px 偏移
- hover：circle 半径 `r → r×1.4` + 文字下划线

**MVP label 配置**（每个 JSON 加 `label: true` 的星）：

| 星座 | 标注星 |
|---|---|
| orion | betelgeuse, bellatrix, alnilam, mintaka, alnitak, rigel |
| sco | antares, shaula, dschubba |
| cyg | deneb, albireo, sadr |
| leo | regulus, denebola |
| and | alpheratz, mirach |

### 3.7 类型扩展 `web/src/types.ts`

```typescript
export interface TraditionListItem {
  key: string
  label: string
  count: number
}
export interface TraditionListResponse { items: TraditionListItem[] }

export interface AtlasListItem {
  abbr: string
  name: string
  latin: string
  glyph?: string
  hemisphere?: Hemisphere
  bestMonth?: number
  season?: string
  caption?: string
  magnitude?: number
  bright_stars?: number
  storyStyles?: string[]
  tradition?: string         // ★ 新增
  star_count?: number        // ★ 新增（来自 list 端点）
  has_stories?: boolean      // ★ 新增（来自 list 端点）
}

export interface AtlasListResponse {
  tradition?: string         // ★ 新增
  items: AtlasListItem[]
}

// ConstellationAtlas 新增：
//   tradition: string
//   center: { ra: number; dec: number }
//   mansion?: string | null
//   asterism_id?: string | null
//   stories?: ConstellationStories
```

### 3.8 删除的文件

- `web/src/data/constellations.json`
- `web/src/data/atlas_stories.json`
- 整个 `web/src/data/` 目录

---

## 4. 测试策略

### 4.1 后端

```python
# tests/test_traditions.py（新增）
- test_scan_loads_western_and_chinese          # 自动发现
- test_load_skips_bad_json_does_not_crash    # fail-soft（坏 JSON 不拄服务）
- test_load_skips_abbr_mismatch               # fail-soft（abbr != filename 跳过）
- test_get_constellation_returns_full_entry    # 含 stars/lines/stories/center
- test_list_constellations_filters_by_tradition
- test_list_includes_star_count_and_has_stories
- test_find_nearest_returns_closest            # 反查
- test_find_nearest_respects_max_separation   # 5° 阈值
- test_find_nearest_handles_ra_wrap           # ★ RA 跨 0°/360°（359° vs 1°）；用 mock fixture 构造跨零度数据（不依赖 MVP 实际数据）

# tests/test_build_star_catalog.py（新增）
- test_dedupes_stars_by_ra_dec                # 同 RA/Dec 多 tradition 合并
- test_returns_all_required_fields            # bayer/name/magnitude/ra/dec/constellation

# tests/test_constellations_router.py（新增或合并）
- test_traditions_endpoint
- test_constellations_endpoint_with_query
- test_constellation_detail_404

# tests/test_identify.py（改写）
- 删：hit_stars = 8 时假定 ori
- 加：wcs 中心 (86, -2) → 命中 ori，返回 visible_stars 与 tradition
- 加：wcs 中心 (300, -60) → 不命中任何
- 加：识别返回 tradition 字段
```

### 4.2 前端

```typescript
// tests/atlas.store.tradition.test.ts（新增）
- store.setTradition 切换后 currentItems 重渲染
- getAtlas('western', 'ori') 缓存命中不调 API

// tests/atlas.api.test.ts（新增）
- listTraditions / listConstellations / getConstellation 三端点

// tests/AtlasStoryStatic.test.ts（已有，改写）
- mock store 提供 constellation.stories（不再 import JSON）
- 测试传 :tradition + :abbr 两个 prop

// tests/ConstellationView.test.ts（改）
- 已有 .smedal 测试加 tradition chip 测试

// tests/StarCanvas.label.test.ts（新增）
- label: true 的星画了 <text>
- hover 时 <circle> 半径变大
- tradition='chinese' 时显示 name_zh
```

### 4.3 数据校验脚本

```python
# server/scripts/validate_atlas.py（**第一阶段末尾跑一次**，第二期起集成 CI）
- 遍历 traditions/*/*.json
- 校验硬性：abbr == 文件名、center.ra/dec 存在、stars 有 ra/dec、magnitude 数值、label 是 bool
- 校验硬性：lines 两端都是有效 star key
- 校验软性：center 到该 constellation stars 的平均角距 < 15°（warning 不报错）
- 校验硬性：stories 6 个 key 都存在（myth/science × epic/chat/brief），且每条 `title` 必填（未撰写的可用占位 `"尚未撰写"`），`paragraphs` 可为空数组
- 输出报告，缺哪条信息列出；MVP 第一阶段末尾手动跑一次，保证 5 文件完整可走
```

---

## 5. 实施分阶段

### 第一阶段（MVP，本次单次）

1. 删 `server/data/constellations.json`、`preset_stories.json`、`bayer_index.json`
2. 创建 `server/data/traditions/western/{ori,sco,cyg,leo,and}.json`（5 文件含 ra/dec + center + label）
3. 创建 `server/data/traditions/chinese/`（空目录 + `.gitkeep`）
4. `services/traditions.py` 实现（含 build_star_catalog + RA 环绕 + fail-soft）+ 2 端点
5. `main.py` startup event 调用 `_load_all()`；不使用 lazy-load
6. `routers/identify.py` 反查重写：hit_stars → visible_stars；catalog 用 build_star_catalog
7. `web/src/api/atlas.ts` + `stores/atlas.ts` + `types.ts` 改造
8. `views/ConstellationView.vue` 加 chips + 空状态
9. `views/ScanView.vue` 删静态 import + tradition 透传给 StarCanvas
10. `components/AtlasStoryStatic.vue` 改读 constellation.stories + 空状态
11. `components/StarCanvas.vue` 加 labels 组 + name 鬼底
12. 删 `web/src/data/` 整个目录
13. `scripts/validate_atlas.py` 实现 + 末尾手动跑一次
14. 测试全部更新（含 RA 跨零度 case）
15. 后端 pytest 全绿 + 前端 vitest 全绿 + vue-tsc 0 错误

**MVP 故事数据量控制**：5 星座每个**先只写 2 套**（`brief` + `chat`），`epic` 维度留空数组 `[]`，前端走“该维度暂无内容”fallback。补齐 6 套到第二期。第三期才做中国故事。

**完工标志**：5 星座西方视角与之前 100% 一致；tradition 切换 UI 能切到空的中文目录。

### 第二期（后续）

- `scripts/validate_atlas.py` 集成 CI
- 批量加 83 个西方 JSON（每个 5-30 颗星 + 连线 + 6 套 stories 补齐）
- AI 辅助生成 → 用户审校

### 第三期（后续）

- 补中国 28 宿 + 三垣 JSON
- 中国古星名标注（name_zh）
- 中国独有视觉（二十八宿分布图、三垣图等）

---

## 6. 验收标准

| 项 | 标准 |
|---|---|
| 后端 pytest | 全绿（新增 ~7 用例，含 RA 跨零度） |
| 前端 vitest | 全绿（新增 ~8 用例 + 改 ~3 用例） |
| vue-tsc | 0 error |
| Atlas UI | 切换 chips 工作；中文空时显示空状态 |
| Scan UI | 识别后展示真实命中的 atlas（含标注），不是写死猎户 |
| 数据加载 | 添加新 JSON 重启后自动可见（fail-soft 不拄服务） |
| validate_atlas | 第一阶段末尾跑过，5 文件全绿 |
| 旧文件 | `web/src/data/`、`bayer_index.json`、`preset_stories.json` 全删 |
| live 验证 | test1.jpg / test2.jpg / test3.jpg 实测识别仍成功 |

---

## 7. 风险与边界

| 风险 | 缓解 |
|---|---|
| 5 星座 JSON 拆开后行为漂移 | 端到端 E2E test（test_e2e_real_samples.py）覆盖 |
| WCS 反查误命中（小图覆盖远区）| `max_sep_deg=5.0` 阈值 + confidence 字段告知前端 |
| RA 跨零度计算错误 | `_angular_separation` 处理环绕；test_traditions 中加 case |
| 多 tradition 同星重复投影 | `build_star_catalog` 按 (RA, Dec) 去重 |
| `visible_stars` 统计偏高（含其他星座的可见星）| identify 按 `s["constellation"] == abbr` 过滤后再统计 |
| `displayNameFor` 空字符串失效（`??` 不 fallback）| 用 `\|\|` + `.trim()` 鬼底；test_starCanvas 补 `name: ""` + `name_zh: ""` case |
| `name_zh: " "`（空格）伪非空 | `displayNameFor` `.trim()` 后判断 |
| 88 星座数据量过大 | MVP 只做 5 个；批量第二期分批引入 |
| StarCanvas 改造影响现有 scan-atlas 模式 | 加 props `tradition` 默认 'western'，向后兼容 |
| `tests/StarCanvas.animate.test.ts` 内联 orion 数据 | 测试 fixture 保留；改字段后断言需更新 |
| 坏 JSON 不应拄服务 | runtime fail-soft 跳过该文件 + logger.error；严格检查交给 validate_atlas |
| 高赤纬角距失真（\|dec\| > 60°）| MVP 5 星座均不在极区；`_angular_separation` 加 TODO；第二期切 3D 点积 |
| MVP `epic` 维度只有空数组 | frontend AtlasStoryStatic 走“该维度暂无内容”fallback；validate 允许 title 占位 `"尚未撰写"` |
| `build_star_catalog` 去重粒度风险（0.01° ≈ 36″）| MVP 可接受；代码注释加“第二期改 0.001 或加 magnitude” |

---

## 8. 不在本次范围 / 后续优化

- 第二期、第三期数据补齐
- 中国独有视觉（二十八宿分布图等）
- RA/Dec 真投影渲染（仅入库不渲染）
- 真实星等自适应渲染（当前用 magnitude 算 size，已存在）
- WCS 严格角距公式（Haversine，MVP 简化版够用）
- `find_nearest` 返回多个候选（第二期可能返回 list）
- `GET /api/constellation` 加 `include_stories=false` 查询参数（payload 优化）
- `tradition/_meta.json` 取代硬编码 `_label`（多体系时）