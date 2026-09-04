# Atlas 投影失真修复设计稿

**日期**：2026-09-01
**作者**：Claude (brainstorming 协作)
**状态**：Draft → 待用户审批
**关联 spec**：
- `docs/specs/2026-08-25-atlas-data-completion.md`（数据生成管道，v4/v5 已记录的 cos(Dec) TODO）
- `docs/specs/2026-08-25-atlas-tradition-design.md`（多 tradition 架构）
- `docs/specs/2026-08-25-atlas-backend-rendering-tidy.md`（渲染端规范）

---

## 1. Goals & Non-Goals

### Goals

1. **统一投影公式源**：Chinese 与 Western 走同一套公式（Python build 端 + TypeScript runtime 端各一份，但定义一一对应），消除公式漂移。
2. **修复星点失真**：高赤纬区（紫微垣、北斗、猎户腰带等）的横向拉伸消失；星座恢复肉眼天空的天然横宽比。
3. **统一数据 schema**：Chinese 与 Western 的 JSON schema 收敛一致（HIP-keyed stars、`hip` 字段必有、`name`/`name_zh` 各自 tradition 正确）。
4. **方向直觉**：「东=右、北=上」与 Stellarium / SkySafari 等标准天文软件一致。

### Non-Goals

- **不引入 Hammer-Aitoff / Mollweide 等全天空投影**（这些是整片天的椭圆投影，不适合单星座）。
- **不动 viewBox 维度**（仍 700×700 正方形，留白可接受）。
- **不动 StarCanvas 的 mode 体系**（overlay / scan-atlas / real-projection 三档保留，但公式收敛一致）。
- **不动 ConstellationView / ScanView 的 UI 框架**（仅改 chip 名称和 default 不算 spec 范围）。
- **不补 Western 星座的英文常用专名全集**（没在 `starnames.csv` 的 fallback 到 Bayer 名，不强求补全）。

### 投影选型：为什么是 Stereographic

**目标**：渲染单个星座时星点之间的相对角度和形状要符合人眼在天空里看到的（即"Norton's Star Atlas / Stellarium 那种图"的感觉）。

**候选对比**：

| 投影 | 中心形状 | 边缘形状 | 适合单星座 | 复杂度 |
|---|---|---|---|---|
| Equirectangular + cos(center_dec) | ✓ | ✗ 横向拉扁（远离中心）| 一般 | 极简 |
| Equirectangular + cos(dec)（per-star）| ✓ | ✗ 高纬非线性畸变 | 差 | 简单 |
| **Stereographic（azimuthal）** | ✓ | ✓ 保角 | **好** | 中 |
| Hammer-Aitoff | 整片天椭圆投影 | — | ✗ 单星座像在鱼眼里 | 中 |

**Stereographic 选型理由**：
1. **保角（conformal）**：天球上的任意小圆映射到平面上仍是小圆，星座轮廓和连线不失真。这是 equirectangular 没有的性质。
2. **Norton's Star Atlas / Cambridge Star Atlas 等专业天文星图都用 stereographic**——不是因为传统，是因为对单星座来说它最接近人眼对一片天区"压平"的感知。
3. **跨 Dec 全档都好**：高赤纬（紫微垣、北斗）和低赤纬（猎户、天蝎）走同一套公式。
4. **Hammer-Aitoff 不行**：是整片天投影，单星座放在里面会显得在小鱼眼镜头里。
5. **公式复杂度可控**：相比 equirectangular 只多 5-8 行标准球面三角，Python 和 TS 都好实现。

**注意事项**：
- Stereographic 远离中心时**面积会被放大**（这是 conformal 投影的固有代价，不是 bug）：
  - 线性放大因子 = k = 2/(1+cos c)
  - c=15° 时 k ≈ 1.017（线性 1.7%、面积 3.5%）
  - c=30° 时 k ≈ 1.072（线性 7.2%、面积 15.4%）—— 单星座边缘星在这个量级
  - c=60° 时 k ≈ 1.333（线性 33%、面积 78%）—— 接近半个画布宽度才会到这个
- 中心点 `c = 0` 时公式不奇异（x_local, y_local 趋 0）；但加 guard 保证双端数值一致（spec §3.2）。
- 不声称"边缘完全无畸变"——Stereographic 仍是投影，没有 0 失真。保的是形状不是面积。

---

## 2. 背景：当前问题（已被调研确认）

### 2.1 scan-atlas 模式用手绘 x/y，不走 ra/dec

