# Atlas 后端精度 + API 优化 + RA/Dec 真投影（v4）

> **目的**：在 spec v3 MVP 基础上，推进 spec v3 第 8 节"不在本次范围"中工程类的 5 项：Haversine 严格角距（项 5）+ find_nearest 多候选（项 6）+ `/api/constellation?include_stories=`（项 7）+ `traditions/{key}/_meta.json`（项 8）+ StarCanvas `mode="real-projection"`（项 3 C 方案）。
> 业务类（项 1+2 数据补齐）单独 spec v5 暂存，等业务定义到位再开。

**日期**：2026-08-25
**状态**：v4 — 设计稿（待用户审查）
**前置**：spec v3 (`docs/specs/2026-08-25-atlas-tradition-design.md`) MVP 已 14/14 完成
**范围**：数据模型 / 后端 services+routers / 前端 StarCanvas / 前端 ScanView 集成 / 测试 / 验收

## 修订记录

- v4: 新增 `_meta.json` 数据模型 + Haversine 替换 + find_nearest 改返回 list + `?include_stories=` query + `mode="real-projection"` C 方案分工；业务包（项 1+2）单独 spec v5 暂存
- v4 评审修正: 2.1 真正 Haversine 公式（atan2 版）；1.2 _meta 坏 JSON 仅降级不跳过；1.1 star_count 以 glob 为准；3.2 tradition_meta 字段白名单；4.2+4.3 抽 normalizeRaDiff；4.3 屏幕物理坐标注释；4.2 computeField clamp + cos(Dec) TODO；4.4 gridStep 函数；2.2 docstring 明确 top_k=3；3.3 stories 标 Story[] | null；validate_atlas 加严 key/coordinate_system 校验；测试数量统一 121/72
- v4 二审修正: 测试 #8 改名 test_meta_corrupt_json_falls_back_meta；测试 #2 措辞去 cos θ；1.2 加载顺序去“跳过”歧义 + glob_count 时机；3.2 tradition_meta 不含 key 约定；4.2 computeField clamp 裁剪 warn TODO；5.2 watch onUnmounted 卸载防护；2.1 高纬区分别（角距仍准 vs 投影失真）；3.1 chinese label 示例加注

---

## 1. 数据模型扩展（项 8）

### 1.1 `traditions/{key}/_meta.json` schema

每个 tradition 目录下新增 `_meta.json`，取代当前硬编码 `_label`：

