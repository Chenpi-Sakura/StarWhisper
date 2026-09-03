# Atlas 数据补齐 — 西方 88 星座 + 中国星官 306（v5）

> **目的**：把 tradition 数据从 MVP 5 西方星座，扩展到西方 IAU 88 座全量 + 中国星官体系全量（三垣二十八宿，约 306 星官）。
> 本 spec 承接 spec v4（`docs/specs/2026-08-25-atlas-backend-rendering-tidy.md`）第 8.2 节"业务包暂存"。
>
> 前置：spec v4 已落地（Haversine + find_nearest list + `_meta.json` + `real-projection` 真投影）。

**日期**：2026-08-25
**状态**：v5 — 设计稿（二审修订，已实测数据源 schema）
**范围**：数据模型（中国星官落地）/ 数据来源与采集管道 / 后端 services+routers / 前端 StarCanvas 星官连线 / 测试 / 验收

## 0. 业务定义（已确认）

| 维度 | 决策 |
|---|---|
| 西方星座 | IAU 88 座全量 |
| 中国星官 | 三垣二十八宿全量，约 306 星官 |
| 字段/精度 | RA/Dec + magnitude，0.01° |
| 数据来源 | `celestial_data` 开源 GeoJSON/CSV（dieghernan 维护）+ `assets/星官对应.md`（维基中西星名对照表） |
| 中国独有视觉 | 星官连线图（按星官分组连线，星官名标注） |

## 1. 数据模型

### 1.1 现有 schema（spec v3 已落地，不可破坏）

单文件 `traditions/{key}/{abbr}.json`（ori.json 为基准）：`abbr/name/latin/glyph/season/caption/viewBox/center{ra,dec}/stars{starKey:{x,y,bayer,name,name_zh,magnitude,ra,dec,label}}/lines[[a,b]]/mansion/asterism_id/stories`。

### 1.2 中国星官语义 + entry 粒度

| 字段 | 西方 | 二十八宿 entry | 三垣 entry | 一般星官 entry | 近南极 entry |
|---|---|---|---|---|---|
| `mansion` | `null` | 本宿 id（如 `shen`） | `null` | 所属宿 id 或 `null` | `null` |
| `asterism_id` | `null` | `null` | 本垣 id（如 `ziwei`） | 所属垣 id 或 `null` | `"nanji"`（近南极伪垣） |

**entry 粒度（已拍板）**：按星官，约 306 个。`constellations.cn` 312 对象 = 28 宿 + 6 垣墙 + 278 星官。

**三垣合并（评审澄清）**：`constellations.cn` **没有**"紫微垣/太微垣/天市垣"本体 entry，只有 6 个垣墙（`rank=2`：紫微左/右垣、太微左/右垣、天市左/右垣）。若不做合并，三垣会**凭空消失**。故 3 个三垣 entry 由 6 垣墙合并生成：
- `lines` = 左+右垣墙连线（`lines.cn` 中 `rank=2` 的 feature）
- `stars` = 垣墙连线端点回填的星（城墙星）
- 垣**内**星官（`rank=3`，如"北极""勾陈""北斗"）**各自仍是独立 entry**，不并入三垣 stars——三垣 entry 只代表"城墙轮廓"

**近南极星官（评审新增）**：23 个近南极星官（海山/十字架/马腹等）不属三垣也不属二十八宿，`mansion=null` 且 `asterism_id="nanji"`（伪垣），使"至少一个非 null"校验规则无需放宽。

最终 entry 数 = **28 宿 + 3 垣 + 23 近南极 + 剩余星官**，以实际生成为准（约 306，`_meta.json` 写实值）。

**abbr 规则（评审修订，全 ASCII）**：`abbr` 用 pinyin slug 化，**去除非 ASCII**：转小写、括号和空格转单下划线 `_`、去掉声调符号。示例：`柱(毕宿)` → `zhu_bixiu`；`柱(角宿)` → `zhu_jiaoxiu`。`name` 存中文原名，`en` 存英文译名。`validate_atlas.py` 校验 abbr 匹配 `^[a-z0-9_]+$`。

### 1.3 星官连线（中国独有视觉）