- `server/data/traditions/western/ori.json:17-105` 每颗星同时存 `x/y`（手绘）和 `ra/dec`（真值）
- `web/src/components/StarCanvas.vue:317-340` `drawScanAtlas` 完全不读 ra/dec，只读 `x/y`
- Western 的 `x/y` 是手工标注美术画布坐标，几轮 commit 累积人工微调（含 `e2ed1bf` RA 镜像引入）

### 2.2 Chinese build script 用了 sx≠sy

- `server/scripts/build_chinese_stars.py:269-283` 投影公式：
  ```python
  sx = (VIEW_W / 2 - 30) / max(max_dra_cos, 0.001)
  sy = (VIEW_H / 2 - 30) / max(max_ddec,    0.001)  # sx ≠ sy
  ```
- 北斗：sy=51 px/°、sx=27 px/°，Dec 方向被拉高 89%，勺子被纵向拉成"竖着的怪形"
- spec v5 决策表 #8 已记录 cos(Dec) 回退，但脚本未对齐

### 2.3 Runtime 渲染 `worldToPixelEquirect` 没加 cos(Dec)

- `web/src/components/StarCanvas.vue:94-109` `worldToPixelEquirect` 直接用 ΔRA，**不乘任何 cos(Dec)**（既不是 cos(center_dec) 也不是 cos(dec)）
- 这是最朴素的等距投影，**高纬区 RA 方向被整体横向拉宽**（1/cos(55°) ≈ 1.74×）
- 在 Dec=+55° 区**与 Chinese scan-atlas 失真方向相反**（一个横向拉，一个纵向拉），导致两个模式同一北斗形状错位
- spec v4 `StarCanvas.vue:96-97` 注释明确"cos(Dec) 修正留作 TODO"，spec v4 声明"MVP 范围 |Dec| < 45°"（北斗 Dec=55° 超界）
- **本期方案不修这个公式**：本期直接换 Stereographic，公式整段重写；cos(Dec) 方案作为 Stereographic 之前的过渡产物被弃用。

### 2.4 数据 schema 不一致

- Western JSON 没有 `hip` 字段，Chinese 有
- Western JSON 的 `name` 字段填的是中文古名（"参宿四"），不是西方常用英文专名（Betelgeuse），导致 `displayNameFor(western)` 实际显示中文
- Chinese 三垣 entry（紫微/太微/天市）没写 `x/y`，只能走实时投影；Western 全部写了 `x/y`

---

## 3. 架构：单公式源 + 双端共享

### 3.1 模块布局

```
server/scripts/atlas_projection.py        # 新建：Python 端公式（build 脚本依赖）
  ├─ project(ra, dec, center, scale, viewbox) -> (x, y)        # Stereographic 投影
  ├─ compute_field(stars, viewbox) -> {scale, padding, center} # 中心 + scale + padding
  ├─ compute_center(stars) -> (ra, dec)                        # cos-Dec 加权几何中心
  └─ angular_separation(ra1, dec1, ra2, dec2) -> float         # 球面角距（度）

server/scripts/build_western_stars.py     # 新建：从 celestial_data 重算 88 个 JSON
server/scripts/build_chinese_stars.py     # 改：调新公式、移除 RA 镜像

web/src/utils/atlasProjection.ts          # 新建：TypeScript 端公式（StarCanvas 依赖）
  ├─ projectStereographic(ra, dec, center, scale, viewbox) -> (x, y)
  ├─ computeField(stars, viewbox) -> {scale, padding, center}
  ├─ computeCenter(stars) -> {ra, dec}
  └─ angularSeparation(ra1, dec1, ra2, dec2) -> number

web/src/components/StarCanvas.vue         # 改：worldToPixelEquirect 调 atlasProjection.ts
                                          # 改：displayNameFor 走正确的 name 字段
```

### 3.2 投影公式（统一 — Azimuthal Stereographic）