```json
{
  "key": "western",
  "label": "西方星座",
  "label_en": "Western Constellations",
  "description": "以古希腊罗马神话为基础的 88 个星座体系",
  "epoch": "BCE 2nd century",
  "source": "IAU 1922 标准",
  "license": "Public Domain",
  "star_count": 5,
  "coordinate_system": "equatorial"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `key` | ✓ | tradition 名（与目录名一致，全小写） |
| `label` | ✓ | 中文显示名 |
| `label_en` | × | 英文显示名（可选） |
| `description` | × | 一句话描述 |
| `epoch` | × | 起源年代 |
| `source` | × | 数据来源标注 |
| `license` | × | 版权（Public Domain / CC-BY-SA / ...） |
| `star_count` | ✓ | 服务启动时校验：`star_count == len(glob("*.json")) - 1`（排除自身） |
| `coordinate_system` | ✓ | `"equatorial"`（RA/Dec）或 `"mansion"`（宿度，待中国 tradition 用） |

### 1.2 加载行为（fail-soft）

- `services.traditions._load_all()` 加载顺序：
  1. 读 `_meta.json`：缺失 → 降级默认值 + warn；坏 JSON → 降级默认值 + error；**星表始终尝试加载**（不受 meta 状态影响）
  2. 扫描 `traditions/{key}/*.json`（不含 `_meta.json`）—— 在读 meta **之前或同时** 计算 `glob_count`，避免 count 为 0
  3. 合并到 `_DATA[key]` 和 `_META[key]`
- 缺失 `_meta.json` 时**降级默认值**：
  ```python
  {"key": key, "label": key, "star_count": glob_count, "coordinate_system": "equatorial"}
  ```
  不让坏数据挂服务，但 logger.warning 记录。
- **加载期降级**：默认值在加载阶段填入 `_META` dict；路由层透传，无须在路由函数补默认。
- `_meta.json` **坏 JSON 时仅降级 meta**，**仍加载星表 `*.json`**（星表可独立使用；跳过整个 tradition 会导致该体系完全不可用，损失较大）：
  ```python
  try:
      meta = json.loads(meta_path.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError) as e:
      logger.error("tradition %s _meta.json corrupt: %s, using defaults", key, e)
      meta = default_meta(key, glob_count)
  ```
- `star_count` 以**实际 `glob` 数量为准**，覆盖 meta 里的 `star_count` 并 `logger.warning`（避免 meta 与数据不一致）。

### 1.3 端点契约变化（先埋钩子，第 3 节实现）

- `GET /api/traditions` → 直接读 `_META`，不再用任何硬编码 `_label` 常量
- `GET /api/constellations?tradition=X` → 响应补 `tradition_meta: {label, description, epoch, ...}` 字段

---

## 2. 后端 services.traditions.py

### 2.1 Haversine 严格角距公式（项 5）

**直接替换** `_angular_separation` 实现，无须保留简化版（spec v3 TODO 撤销）。

```python
def _angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """严格 Haversine 球面角距，返回度数。
    
    公式：
      a = sin²(Δδ/2) + cos δ₁ · cos δ₂ · sin²(Δα/2)
      θ = 2 · atan2(√a, √(1−a))
    
    选用 Haversine 而非 acos 版球面余弦的原因：
    - 极小角距 (<0.001°) 时，acos 公式会出现 cos θ ≈ 1 的浮点取消
    - Haversine 通过 half-angle 计算保持数值稳定
    
    MVP 精度（与简化版对比）：
    - |Dec| < 45°：偏差 < 0.001°（5 星座均满足）
    - |Dec| > 70°：**角距计算仍准**；**投影失真** 在 4.3 equirectangular TODO 中处理（第二期改 Stereographic）
    """
    ra1_r = math.radians(ra1)
    dec1_r = math.radians(dec1)
    ra2_r = math.radians(ra2)
    dec2_r = math.radians(dec2)
    ddec_r = dec2_r - dec1_r
    dra_r = ra2_r - ra1_r
    a = (
        math.sin(ddec_r / 2) ** 2
        + math.cos(dec1_r) * math.cos(dec2_r) * math.sin(dra_r / 2) ** 2
    )
    a = min(1.0, max(0.0, a))  # 数值保护（避免 sqrt(负数)）
    return math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
```

**变更影响**：函数签名不变，所有调用方零改动；移除原 `_angular_separation` 的"高赤纬 TODO"注释。

### 2.2 `find_nearest` 返回多候选（项 6，**破坏性 API 变化**）

```python
def find_nearest(
    ra: float,
    dec: float,
    max_sep_deg: float = 5.0,
    top_k: int | None = None,
) -> list[tuple[str, str, float]]:
    """按 (ra, dec) 反查所有 ≤ max_sep_deg 的候选，按角距升序。
    
    Args:
        ra, dec: 中心坐标（度）
        max_sep_deg: 最大接受角距
        top_k: 最多返回候选数；None = 全部（不截断）。
            **生产路径固定 `top_k=3`**（routers/identify.py 约定），避免不截断带来的性能回退。
    
    Returns:
        [(tradition, abbr, sep_deg), ...] — 空 list = 无命中
    """
    _load_all()
    results = []
    for trad_key, entries in _DATA.items():
        for abbr, entry in entries.items():
            ra2 = entry["center"]["ra"]
            dec2 = entry["center"]["dec"]
            sep = _angular_separation(ra, dec, ra2, dec2)
            if sep <= max_sep_deg:
                results.append((trad_key, abbr, sep))
    results.sort(key=lambda x: x[2])
    if top_k is not None:
        results = results[:top_k]
    return results
```

**破坏性变化**：
- 旧：`find_nearest(ra, dec) → tuple[str, str, float] | None`
- 新：`find_nearest(ra, dec) → list[tuple[str, str, float]]`

**调用方更新清单**（**1 处**：routers/identify.py）：

```python
# 旧
trad, abbr, sep = find_nearest(ra, dec) or (None, None, None)

# 新
hits = find_nearest(ra, dec, max_sep_deg=5.0, top_k=3)
if not hits:
    return SolveResponse(constellations=[], ...)
nearest = hits[0]
trad, abbr, sep = nearest
# 后续：visible_stars 按 constellation==abbr 过滤（如 spec v3 1.3）
```

**测试更新清单**（**5 处**：test_traditions.py 5 项断言）：
- `find_nearest(ra, dec) → tuple` 改为 `find_nearest(ra, dec) → list[0] == tuple`
- `assert find_nearest(...) is not None` 改为 `assert len(find_nearest(...)) >= 1`

### 2.3 `_load_all` 加载 _meta（项 8 配套）

```python
_DATA: dict[str, dict[str, dict]] | None = None
_CATALOG: list[dict] | None = None
_META: dict[str, dict] | None = None
_LOCK = threading.Lock()

def _load_all() -> None:
    """显式调用 + idempotent。double-check locking。
    
    加载顺序（每个 tradition）：
    1. 读 _meta.json（缺则降级默认值 + warn；坏 JSON 也降级 + error，但星表照常加载）
    2. 读 *.json（除 _meta 外）
    3. 校验 star_count（以 glob 为准），不匹配覆盖 meta + warn
    4. 三个全局变量 _DATA / _META / _CATALOG 一起原子赋值（避免半初始化）
    """
    global _DATA, _CATALOG, _META
    if _DATA is not None and _META is not None:
        return  # 缓存命中
    with _LOCK:
        if _DATA is not None and _META is not None:
            return
        # ... 实现（详见 2.3.1 ~ 2.3.4）
```

新增公开 API：

```python
def get_meta(tradition: str) -> dict | None:
    """返回 _meta.json dict（lowercase tradition key）。"""
    _load_all()
    return _META.get(tradition.lower()) if _META else None
```

### 2.4 不保留向后兼容

按 spec v3 一致性原则：
- `_angular_separation` 内部用 Haversine 替换（无外部 API 变化）
- `find_nearest` 返回类型变（**1 处调用方 + 5 处测试更新**）
- 新增 `get_meta()`

---

## 3. 后端 API 改动

### 3.1 `GET /api/traditions` 用 `_meta.json`（项 8）

**响应保持 list 形式**（前端类型稳定），每项扩展可选字段：

```json
[
  {
    "key": "western",
    "label": "西方星座",
    "label_en": "Western Constellations",
    "description": "以古希腊罗马神话为基础的 88 个星座体系",
    "epoch": "BCE 2nd century",
    "source": "IAU 1922 标准",
    "license": "Public Domain",
    "coordinate_system": "equatorial",
    "count": 5
  },
  {
    "key": "chinese",
    "label": "中国古代星空",
    "coordinate_system": "mansion",
    "count": 0
  }
]

> **注**：示例 chinese 项展示了**有完整 `_meta.json` 时的形态**。MVP 阶段 `chinese/` 仅有 `.gitkeep`，未提供 `_meta.json`，实际会走 1.2 节降级默认值（`label == "chinese"`，无 description）。补上 `_meta.json` 后才会出现上例的 label。
```

| 字段 | 来源 | 说明 |
|---|---|---|
| `key` | `_meta.key` | tradition 目录名 |
| `label` | `_meta.label` | 中文显示名（**取代硬编码**） |
| `label_en` | `_meta.label_en` | 英文显示名（可选） |
| `description` | `_meta.description` | 一句话描述（可选） |
| `epoch` | `_meta.epoch` | 起源年代（可选） |
| `source` | `_meta.source` | 数据来源（可选） |
| `license` | `_meta.license` | 版权（可选） |
| `coordinate_system` | `_meta.coordinate_system` | `"equatorial"` 或 `"mansion"` |
| `count` | `len(_DATA[key])` | 星座数（实时计算，不从 _meta 读） |

**实现**：`routers/traditions.py` 改为遍历 `_META.items()`，缺字段用 `entry.get('field')` 省略（**不补默认值**——只在 _meta 缺失时整个 tradition 降级）。

### 3.2 `GET /api/constellations?tradition=X` 增 `tradition_meta`（项 8 配套）

**响应增加 `tradition_meta` 字段**（前端 ConstellationView 头部可显示 description）：

```json
{
  "tradition": "western",
  "tradition_meta": {
    "label": "西方星座",
    "description": "...",
    "coordinate_system": "equatorial"
  },
  "items": [{...}, ...]
}
```

`tradition_meta` 是 `/api/traditions` 响应中对应 tradition 的**字段白名单子集**（去掉 `count` / `key`）：

| 白名单字段 | 必填 | 说明 |
|---|---|---|
| `label` | ✓ | 中文显示名（加载期降级或缺失 → 取 `_META[key]['label']`） |
| `label_en` | × | 可选，未填省略 |
| `description` | × | 可选，未填省略 |
| `epoch` | × | 可选，未填省略 |
| `source` | × | 可选，未填省略 |
| `license` | × | 可选，未填省略 |
| `coordinate_system` | ✓ | 从 `_META` 透传 |

实现：`{k: meta[k] for k in WHITELIST if k in meta}`。**不含 `count` / `key`**。

**约定**：`tradition` key 仅出现在响应顶层（如 `{"tradition": "western", "tradition_meta": {...}}`），`tradition_meta` 内部不放 `key` 以避免重复；前端如需体系名 key 直接读顶层 `tradition`。

### 3.3 `GET /api/constellation/{trad}/{abbr}?include_stories=`（项 7）

**Query 参数**：
- `include_stories: bool = True`（默认 True，向后兼容）
- `false` 时：`stories` 字段为 `null`（**不删除字段，保持 schema 稳定**）
- 前端类型：`stories: StoryBlock | null`（避免 TS 严格模式报错）

```python
@router.get("/constellation/{tradition}/{abbr}")
async def get_constellation_endpoint(
    tradition: str,
    abbr: str,
    include_stories: bool = Query(True, description="是否包含 stories 字段"),
):
    entry = get_constellation(tradition, abbr)
    if entry is None:
        raise HTTPException(404, detail={
            "code": "CONSTELLATION_NOT_FOUND",
            "tradition": tradition, "abbr": abbr,
        })
    result = {**entry, "ok": True}
    if not include_stories:
        result["stories"] = None
    return result
```

**前端行为**：
- `atlas.getConstellation(trad, abbr)` 默认 `include_stories=true`
- ConstellationView 默认完整加载
- 暂不调用 `false`（payload 优化钩子就位，留给第二期减少 bundle）

### 3.4 `GET /api/identify/solve` 适配 `find_nearest` 列表（项 6 配套）

详见节 2.2 调用方更新。`constellations[]` 响应结构不变（仍取首个命中），内部支持多候选（`find_nearest(..., top_k=3)` 已就位）。

**第二期暴露**：响应可加 `candidates: [{trad, abbr, sep}]` 字段，前端做"匹配度排序"chip。

### 3.5 端点测试覆盖

| 测试文件 | 测试名 | 断言 |
|---|---|---|
| test_constellations_router.py | `test_traditions_uses_meta` | 含 description / coordinate_system |
| test_constellations_router.py | `test_traditions_missing_meta_falls_back` | 缺 _meta.json → label == key |
| test_constellations_router.py | `test_constellations_includes_tradition_meta` | `tradition_meta.label == "西方星座"` |
| test_constellations_router.py | `test_constellation_include_stories_default` | 默认 stories 不为 null |
| test_constellations_router.py | `test_constellation_include_stories_false` | stories 为 null |
| test_identify.py | `test_identify_solve_uses_nearest_list` | mock WCS 命中 ori，constellations[0].abbr == 'ori' |

---

## 4. 前端 StarCanvas `mode="real-projection"`

### 4.1 mode 矩阵（C 方案落地）

| mode | 用途 | 数据源 | 投影方式 | 使用入口 |
|---|---|---|---|---|
| `overlay` | ScanView 识别叠层 | `starsOverlay` | WCS `world_to_pixel` | ScanView 自动 |
| `scan-atlas` | 美术坐标静态图鉴 | `constellationData` + `viewBox` | 线性 viewBox | ConstellationView 全局；ScanView "美术模式" |
| `real-projection` | 赤道坐标真实星图 | `constellationData` + `center` + `stars.ra/dec` | equirectangular | ScanView "真实模式"（**新增**） |

### 4.2 视场尺寸自动计算（无须 JSON 改动）

```typescript
/**
 * 赤经差归一化（处理 RA 跨 0/360° 边界）。
 * 返回 [-180, 180] 范围的有符号差值。
 */