- 西方：`lines` = stick-figure（不变）
- 中国：`lines` = 该星官内部连星，来自 `lines.cn`（255 条），但**端点需坐标回填为 star key**（见 §2.4）
- 前端两种模式中西通用，`lines` 语义由 data 决定，**无需新增渲染模式**。单星星官/无连线星官 `lines = []`，前端须正确处理（只画星+标签不画线）。

### 1.4 x/y 投影（评审修订：与 spec v4 完全一致，含 RA wrapping 与自适应 scale）

统一脚本从 RA/Dec 投影生成 `x/y`，投到 `viewBox`。

**投影公式必须与 spec v4 `worldToPixelEquirect`（StarCanvas.vue 已落地）逐字一致**——该函数实测**不含 cos(Dec)**（源码注释明确"cos(Dec) 修正留作 TODO"）。故数据生成端也**不得加 cos**，否则 scan-atlas（读 x/y）与 real-projection（运行时重算 ra/dec）会视觉错位：

```
// RA wrapping：取天球最短弧（跨 0°/360° 不截断）
d_ra = ((ra - center.ra + 180) mod 360) - 180
x = (d_ra + field.width  / 2) / field.width  * viewBox.width
y = (center.dec - dec + field.height / 2) / field.height * viewBox.height
```

- **RA wrapping（评审新增）**：`stars.ra` 与 `center.ra` 均 0..360（§2.2 转换后），直接相减遇跨春分点（`center.ra=1°`、星 `ra=359°`）会得 358° 错投。用 `((Δ+180) mod 360) - 180` 取最短弧，与 spec v4 `normalizeRaDiff` 一致。
- **cos(Dec) 一致性问题（评审 P1，已回退）**：v4 未加 cos，本 spec 也不加。高纬（紫微垣）横向拉伸是 v4 遗留 TODO，第二期做 Stereographic 时 scan-atlas 与 real-projection **同步改**，不在数据端单方面引入。
- **自适应 scale（评审新增）**：三垣 entry 跨度极大（紫微垣覆盖北天极区），固定 `scale` 会超出 viewBox。生成脚本对每个 entry 按成员星 `max(|d_ra|)、max(|d_dec|)` 计算包围盒，动态推导 `scale` 使连线收敛于 viewBox 内。二十八宿/一般星官也可复用同一包围盒逻辑（星少时自然退化为接近固定 scale）。
- 现有 5 星座手绘 x/y 保留，脚本 skip 已有 entry。

### 1.5 `_meta.json` 更新

- `western`：`star_count` 5 → 88；`chinese`：0 → ~306
- **source/license 分 tradition 标注（评审新增）**：`chinese/_meta.json` 的 `source` 写 `celestial_data + 维基百科中西星名对照表`，`license` 写 `CC-BY-SA 4.0 (维基对照表) + 数据集原始许可`。

## 2. 数据来源与采集管道

### 2.1 数据源（已实测 schema）

| 文件 | 实测结构 | 关键字段 |
|---|---|---|
| `constellations.cn.csv` | 312 行 | `id, name(中文星官名), en, pinyin, desig, rank(1宿/2垣/3星官), display_ra, display_dec` |
| `constellations.lines.cn.geojson` | 255 feature | `properties.{id,rank,name,en}` + `geometry.MultiLineString.coordinates` = **端点 `[lon,lat]` 坐标** |
| `starnames.cn.csv` | 3056 行 | `id(HIP), name(中文单星名,如"参宿四"), desig(α Ori/HDxxx/29 Psc), en, pinyin` |
| 西方系列 | 见前版 | `constellations`(89)/`lines`(89)/`bounds`(89)/`borders`(257)/`starnames`(HIP/Bayer/HD) |
| `stars.6/8/14` | POINT | `id, mag, bv, br, name` + geometry 坐标 |
| `assets/星官对应.md` | 维基对照表 | 星官→英文译名 + 宿/垣归属（交叉校验） |

**许可**：开源数据，`_meta.json` 分 tradition 如实标注（见 §1.5）。

### 2.2 RA/Dec 坐标转换

celestial_data 用 GeoJSON 经度 **-180..180**，项目 schema 用 **0..360**：

```
ra_deg = lon if lon >= 0 else lon + 360
```

边界锚点（评审新增，实测确认）：`参宿 display_ra=83.7137`→83.7°；`氐宿 -131.6994`→228.3°；另补 `lon=0`→0、`lon=-0.01`→359.99、`lon=180`→180、`lon=-180`→180 共 4 边界参数化测试。