```python
import math

# 输入（所有角度单位：度）
stars:    list[{ra: float, dec: float}]   # 星座成员的 ra/dec
viewbox:  {w: int, h: int}                # 默认 700×700
padding:  int = 30

# ─────────────────────────────────────
# Step 1: center（单位球面 3D 向量平均 → 归一化回球面坐标）
# ─────────────────────────────────────
# 把每颗星当作单位球面上的点，求所有成员的 3D 单位向量平均，
# 然后用 atan2 归一化回 (RA, Dec)。这是球面几何中心的标准做法，
# 对极区、宽视场（如三垣）行为良好，不依赖任意加权方案。
#
# x = cos(dec) · cos(ra)  （赤道平面内，朝 RA=0 方向）
# y = cos(dec) · sin(ra)  （赤道平面内，朝 RA=90° 方向）
# z = sin(dec)            （朝北天极）
vx_avg = mean(cos(radians(dec_i)) · cos(radians(ra_i)) for star)
vy_avg = mean(cos(radians(dec_i)) · sin(radians(ra_i)) for star)
vz_avg = mean(sin(radians(dec_i)) for star)

center_ra  = degrees(atan2(vy_avg, vx_avg)) % 360
center_dec = degrees(atan2(vz_avg, sqrt(vx_avg² + vy_avg²)))

# 北斗 7 星实测 golden value：(186.04°, 56.55°)
# 计算依据：54061 + 53910 + 58001 + 59774 + 62956 + 65378 + 67301 的 3D 单位向量平均

# ─────────────────────────────────────
# Step 2: scale（取最大球面角距对应的平面半径，等比填 viewbox）
# ─────────────────────────────────────
# Stereographic 投影下，球面角距 c 对应的平面半径 r = 2 · tan(c/2)
# 找到所有星到 center 的最大 c，算出对应 r，按 viewbox 取等比 scale。
def angular_separation(ra, dec, ra0, dec0):
    dra = math.radians(ra - ra0)
    cos_c = (math.sin(math.radians(dec0)) * math.sin(math.radians(dec))
             + math.cos(math.radians(dec0)) * math.cos(math.radians(dec))
             * math.cos(dra))
    cos_c = max(-1.0, min(1.0, cos_c))  # clamp 防 acos 数值越界
    return math.degrees(math.acos(cos_c))

max_c = max(angular_separation(s["ra"], s["dec"], center_ra, center_dec)
            for s in stars) if stars else 0.0

if max_c < 1e-6:
    # 极端 case：所有星同点（理论上不该发生）
    scale = 1.0
else:
    # 平面半径 = 2·tan(c_max/2)（stereographic 单位圆半径）
    max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
    # 等比 fit 进 viewbox（取较小，留白可接受）
    scale = min(
        (viewbox["w"] / 2.0 - padding) / max_radius,
        (viewbox["h"] / 2.0 - padding) / max_radius,
    )

# ─────────────────────────────────────
# Step 3: 单点投影（Azimuthal Stereographic）
# ─────────────────────────────────────
def project(ra, dec, center_ra, center_dec, scale, viewbox):
    dra_rad   = math.radians(ra - center_ra)
    dec_rad   = math.radians(dec)
    dec0_rad  = math.radians(center_dec)

    # 球面角距的 cos
    cos_c = (math.sin(dec0_rad) * math.sin(dec_rad)
             + math.cos(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad))
    cos_c = max(-1.0, min(1.0, cos_c))

    # ★ 中心点 guard（公式本身不除以 sin_c，x_local/y_local 在 c→0 时自然趋于 0；
    #   但加 guard 防止极小数舍入差异导致 Python / TS 双端输出不一致）。
    #   阈值 1e-14 对应角距 ≈ 2e-7 rad ≈ 1e-5°，远小于 sub-pixel 精度。
    if abs(1.0 - cos_c) < 1e-14:
        return (viewbox["w"] / 2.0, viewbox["h"] / 2.0)

    # Stereographic 缩放因子
    k = 2.0 / (1.0 + cos_c)

    # 局部平面坐标（旋转后坐标系：x = 东, y = 北）
    x_local = (math.cos(dec_rad) * math.sin(dra_rad))
    y_local = (math.cos(dec0_rad) * math.sin(dec_rad)
               - math.sin(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad))

    # 东=右、北=上；屏幕 y 朝下故取负
    x = viewbox["w"] / 2.0 + k * x_local * scale
    y = viewbox["h"] / 2.0 - k * y_local * scale
    return (x, y)
```

**公式要点**：

| 项 | 含义 |
|---|---|
| `cos_c` | 球面角距 c 的余弦值（来自球面余弦定理） |
| `k = 2/(1+cos_c)` | Stereographic 缩放因子（c=0 时 k=1，c=π 时 k→∞） |
| `x_local` / `y_local` | 旋转后局部平面坐标（无 k 无 scale） |
| **中心点特例** | `cos_c = 1`（即 c = 0）时方向角公式 `0/0`，**必须**显式返回画布中心 |
| 屏幕 y 翻转 | 屏幕 y 朝下，但局部坐标 y_local 北=正，故最终 y 取 `-k · y_local · scale` |
| 东=右 | `x_local = cos(dec)·sin(ΔRA)`，ΔRA > 0 → x_local > 0 → 屏幕 x 增大 |

### 3.3 Python / TypeScript 公式对齐