function normalizeRaDiff(ra: number, centerRa: number): number {
  let dra = ra - centerRa
  if (dra > 180) dra -= 360
  else if (dra < -180) dra += 360
  return dra
}

/**
 * 自动计算视场尺寸（度）。
 * 返回 {width, height} 含 padding，clamp 在 [10×8, 120×90]。
 *
 * TODO：高赤纬 cos(Dec) 缩放 ── 等角矩形投影下，赤经跨度对真实物理角度的贡献受 cos(Dec) 影响。
 * 5 星座均 |Dec| < 45°，MVP 够用；第二期加 cos(centerDec) 修正。
 *
 * TODO：若 maxDra * PAD > 120 或 maxDdec * PAD > 90（被 clamp 裁掉），输出 warn 提示“星座星过散，视场被裁剪”。
 */
function computeField(
  stars: Record<string, AtlasStar>,
  center: { ra: number; dec: number },
): { width: number; height: number } {
  const vals = Object.values(stars)
  if (vals.length === 0) return { width: 30, height: 20 }  // fallback
  let maxDra = 0, maxDdec = 0
  for (const s of vals) {
    const dra = Math.abs(normalizeRaDiff(s.ra ?? 0, center.ra))
    const ddec = Math.abs((s.dec ?? 0) - center.dec)
    if (dra > maxDra) maxDra = dra
    if (ddec > maxDdec) maxDdec = ddec
  }
  const PAD = 1.5
  const rawW = 2 * maxDra * PAD
  const rawH = 2 * maxDdec * PAD
  if (rawW > 120 || rawH > 90) {
    console.warn(`computeField: 星座星过散，视场被裁剪 (raw=${rawW.toFixed(1)}×${rawH.toFixed(1)}°)`)
  }
  return {
    width: Math.min(Math.max(rawW, 10), 120),   // [10°, 120°]
    height: Math.min(Math.max(rawH, 8), 90),    // [8°, 90°]
  }
}
```

**MVP 范围**：5 星座 JSON 已含 `center.{ra, dec}` + `stars.{ra, dec}`（spec v3 已加入），无数据迁移。

### 4.3 equirectangular 投影函数

```typescript
function worldToPixelEquirect(
  ra: number, dec: number,
  center: { ra: number; dec: number },
  field: { width: number; height: number },
  viewbox: { width: number; height: number },
): { x: number; y: number } {
  // RA wrap（跨 0/360° 边界）
  const dra = normalizeRaDiff(ra, center.ra)
  // 本项目约定：采用屏幕物理坐标——RA 增大向右（东为正），
  // 与天文学标准星图（RA 增大向左）不同；避免后续维护混淆。
  const x = (dra + field.width / 2) / field.width * viewbox.width
  // y: 北为正（向上），canvas Y 轴翻转
  const y = (center.dec - dec + field.height / 2) / field.height * viewbox.height
  return { x, y }
}
```

**MVP 精度声明**：equirectangular 在 |Dec| < 60° 失真 < 2%；5 星座均 |Dec| < 45° 满足。
**TODO 注释**：高纬失真、第二期改 Stereographic / Hammer-Aitoff。

### 4.4 `drawRealProjection` 渲染分支

与 `drawScanAtlas` 平行，渲染要素：

| 要素 | 渲染 |
|---|---|
| 网格 | 赤经圈（垂直线，步长接近 5° 的整数倍）+ 赤纬圈（水平线，步长接近 5° 的整数倍） |
| 中心十字 | 中心点十字（`+` 形状，10×10 px，gold） |
| 主星 | 金圈 + 光晕（同 scan-atlas） |
| 连线 | 金色实线（同 scan-atlas） |
| 标注 | `displayNameFor(star, trad)`（spec v3 规则） |
| 视场边框 | 1px 实线 + 半透明黑底 |

**网格步长算法**（保证视场大小不一都美观）：

```typescript
function gridStep(fieldExtent: number): number {
  // 目标 6 条线，每条尽量接近 5° 整数倍，但不少于 5°
  const ideal = fieldExtent / 6
  const rounded = Math.max(5, Math.round(ideal / 5) * 5)
  return rounded
}
const stepRa = gridStep(field.width)
const stepDec = gridStep(field.height)
```

### 4.5 type 扩展

```typescript
// types.ts
export type StarCanvasMode = 'overlay' | 'scan-atlas' | 'real-projection'  // +1