### 2.3 采集管道

新增 `server/scripts/`：

- `build_full_catalog.py`（西方）：`lines` + `starnames`(HIP) + `stars.*` → 88 entry。`starnames.id`(HIP) join `stars`，生成 `stars`（含 `hip` 可选字段）+ `lines` + 投影 x/y + stories 占位。

- `build_chinese_stars.py`（中国）：
  1. **星官成员星归组（启发式，含前缀边界防冲突）**：用 `starnames.cn.name` 前缀反推，正则加边界字符限制——`^{asterism_name}([一二三四五六七八九十0-9增\s]|$)`，避免短名误吞长名（"角" 误吞"角振"、"天门"误吞"天门增"、"车"误吞"车府"）
  2. **连线端点回填**：`lines.cn` 端点是 `[lon,lat]`，先转 0..360（§2.2），逐端点在星官成员星集内做 Haversine 最近邻（阈值试 0.01°/0.02°/0.05° 三档，原型定最终值）匹配 star key；匹配失败的线段**保留但端点置 `null`**（不静默丢弃），`validate_atlas.py` 拦截并输出未匹配端点清单供人工补全
  3. 生成 `mansion`/`asterism_id` 归属（依 `星官对应.md` 宿/垣归属表 + 近南极 `nanji`）
  4. 三垣 entry 由 6 垣墙合并（§1.2）
  5. 输出 `traditions/chinese/{abbr}.json`

- **保留** `validate_atlas.py` 作唯一真源校验。

### 2.4 关键风险与前置验证（评审确认 + 实测升级）

**最高风险（评审 1.1 升级为根本性问题）**：中国星官命名**并非普遍以星官名作单星前缀**——紫微垣成员叫"北极星/勾陈一/天皇大帝"（与"紫微垣"无前缀关系）；"斗宿"的成员实为"天枢/天璇/天玑/天权"（北斗七星，与"斗宿"无关）。若前缀匹配覆盖率 < 50%，管道将产生大量错误/缺失星官。

**必须的 plan 前置验证（阻塞 gate）**：先对 2-3 个代表性星官（参宿、紫微垣、一个单星/无连线星官、一个近南极星官）统计：
1. **前缀归组覆盖率**：匹配成员星数 vs `星官对应.md` 期望数；是否跨宿污染
2. **连线回填成功率**：0.01°/0.02°/0.05° 三档匹配率 + 失败端点距离分布
3. **坐标一致性抽检**：同一 HIP 在 western/chinese 的 ra/dec/mag 一致（呼应 §3.2）

**否决条件**：若前缀归组覆盖率 < 80%，**立即停止启发式**，改求：
- `星官对应.md` 的结构化版本（需确认是否含星官→单星映射），或
- 引入第三方已结构化的中西星名映射表，或人工补齐映射表

**`validate_atlas.py` 新增硬规则**：
- `lines` 所有 star id 必存在于本 entry `stars`（防 Dangling keys）；`null` 端点记为 hard error 并输出清单
- 单星星官允许 `lines = []`（不报错）
- `mansion`/`asterism_id`：至少一个非 null（近南极用 `asterism_id="nanji"` 满足）

**`_meta.json` 对账**：显式写 `最终 entry 数 = 28 + 3 + 23近南极 + 实际星官数`（评审建议）。

## 3. 后端改动

### 3.1 `find_nearest` 性能与多命中

- 394 entry 全量遍历 O(394) Haversine 无压力。
- 多 tradition 命中（`ori` 与 `参宿` 同天区）已由 `find_nearest` list + `top_k=3` 支持；`routers/identify.py` 保持 `hits[0]` 默认主命中。

### 3.2 `build_star_catalog` 去重升级（必须）

- `round(ra,2)`≈36″ 在 394 entry 数千星下误合并。**改用 HIP 号优先去重**（数据源已带 HIP），fallback `round(ra,3)`≈3.6″。
- **跨 entry 星一致性（评审新增，含 `name_zh`）**：`name_zh` 采用 `starnames.cn` 标准中文星名，**全库唯一**。同一 HIP 号（如参宿四同属 western/ori 与 chinese/参宿）在不同 entry 的 `ra/dec/magnitude/name_zh` 必须一致——测试断言覆盖：
  - 同一 HIP 出现在 western + chinese
  - 同一 HIP 仅出现在一个 tradition
  - 无 HIP 时 fallback `round(ra,3)` 碰撞概率（随机采样验证）