| 函数 | Python (`atlas_projection.py`) | TypeScript (`atlasProjection.ts`) |
|---|---|---|
| 中心计算 | `compute_center(stars)` | `computeCenter(stars): {ra, dec}` |
| 跨度 + scale | `compute_field(stars, viewbox)` | `computeField(stars, viewbox): {scale, padding, center}` |
| 单点投影 | `project(ra, dec, center, viewbox, scale)` | `projectStereographic(ra, dec, center, viewbox, scale)` |
| 球面角距 | `angular_separation(ra1, dec1, ra2, dec2)` | `angularSeparation(ra1, dec1, ra2, dec2)` |

**对齐守护**：
- `server/tests/test_atlas_projection.py` 与 `web/tests/utils/atlasProjection.spec.ts` 共享一组 golden values（北斗 7 星、猎户腰带 3 星、织女一 Vega 的精确坐标）
- 数值偏差阈值 0.01 px（远小于 1 像素）
- 中心点奇异性 (`cos_c ≈ 1`) 两端都做特殊处理，输出严格一致

**为什么公式两端各写一份而不是用 wasm/python 跨语言**：
- 公式只 5-8 行球面三角，Python `math` 和 JS `Math` 都有原生支持
- 维护成本：双端各 30 行代码 vs wasm 工具链（rust + wasm-pack + 异步加载 + 失败回退）
- 一致性守护靠 spec 里的 golden values 而不是共享代码（明确"两套实现要输出一致"的契约）

---

## 4. 数据 Schema 统一

### 4.1 收敛后的 entry schema

```json
{
  "abbr": "ori",
  "name": "Orion",                  // ★ Western entry name 来自 latin（"Orion/Ursa Major/..."）
  "name_zh": "猎户座",                  // ★ Chinese entry name 来自 constellations.cn.csv
  "latin": "Orion",
  "viewBox": { "width": 700, "height": 700 },
  "center": { "ra": 86.0, "dec": -1.0 },
  "stars": {
    "HIP_54061": {                       // ★ HIP 作为 key（之前 Chinese 用 HIP key，Western 改跟齐）
      "bayer": "Alpha Ori",             // Bayer 希腊字母命名（Chinese 留空）
      "name": "Betelgeuse",             // ★ Western 单星 name 来自 starnames.csv（之前填中文 = bug）
      "name_zh": "参宿四",               // 中文古名（Western 也要有，从 assets/星官对应.md 拉）
      "magnitude": 1.81,
      "ra": 88.7929,
      "dec": 7.4071,
      "label": true,                    // mag < 4.5 为 true，≥ 4.5 为 false
      "hip": "54061",                   // ★ 必有（之前 Western 缺）
      "x": 320.5, "y": 405.2            // 公式算（Chinese 三垣除外）
    }
  },
  "lines": [["HIP_54061", "HIP_37279"], ...],  // ★ 用 HIP 引用（之前 Western 用 ID 字符串）
  "season": "winter",
  "caption": "...",
  "stories": { "myth": {...}, "science": {...} }
}
```

**注意**：entry `name` 和星 `name` 是两层不同概念：
- **entry-level name**（88 个 constellation 的名字）：Western 从 `latin` 派生（"Orion"），Chinese 从 `constellations.cn.csv` 派生（"猎户座"）
- **star-level name**（每颗星的名字）：Western 从 `starnames.csv` 派生（"Betelgeuse"），Chinese 从 `assets/星官对应.md` 派生（"参宿四"）

### 4.2 `name` 字段规则

**Entry-level name**（88 个 constellation 自己的名字）：

| tradition | entry `name` | entry `name_zh` |
|---|---|---|
| **Western** | 从 `latin` 字段派生（"Orion" / "Ursa Major"） | 从 `constellations.cn.csv` 派生（"猎户座" / "大熊座"） |
| **Chinese** | 从 `constellations.cn.csv` 派生（"参宿" / "心宿"） | 同 `name`（同源同值） |

**Star-level name**（每颗星的名字）：

| tradition | star `name` | star `name_zh` | `bayer` | `hip` |
|---|---|---|---|---|
| **Western** | 英文常用专名（Betelgeuse/Sirius/Vega）从 `starnames.csv` 拉；缺失则 fallback 空串（**不是** Bayer 名） | 中文古名（从 `assets/星官对应.md` 拉）| IAU Bayer | 必填 |
| **Chinese** | 中文星官名（参宿四） | 同 `name` | 空（Bayer 是西方体系） | 必填 |