// ConstellationAtlas 增可选字段（schema 已兼容，无须改 JSON）
export interface ConstellationAtlas {
  // ... 已有 ...
  center?: { ra: number; dec: number }
  viewBox?: { width: number; height: number }
  stars: Record<string, AtlasStar>
}

export interface AtlasStar {
  // ... 已有 ...
  ra?: number
  dec?: number
  label?: boolean
}
```

---

## 5. 前端集成

### 5.1 ScanView 模式矩阵（3 chip UI）

当前 ScanView 的 `showAtlas: boolean`（2 态）改为双 ref：

```typescript
type OverlayMode = 'overlay' | 'atlas'
type AtlasMode = 'scan-atlas' | 'real-projection'

const overlayMode = ref<OverlayMode>('atlas')          // done 状态默认 atlas
const atlasMode = ref<AtlasMode>('scan-atlas')         // 默认美术
```

**UI（3 chip 组）**：

```vue
<div class="view-toggle" v-if="scan.status === 'done'">
  <span class="toggle-label">视图：</span>
  <StarChip
    label="照片叠层"
    :active="overlayMode === 'overlay'"
    @click="overlayMode = 'overlay'"
  />
  <StarChip
    label="美术连线"
    :active="overlayMode === 'atlas' && atlasMode === 'scan-atlas'"
    @click="() => { overlayMode = 'atlas'; atlasMode = 'scan-atlas' }"
  />
  <StarChip
    label="真实投影"
    :active="overlayMode === 'atlas' && atlasMode === 'real-projection'"
    @click="() => { overlayMode = 'atlas'; atlasMode = 'real-projection' }"
  />