### 3.3 校验脚本扩展

`validate_atlas.py`：
- 中国 entry（`coordinate_system == "mansion"`）`stars` 必含 `name_zh`
- `mansion`/`asterism_id` 至少一个非 null
- abbr 匹配 `^[a-z0-9_]+$`（防括号/中文/URL 编码问题）
- `lines` 无悬空引用（§2.4）

## 4. 前端改动

### 4.1 星官连线渲染（零新增模式）

`StarCanvas` 中西通用；`displayNameFor` 负责中国 entry 用 `name_zh`；空 `lines` 只画星+标签。

### 4.2 列表性能与分组（评审修订）

- 西方 88 项直接渲染。
- 中国 306 项：**本期加原生分组**——按「三垣 + 四象（东方七宿/北方七宿/西方七宿/南方七宿）+ 近南极」用 `<optgroup>` 或 `<details>/<summary>` 折叠，避免 306 个复杂 DOM 节点首屏 Layout 卡顿。虚拟滚动第二期。

## 5. 不在本次范围

- 中国"赤道环/宿度分布"视觉（circular 天图）
- `real-projection` 高赤纬 cos(Dec)（spec v4 TODO，第二期 Stereographic）
- 跨 tradition 命中排序/合并 UI；`find_nearest` 多候选 UI
- `constellations.bounds.cn` 二十八宿边界渲染
- stories epic/chat 精写（独立 backlog；主流程 data 先落）

## 6. 验收标准

| 项 | 预期 |
|---|---|
| `western` star_count | 88 |
| `chinese` star_count | ~306（`_meta.json` 写实值：28+3+23+n） |
| `validate_atlas.py` | 0 hard errors / 0 soft warnings（394 entry，含 lines 悬空引用 + null 端点清单） |
| **前置验证 gate（阻塞）** | 前缀归组覆盖率 ≥ 80%，连线回填成功率达标，否则停止启发式 |
| RA 转换 | `参宿`→83.7°、`氐宿`→228.3° + 4 边界参数化测试 |
| RA wrapping | 跨 0°/360° 星（center.ra=1°、星 ra=359°）正确投到近端 |
| `build_star_catalog` 去重 | HIP 优先，跨 entry 星一致性（含 name_zh）断言通过 |
| 后端 pytest | 新增测试全绿，原 119 不回归 |
| 前端 vitest | 306 分组列表 + 星官连线 + 空 lines 渲染全绿 |
| 分组逻辑 | 三垣/四象/近南极分组由后端 `_meta` 或专门字段提供，前端不硬编码映射 |
| live E2E | 识别 ori 命中 → 3 chip 视图切换正常 |

**测试预估（评审新增）**：RA 转换边界 ~6 + HIP 去重 ~4 + 中国星官专项 ~8 + 跨 entry 一致性 ~3 + 空 lines 渲染 ~2 ≈ 新增 23，总量 ~142（后端）/ ~75（前端）。

## 7. 决策记录

| # | 问题 | 决策 |
|---|---|---|
| 1 | x/y 投影 | 与 spec v4 `worldToPixelEquirect` 逐字一致（不加 cos，RA wrapping + 自适应 scale） |
| 2 | entry 粒度 | 按星官约 306（28宿+3垣+23近南极+星官；6 垣墙合并成三垣） |
| 3 | 数据源 | celestial_data（RA/Dec+连线+HIP 一站式） |
| 4 | stories | 全量手写，分批回填，不阻塞 pipeline |
| 5 | abbr | pinyin slug 全 ASCII `^[a-z0-9_]+$` |
| 6 | 连线拓扑 | lines.cn 坐标回填 star key，null 端点不静默丢弃 |
| 7 | 近南极 | `asterism_id="nanji"` 伪垣，不改校验规则 |
| 8 | 投影 cos | 回退（v4 未加，避免 scan-atlas/real-projection 错位） |

**plan 阶段第一步（阻塞性前置验证）**：跑 `build_chinese_stars.py` 最小原型（参宿 + 紫微垣 + 1 单星星官 + 1 近南极星官），量化前缀归组覆盖率与连线回填匹配率。**覆盖率 < 80% 即否决启发式方案**，改引入结构化映射表或人工补齐。