**为什么 star.name fallback 用空串而不是 Bayer 名**：
- Bayer 名（"Alpha Ori"）跟 Chinese 兜底"未命名"在界面上的可读性差不多，但 Bayer 名容易被误读为"系统找了个能显示的名字"，误导用户以为找到了正确的专名
- 空串会走 displayNameFor 兜底到 "未命名"——明确告诉用户"系统不知道这颗星的名字"
- §4.2 displayNameFor fallback 链已经覆盖这个 case

`displayNameFor`（`web/src/components/StarCanvas.vue:23-32`）改为：

```typescript
export function displayNameFor(star: Star, trad: Tradition): string {
  if (trad === 'chinese') {
    return (star.name_zh ?? star.name ?? '').trim() || '未命名'
  }
  // Western 走真正的英文专名，fallback 才到中文古名；都没有就"未命名"
  return (star.name ?? star.name_zh ?? '').trim() || '未命名'
}
```

**注意**：本 spec 改动 ConstellationView 的 entry 显示名（从中文星官名 → 西方拉丁名）。这是 entry schema 语义变化带来的预期显示变化，**在 Non-Goal「不动 UI 框架」的允许范围**（chip / 列表 / 详情页结构不变，只是文字内容变化）。

### 4.3 三垣 entry 例外

`zi_wei_yuan.json`、`tai_wei_yuan.json`、`tian_shi_yuan.json` 的 `stars` **不写 `x/y`**（保持现有约定），运行时由 `atlasProjection.projectStereographic` 实时算。Stereographic 公式本身处理任意极区角距，不再有"span 爆炸"问题——三垣成员覆盖整个北极圈都没事。

---

## 5. Build Scripts

### 5.1 `build_chinese_stars.py` 改动

- 移除 `server/scripts/build_chinese_stars.py:269-283` 内联的 x/y 计算
- 改为调 `atlas_projection.py:compute_center` / `compute_field` / `project`
- **移除 RA 镜像**（commit `e2ed1bf` 引入的 `s["x"] = ... - dx * sx` 改为 `s["x"] = ... + dx * sx`）
- sx/sy 改成等比 `scale = min(...)`
- 三垣 entry 仍不写 x/y
- 保留所有其他逻辑（CSV 解析、HIP Haversine 匹配、附官 fallback、6 垣墙合并等）

### 5.2 `build_western_stars.py` 新建

数据源：
- `celestial_data/constellations.lines.geojson`（端点为 HIP）
- `celestial_data/constellations.boundaries.csv`（IAU 1930 星座边界多边形）— 用于"星座内星"判定
- `celestial_data/stars.8.min.geojson`（HIP + RA + Dec + mag，覆盖 mag ≤ 8 全天星）
- `assets/星官对应.md`（HIP → 中文古名对照表）
- `celestial_data/starnames.csv`（HIP → 英文常用专名）

输出：88 个 `server/data/traditions/western/{abbr}.json`，每个含完整 schema。

**收录规则（决定 stars 里包含哪些星）**：
- **必收**：constellations.lines.geojson 中本星座所有 line 端点引用的 HIP（连线必须能画出来）
- **可选**：mag < 5.5 且在 IAU 1930 星座边界内的星（亮星才标名字，背景星不画连线）
- `label = true` 阈值：mag < 4.5（5.5 边界内的暗星保留在 stars 列表，但不画文字标注）

**字段填充规则**：

| 字段 | 来源 | 兜底 |
|---|---|---|
| `abbr` | 文件名 stem | — |
| entry `name` | `latin` 字段派生 | — |
| entry `name_zh` | `constellations.cn.csv` → 中文星官名 | fallback 拉丁名 |
| `latin` | `constellations.lines.geojson` → `properties.constellation` | — |
| star `name` | `starnames.csv` → `english_name` | **空串**（不 fallback Bayer，§4.2 解释）|
| star `name_zh` | `assets/星官对应.md` → 中文古名 | 空串 |
| star `bayer` | `starnames.csv` → `bayer` | 空串 |
| `center` | `compute_center(stars)`（§3.2 3D 向量平均） | — |
| `stars[HIP].x/y` | `project(ra, dec, center, viewbox)` | — |
| `stars[HIP].label` | `mag < 4.5` | — |
| `lines` | `constellations.lines.geojson` 端点转 HIP | — |
| `season` | **原 JSON 有则拷，无则按 RA 推**（RA 0-6h→winter, 6-12h→spring, 12-18h→summer, 18-24h→autumn）| 空串 |
| `caption` | **原 JSON 有则拷，无则空串** | 空串 |
| `stories` | **原 JSON 有则拷，无则 `{}` 空 dict** | `{}` |