</div>
```

**`<StarCanvas>` 渲染分支**：

```vue
<StarCanvas
  v-if="overlayMode === 'overlay'"
  class="overlay"
  mode="overlay"
  :stars-overlay="scan.result?.stars_overlay"
  :overlay-lines="scan.result?.overlay_lines"
  :image-width="scan.result?.image_width"
  :image-height="scan.result?.image_height"
  :active-abbr="scan.activeAbbr"
/>
<StarCanvas
  v-else
  class="overlay atlas"
  :mode="atlasMode"
  :constellation-data="atlasData"
  :active-abbr="scan.activeAbbr"
  :tradition="atlasTradition"
/>
```

### 5.2 atlasStore 缓存键（无须扩展）

`atlasCache` 已用 `${tradition}/${abbr}` 作 key（spec v3 第 3.5 节），**无须扩展**。

新增主动加载 effect（ScanView.vue）：

```typescript
import { onUnmounted } from 'vue'

let isMounted = true
onUnmounted(() => { isMounted = false })

watch(
  () => scan.result?.constellations?.[0]?.abbr,
  async (newAbbr) => {
    const hit = scan.result?.constellations?.[0]
    if (!hit || !newAbbr) return
    // 🔧 判空守卫：constellations 为空数组时进入 empty 分支，不加载 atlas
    const trad = hit.tradition ?? 'western'
    await atlasStore.getAtlas(trad, newAbbr)
    if (!isMounted) return  // 卸载后写入保护
  },
  { immediate: true },
)
```

**判空逻辑**：`constellations = []`（无命中）时，ConstellationView/ScanView 走"未识别到星座"empty 分支，不调用 `getAtlas`；前端类型保证 `result.constellations` 非 undefined。

**调用流程**：
1. 识别完成 → `scan.result.constellations[0]` 就位
2. `watch` 触发 → `atlasStore.getAtlas(trad, abbr)` 加载
3. `atlasData` computed 自动从 `atlasCache` 取数据
4. 用户切 "真实投影" chip → `atlasMode = 'real-projection'` → StarCanvas 重渲染

### 5.3 `getAtlas` 行为（spec v3 已有，确认）

```typescript
async function getAtlas(tradition: string, abbr: string): Promise<void> {
  const key = `${tradition}/${abbr}`
  if (atlasCache.value[key]) return  // 缓存命中跳过
  const data = await getConstellation(tradition, abbr)
  atlasCache.value = { ...atlasCache.value, [key]: data }
}
```

**MVP 不暴露**：loading / error 状态第二期再补。

### 5.4 ConstellationView 不变

按 C 方案分工，ConstellationView **继续用 `mode="scan-atlas"`**（美术 viewBox）。真实模式仅 ScanView 暴露。

---

## 6. 测试策略

### 6.1 后端单元测试

#### `services/traditions.py`（11 个新测试）

| # | 测试名 | 断言 |
|---|---|---|
| 1 | `test_haversine_low_lat_matches_simplified` | ori → and 角距 = 73°，偏差 < 0.001° |
| 2 | `test_haversine_high_lat_no_distortion` | Dec=89° 处与已知参考实现（atan2 解析值）偏差 < 1e-6° |
| 3 | `test_find_nearest_returns_list` | `find_nearest(84,-1)` → `len() == 1` 且 `[0]` 是 tuple |
| 4 | `test_find_nearest_top_k_truncates` | mock 5 星座全在阈值内 → `top_k=2` 返回 2 项按角距升序 |
| 5 | `test_find_nearest_empty_when_above_threshold` | 任意坐标超 5° → `[]` |
| 6 | `test_meta_load_normal` | `_meta.json` 含 label → `get_meta('western')['label'] == '西方星座'` |
| 7 | `test_meta_missing_falls_back` | 缺 `_meta.json` → `get_meta('xxx')['label'] == 'xxx'` + warn 日志 |
| 8 | `test_meta_corrupt_json_falls_back_meta` | 坏 JSON → meta 用默认值 + error 日志；`_DATA[key]` 仍有星表数据（与 1.2 fail-soft 行为一致） |
| 9 | `test_meta_star_count_auto_corrected` | meta 写 star_count=99 → 实际 5 → 自动校正 + warn |
| 10 | `test_double_check_locking_idempotent` | 多线程并发调 `_load_all()` 100 次 → `_DATA` 引用一致 |
| 11 | `test_get_meta_lowercase` | `get_meta('WESTERN')` 等同 `'western'` |

#### `routers/identify.py`（1 个更新）

- `test_identify_solve_uses_nearest_list` 更新断言为 list 类型

#### `routers/constellations.py`（5 个新测试）

详见节 3.5 表格。

#### `scripts/validate_atlas.py`（2 个新测试）

- `test_meta_required_fields` — _meta.json 必含 key/label/star_count/coordinate_system
  - `key == dir_name`（小写）
  - `coordinate_system ∈ {"equatorial", "mansion"}`
- `test_meta_star_count_matches_glob` — `meta.star_count == len(glob("*.json")) - 1`

### 6.2 前端单元测试

#### `StarCanvas.test.ts`（4 个新测试，新建）

| # | 测试名 | 断言 |
|---|---|---|
| 1 | `test_real_projection_renders_stars` | mock atlasData → mode='real-projection' → 8 主星渲染 |
| 2 | `test_real_projection_center_cross` | 中心十字位于 canvas 中心 |
| 3 | `test_compute_field_ra_wrap` | star RA=355°, center RA=5° → dra=-10°（非 +350°） |
| 4 | `test_display_name_chinese_uses_name_zh` | tradition='chinese' + star.name_zh='参宿四' → 标注 '参宿四' |

#### `ScanView.test.ts`（5 个新测试，新建）

| # | 测试名 | 断言 |
|---|---|---|
| 1 | `test_default_atlas_after_solve` | solve 完成 → `overlayMode === 'atlas'` + `atlasMode === 'scan-atlas'` |
| 2 | `test_click_real_projection` | 点 "真实投影" chip → `atlasMode === 'real-projection'` |
| 3 | `test_click_photo_overlay` | 点 "照片叠层" chip → `overlayMode === 'overlay'` |
| 4 | `test_getAtlas_called_after_solve` | solve 完成 → `atlasStore.getAtlas('western', 'ori')` 被调 1 次 |
| 5 | `test_cache_hit_no_reload` | mode 切换不触发 `getAtlas` |

### 6.3 回归测试

- 后端 102 → **121 passed**（净增 +19）
  - services.traditions: +11（Haversine 2 / find_nearest 3 / _meta 6）
  - routers.identify: +1（find_nearest 适配）
  - routers.constellations: +5（traditions meta 2 / constellation include_stories 2 / constellations meta 1）
  - scripts.validate_atlas: +2（_meta 必填字段 + star_count 校验）
- 前端 63 → **72 passed**（净增 +9）
  - StarCanvas.test.ts: +4（real-projection 渲染 / 中心十字 / RA wrap / 中文标注）
  - ScanView.test.ts: +5（默认 atlas / 三 chip 切换 / getAtlas 触发 / cache hit）
- vue-tsc 0 error
- validate_atlas.py 0 hard errors（_meta 校验就位）

### 6.4 live E2E

| 用例 | 验证 |
|---|---|
| `live_identify_orion_mock` | mock WCS 中心 (84,-1) → constellations[0].abbr='ori', tradition='western' |
| `live_traditions_meta` | `/api/traditions` 含 description/coordinate_system |
| `live_constellation_include_stories_false` | `?include_stories=false` → stories=null |
| `live_real_projection_render` | 前端 mode='real-projection' → 8 主星可见（截图存档） |

---

## 7. 验收标准（pass/fail 清单）

### 7.1 后端验收

| 项 | 命令 / 操作 | 预期 |
|---|---|---|
| pytest 全绿 | `cd server && .venv/Scripts/python.exe -m pytest -q` | **121 passed**（原 102 + 净增 19） |
| Haversine 精度 | `pytest test_traditions.py::test_haversine_low_lat_matches_simplified` | 偏差 < 0.001° |
| find_nearest 类型 | `pytest test_traditions.py::test_find_nearest_returns_list` | 返回 list |
| _meta 加载 | `pytest test_traditions.py::test_meta_load_normal` | `_META['western']['label'] == '西方星座'` |
| 端点契约 | `curl /api/traditions \| jq` | 含 description/coordinate_system |
| include_stories | `curl '/api/constellation/western/ori?include_stories=false'` | `stories == null` |
| 422 兼容 | `curl /api/constellations` | HTTP 422（spec v3 不变） |
| 404 兼容 | `curl /api/constellation/western/xxx` | HTTP 404 |

### 7.2 前端验收

| 项 | 命令 / 操作 | 预期 |
|---|---|---|
| vitest 全绿 | `cd web && npx vitest run` | **72 passed**（原 63 + 净增 9） |
| vue-tsc | `cd web && npx vue-tsc --noEmit` | **0 error** |
| ScanView 默认模式 | `ScanView.test.ts test_default_atlas_after_solve` | `overlayMode === 'atlas'` + `atlasMode === 'scan-atlas'` |
| ScanView 切换 | `test_click_real_projection` | `atlasMode === 'real-projection'` |
| StarCanvas 真投影 | `StarCanvas.test.ts test_real_projection_renders_stars` | 8 主星 canvas data URL 非空 |
| RA wrap | `test_compute_field_ra_wrap` | dra = -10° |
| displayName 中文 | `test_display_name_chinese_uses_name_zh` | tradition='chinese' 用 name_zh |
| ConstellationView 不变 | `ConstellationView.test.ts` 全绿 | mode 仍为 'scan-atlas' |

### 7.3 数据验收

| 项 | 命令 / 操作 | 预期 |
|---|---|---|
| _meta.json 完整 | `cd server && .venv/Scripts/python.exe scripts/validate_atlas.py` | **0 hard errors, 0 soft warnings** |
| _meta 字段 | `cat server/data/traditions/western/_meta.json` | 含 key/label/star_count/coordinate_system |
| chinese 空 | `ls server/data/traditions/chinese/` | `.gitkeep` 占位 |
| 旧文件未回归 | `find server/data -name '*.json' \| grep -v traditions` | 空 |

### 7.4 live E2E

| 用例 | 操作 | 预期 |
|---|---|---|
| L1 识别 hit | `curl -X POST /api/identify/solve -F "image=@assets/test1.jpg"` | `solved=true` |
| L2 端点契约 | `curl /api/traditions \| jq` | 返回 list 含 description |
| L3 include_stories | `curl '/api/constellation/western/ori?include_stories=false'` | `stories=null` |
| L4 真投影 UI | `npm run dev` + 浏览器识别 test1.jpg + 切 "真实投影" | 8 主星按 RA/Dec 渲染（截图存档） |
| L5 端点回归 | `/api/constellations?tradition=western` | 含 `tradition_meta.label` |

### 7.5 commit 规范

- 单一 commit：`feat(atlas): spec v4 后端精度+API 优化+RA/Dec 真投影`
- 文件改动统计：~14 个文件，~700 行新增
- 不提交 `server/scripts/build_tradition_data.py`（一次性脚本，参照 prepare_samples.py 约定）

---

## 8. 不在本次范围

### 8.1 本次明确不做

- **WCS 3D 向量点积**：Haversine 已够 MVP；高纬失真场景在 spec v3 TODO 已撤销
- **`find_nearest` 暴露多候选 UI**：后端支持 list 返回（top_k=3），前端 MVP 仅取首个；第二期做"匹配度排序"chip
- **`include_stories=false` 前端调用**：后端支持，前端 MVP 不调用（payload 优化钩子就位）
- **`_meta.json` 多语言扩展**：当前仅 `label`/`label_en` 字段；第二期加 `label_ja`/`label_ko` 等
- **ConstellationView 切真实模式**：C 方案分工，仅 ScanView 暴露；ConstellationView 沿用美术 viewBox

### 8.2 业务包暂存（spec v5 占位）

项 1（第二期第三期数据补齐）+ 项 2（中国独有视觉）**单独写 spec v5 暂存**，等业务定义到位再开工：

```
待业务定义：
- 西方 88 余下 83 个加哪些 MVP 范围外？（全加？按季节？按最亮星先加几个？）
- 中国 28 宿 + 三垣 数据从哪来？（中科院星表？维基？自制？）
- 精度要求？（0.01°？0.001°？包含 magnitude？）
- 版权协议？（星表数据商用许可？）
- "中国独有视觉"具体是什么？（赤道环？二十八宿分布图？星官连线？）
```

**v5 spec 当前不能写**：业务定义缺失会导致 spec 内 70% 是 placeholder/TODO，违反 brainstorm 自检规则。

**预期流程**：业务定义到位 → 写 spec v5 → brainstorm → plan → 实现（独立 spec → plan → impl 周期）。

### 8.3 任务 14 MVP 回顾

T7 atlas tradition MVP（spec v3）已 14/14 完成：
- 5 西方星座数据 + chinese 空目录
- 后端 102 测试 + 前端 63 测试 + vue-tsc 0 error
- validate_atlas 0 hard errors
- live E2E 链路通（test1.jpg 上游解算成功，catalog 投影正常）
- tradition 切换 UI 工作（western/chinese tabs）
- spec v4 在 v3 基础上做"局部精度 + API + 真投影"扩展