**Fail-fast**：celestial_data 缺哪个星座，脚本 fail 并写 `assets/missing_constellations.md`，列出缺失列表，让用户手工补。

**Stars.8.min.geojson 完整性自检**：脚本启动时检查 stars.8.min.geojson 是否包含本星座所有 line 端点的 HIP；若缺，写 `assets/missing_stars.md`（HIP 列表），让用户手工补源数据。

---

## 6. Runtime 渲染改动

### 6.1 `StarCanvas.vue` 改动清单

| 位置 | 改动 |
|---|---|
| 行 23-32 `displayNameFor` | Western 走 `star.name`（Commit 3 后能拿到 "Betelgeuse"） |
| 行 65-92 `computeField` | 删内联公式，改为调 `atlasProjection.computeField`（返回 scale） |
| 行 94-109 `worldToPixelEquirect` | 删内联公式，改为调 `atlasProjection.projectStereographic` |
| 行 317-340 `drawScanAtlas` | 行为不变（读 x/y，但 x/y 现在由 Stereographic 公式生成） |
| 行 363-477 `drawRealProjection` | 行为不变（已调 `worldToPixelEquirect`，自动跟随新公式） |
| 全局 | 删除 `cosDecAdjustment`、`normalizeRaDiff` 等仅 equirectangular 用的辅助 |

### 6.2 视图层零改动

`ConstellationView.vue`、`ScanView.vue` 不需要任何 UI 改动（mode 体系保持）。

---

## 7. 测试策略

### 7.1 新增单元测试

**`server/tests/test_atlas_projection.py`**：

- `test_compute_center_known_constellation`：北斗 7 星（54061/53910/58001/59774/62956/65378/67301）→ center = **(186.04°, 56.55°)** ±0.01°（§3.2 公式手算的 golden value）
- `test_compute_field_radial_symmetry`：所有星到 center 的最大 c 对应的 `2·tan(c/2)` × scale ≤ `viewbox/2 - padding`
- `test_project_center_singularity`：传入 `(center_ra, center_dec)` 返回值与画布中心 **(viewbox.w/2, viewbox.h/2) 误差 < 1e-6 px**（注意浮点不会 strict equal）
- `test_project_east_right`：ΔRA > 0 的星 x > viewbox.w/2
- `test_project_north_up`：Δdec > 0 的星 y < viewbox.h/2
- `test_project_conformal_smoke`：北斗 7 星投影后相邻星的角度关系（至少 3 对）保留 ±1°
- `test_angular_separation_known_pair`：织女一(Vega, RA 18h37m Dec +38°)-牛郎(Altair, RA 19h51m Dec +9°)= ~34° ±0.1°（教科书标准值）
- `test_sanyuan_max_angular_distance`：**专门验证三垣（紫微/太微/天市）成员的 max_c < 90°**（如果某星 > 90°，脚本要 raise / 降级到另一投影）

**`web/tests/utils/atlasProjection.spec.ts`**：
- 跟 Python 端同一组 golden values（北斗 7 星 + Vega/Altair），阈值 0.01 px
- 中心点奇异性特殊处理两端一致（容差 1e-6 px，不是 strict equal）
- 公式交叉验证（同一组输入，Python 输出 vs TS 输出误差 < 0.01 px）

### 7.2 视觉快照

**`web/tests/components/StarCanvas.spec.ts`** 新增：
- 北斗 7 星在 700×700 viewBox 里：参考实现跑一遍，把每颗星的 x/y 输出作为期望值，断言误差 < 1 px（**不是手写 [30, 670] 这种预估值**——参考实现才是 ground truth）
- 猎户腰带、参宿三星、紫微垣 5 颗核心星同款（跑参考实现 → 存期望 → 断言）
- 三垣（紫微垣，没 x/y）走 real-projection 渲染后所有星落在画布内（不溢出 viewBox）
- **方向断言**：Betelgeuse 的 x > Rigel 的 x（东=右约定守护，防止镜像公式回归）

### 7.3 既有测试守护

- 后端 26 测试（identify + jpeg_recompress + traditions + e2e）必须全过
- 前端 72 测试（jsdom + StarCanvas overlay/scan-atlas/real-projection）必须全过
- `server/tests/test_traditions.py`（如果存在）验证新 schema 不破坏多 tradition 反查
- **Commit 1 后预期部分 atlas 渲染快照断言失败**（公式变了 → 投影坐标变了）：这些是**预期失败**，Commit 1 实施时一并更新断言值，不算回归

### 7.4 e2e 人工验证

启真实上游 + 跑 test1.jpg：
- `POST /api/identify/solve` → 命中 constellation 的 ra/dec 应在 ±0.5° 内（精度守护）
- 切换 tradition：scan-atlas / real-projection 两个模式北斗形状应该**完全一致**（之前是错位的）

### 7.3 既有测试守护

- 后端 26 测试（identify + jpeg_recompress + traditions + e2e）必须全过
- 前端 72 测试（jsdom + StarCanvas overlay/scan-atlas/real-projection）必须全过
- `server/tests/test_traditions.py`（如果存在）验证新 schema 不破坏多 tradition 反查

### 7.4 e2e 人工验证

启真实上游 + 跑 test1.jpg：
- `POST /api/identify/solve` → 命中 constellation 的 ra/dec 应在 ±0.5° 内（精度守护）
- 切换 tradition：scan-atlas / real-projection 两个模式北斗形状应该**完全一致**（之前是错位的）

---

## 8. Migration / Commit 计划

按 CLAUDE.md 的 git 规范，分支 `fix-260901-atlas-projection-fix`，3 次 commit 后 squash merge 到 main。

### Commit 1: `refactor(atlas): 抽出 Azimuthal Stereographic 共享投影公式 + runtime 切换`

```
server/scripts/atlas_projection.py          # 新建：Python 公式（含中心点奇异性处理）
server/tests/test_atlas_projection.py       # 新建：北斗 golden values + 单测
web/src/utils/atlasProjection.ts            # 新建：TS 公式（与 Python 1:1 对齐）
web/tests/utils/atlasProjection.spec.ts     # 新建：golden values 交叉验证
web/src/components/StarCanvas.vue           # 改：worldToPixelEquirect + computeField 调新公式
```

**验证**：后端 26 测试 + 前端 72 测试全过；现有 atlas JSON 视觉变化分两阶段——Commit 1 后 **real-projection 模式**（ScanView 用）视觉立刻变（新公式生效），**scan-atlas 模式**（ConstellationView 用）视觉不变（仍读旧 x/y，JSON 未变）；Commit 2/3 让 scan-atlas 也跟随新公式。

### Commit 2: `fix(atlas): Chinese 数据重生 + build script 走 Stereographic + 移除 RA 镜像`

```
server/scripts/build_chinese_stars.py       # 改：调 atlas_projection.projectStereographic、移除 RA 镜像
server/data/traditions/chinese/*.json       # 310 个 JSON 重生（x/y 由新公式算）
server/data/traditions/chinese/_meta.json   # 更新 star_count 等字段
```

**验证**：北斗在 atlas 视图变回天然横扁勺形（前后对比截图存档到 `04码道使用证明/`）；scan-atlas / real-projection 两个模式北斗形状完全一致。

### Commit 3: `feat(atlas): 新建 build_western_stars.py + Western 数据从 celestial_data 重生 + name 字段修复`

```
server/scripts/build_western_stars.py       # 新建：从 celestial_data 算 88 JSON
server/data/traditions/western/*.json       # 88 个 JSON 重生
server/data/traditions/western/_meta.json   # 更新
assets/missing_constellations.md            # 新建（仅当有缺失）
```

**验证**：Western 88 星座 atlas 视图全部走真投影；`displayNameFor('western')` 能拿到 "Betelgeuse" 等英文常用名。

### Squash Merge

最终 main 上单 commit：
```
fix(atlas): 投影统一改 Azimuthal Stereographic + Chinese/Western 数据重生

- 抽 atlas_projection.py / atlasProjection.ts 共享 Stereographic 公式（带中心点奇异性处理）
- worldToPixelEquirect 改调 atlasProjection.projectStereographic（替代朴素的等距投影）
- build_chinese_stars.py 调新公式、移除 commit e2ed1bf 引入的 RA 镜像、东=右
- 新建 build_western_stars.py 从 celestial_data 重生 88 JSON
- displayNameFor 修复 Western 走英文常用名（不再是中文兜底）
- 数据 schema 收敛：HIP-keyed stars、hip 字段必有
```

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Western 88 个 JSON 重生会丢人工微调（如猎户/天蝎的曲线连线） | 中 | 见下方 `hand_overrides` 机制 |
| celestial_data 不全 88 星座覆盖 | 低 | 脚本 fail-fast + 写 `assets/missing_constellations.md` |
| `starnames.csv` 不全英文常用专名 | 低 | star.name fallback 空串（§4.2） |
| Stereographic 远离 c 极值（c → π）时 `k = 2/(1+cos_c)` → ∞ | 极低 | `test_sanyuan_max_angular_distance` 验证三垣成员 max_c < 90°；运行时若 max_c > 170°，`compute_field` raise ValueError 阻止生成无效坐标 |
| Stereographic 边缘有面积放大（conformal 不是 equal-area） | 低 | 单星座边缘线性放大 ≤ 8%、面积 ≤ 15%；spec §1 已明确数字 |
| Commit 1 后 real-projection 模式视觉立刻变（公式变了，JSON 未变）；scan-atlas 视觉不变 | 中 | Commit 1 让 real-projection 立刻变新公式；Commit 2/3 让 scan-atlas 也跟随 |
| `server/data/traditions/` 310+88 = 398 个文件一起改 git history 大 | 中 | Squash merge 后只一条 commit，squash 前保留详细 commit history |
| Python / TS 双端公式漂移（两边独立维护 Stereographic 实现） | 中 | spec §3.3 的 golden values 交叉验证；同组输入两边输出误差 < 0.01 px |
| `stars.8.min.geojson` 不覆盖 88 星座所有 line 端点 HIP | 低 | 脚本启动自检 + `assets/missing_stars.md` 报告缺失列表 |

### `hand_overrides` 合并机制（Commit 3 重生时保护人工 patch）

**场景**：用户手工改了 `ori.json` 的某些字段（比如猎户连线画弧线而非直线、某个星位置微调），重跑 build 脚本时不想被覆盖。

**机制**：
- 允许 entry JSON 含 `hand_overrides: { stars?: {...}, lines?: [...] }` 字段，schema 顶层
- Build 脚本生成新数据后，**逐字段 merge**：
  - `hand_overrides.stars[HIP]` 内的字段（如 `x`、`y`、`bayer` 等）覆盖生成值
  - `hand_overrides.lines` 完全替换生成的 lines 数组
- 不在 `hand_overrides` 里的字段全部用新数据（保证 schema 演化能落地）

**示例**：
```json
{
  "abbr": "ori",
  "name": "Orion",
  ...
  "hand_overrides": {
    "stars": {
      "HIP_54061": { "x": 318.2, "y": 401.5 }   // 手调 Betelgeuse 位置
    },
    "lines": [["HIP_54061", "HIP_37279"], ...]  // 手画连线
  }
}
```

**注意事项**：
- `hand_overrides` 字段本身**不写入生成的 JSON**——它是"输入时提供合并源"，不是"输出 schema 的一部分"。脚本读旧 JSON 拿 overrides → 生成新内容 → 写新 JSON（不带 overrides 字段）
- 这意味着用户每次重跑脚本前要把 overrides 备份到别处（或用 git diff 保留 commit history）
- **更鲁棒方案**（远期）：把 overrides 存到 `server/data/traditions/western_overrides/{abbr}.json`，build 脚本自动 merge；但本期不在范围（增加 schema 复杂度）

---

## 10. 验证检查清单（合并前必须）

- [ ] `cd server && .venv/Scripts/python.exe -m pytest -q` 26 测试全过
- [ ] `cd web && pnpm test` 72 测试全过 + 新增 atlasProjection.spec.ts + StarCanvas.spec.ts 全过
- [ ] 手动启服务 + test1.jpg e2e：识别命中精度 ±0.5°
- [ ] 北斗前后对比截图存 `作品提交文件夹/04码道使用证明/260901-beidou-before-after.png`
- [ ] 猎户前后对比截图存 `作品提交文件夹/04码道使用证明/260901-orion-before-after.png`
- [ ] `git diff main` 整体改动 review
- [ ] Squash merge + 提交 `作品提交文件夹/04码道使用证明/` 新截图一起 commit

---

## 11. References

- `server/scripts/build_chinese_stars.py` — 当前 Chinese build 脚本（要改）
- `server/data/traditions/western/ori.json` — Western schema 样本（要重生）
- `server/data/traditions/chinese/bei_dou.json` — 北斗数据（要重生）
- `web/src/components/StarCanvas.vue` — 渲染端（要改）
- `docs/specs/2026-08-25-atlas-data-completion.md` — 数据生成规范（v4/v5 已记录的 cos(Dec) 过渡方案，本期升级为 Stereographic）
- `docs/specs/2026-08-25-atlas-backend-rendering-tidy.md` — 渲染规范（v4 MVP 范围 |Dec| < 45° 本期破除，改用全 Dec 适用的 Stereographic）
- `celestial_data` (dieghernan/celestial_data) — Western 数据上游
- `assets/星官对应.md` — 中西星名对照表
- Azimuthal Stereographic Projection — Snyder, J. P. (1987) "Map Projections — A Working Manual", USGS Professional Paper 1395, §20