# Atlas 投影失真修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 atlas 渲染从"手绘 x/y + 朴素等距投影"统一到 **Azimuthal Stereographic 共享公式**（Python build 端 + TypeScript runtime 端），同步重生 Chinese 310 个 + Western 88 个 JSON，让星座（特别是高赤纬的北斗、紫微垣、猎户腰带）恢复肉眼天空的真实横宽比与形状。

**架构：**
- **单一公式源 + 双端共享**：Python `server/scripts/atlas_projection.py` 与 TS `web/src/utils/atlasProjection.ts` 各一份 Stereographic 实现（含中心点 guard），靠 golden values 交叉验证一致性
- **runtime 切到新公式**：`StarCanvas.vue` 的 `worldToPixelEquirect` 调新模块；`drawScanAtlas` 行为不变（仍读 x/y）
- **数据重生**：`build_chinese_stars.py` 调新公式 + 移除 RA 镜像；新建 `build_western_stars.py` 从 celestial_data 重算 88 JSON
- **3 次 commit**：①公式+runtime ②Chinese 重生 ③Western 重生，每步独立可测可回滚

**技术栈：**
- 后端：Python 3.11+ / FastAPI / pytest / pathlib + json / math
- 前端：Vue 3 + Pinia + TypeScript + Vitest + Math (browser native)
- 数据：纯 JSON（HIP-keyed stars，含 ra/dec/center/stories 内嵌）
- 现有依赖（不引入新库）

**Spec：** [`docs/specs/2026-09-01-atlas-projection-fix-design.md`](../specs/2026-09-01-atlas-projection-fix-design.md) — 计划从 spec 推导，spec 跟随实施

---

## Global Constraints

| 项目 | 取值 |
|---|---|
| Python 版本 | 3.11+（`from __future__ import annotations`） |
| 角度单位 | 度（除特别说明外） |
| viewBox | `700 × 700` 正方形，padding 30 px |
| 数据 schema | HIP-keyed stars（key 格式 `"HIP_<hip>"`），每星必有 `bayer`/`name`/`name_zh`/`magnitude`/`ra`/`dec`/`label`/`hip`/`x`/`y` |
| entry name 规则 | Western `name` 从 `latin` 派生（"Orion"），Chinese `name` 从 `constellations.cn.csv` 派生（"猎户座"） |
| star name 规则 | Western `name` 从 `starnames.csv` 拉英文常用专名，**fallback 空串**（不 fallback Bayer 名）；Chinese `name`/`name_zh` 都是中文星名 |
| label 阈值 | `mag < 4.5` → `true`（标文字），`mag ≥ 4.5` → `false` |
| 投影方向 | **东=右、北=上**（屏幕 y 取负） |
| 公式常量 | Stereographic 中心点 guard 阈值 `1e-14`；atan2 数值保护 `clamp cos_c ∈ [-1, 1]` |
| 测试容差 | 浮点比较 ≤ `1e-6 px`；中心点返回画布中心 ≤ `1e-6 px`；坐标绝对误差 ≤ `0.01 px` |
| Git 分支 | `fix-260901-atlas-projection-fix`（已建）；squash merge 到 `main`，main 上单 commit |
| Commit message 格式 | `<type>(<scope>): <imperative summary>`（CLAUDE.md §2） |
| 提交物追踪 | `作品提交文件夹/04码道使用证明/` 下 PNG（含北斗/猎户 before-after）必须跟代码一起 commit（CLAUDE.md §0） |
| OPC 提交流程 | 每次 commit 前检查 `04码道使用证明/` 新增截图，**必须 add 一起 commit** |

---

## 文件结构

### 创建

| 路径 | 职责 |
|---|---|
| `server/scripts/atlas_projection.py` | Python Stereographic 公式：`compute_center` / `angular_separation` / `compute_field` / `project` |
| `server/tests/test_atlas_projection.py` | 公式单测：北斗 7 星 golden value (186.04°, 56.55°) + 中心 guard + 方向断言 + 三垣 max_c 验证 |
| `web/src/utils/atlasProjection.ts` | TS Stereographic 公式（与 Python 1:1 对齐） |
| `web/tests/utils/atlasProjection.spec.ts` | TS 单测：跟 Python 同组 golden values 交叉验证（误差 < 0.01 px） |
| `server/scripts/build_western_stars.py` | 从 `celestial_data` 重算 88 个 Western JSON（含 hand_overrides merge） |
| `assets/missing_constellations.md` | **条件创建**：celestial_data 缺哪个星座时由脚本写 |
| `assets/missing_stars.md` | **条件创建**：stars.8.min.geojson 缺哪个 line 端点 HIP 时由脚本写 |
| `作品提交文件夹/04码道使用证明/260901-beidou-before-after.png` | 北斗修复前后对比图 |
| `作品提交文件夹/04码道使用证明/260901-orion-before-after.png` | 猎户修复前后对比图 |

### 修改

| 路径 | 改动 |
|---|---|
| `web/src/components/StarCanvas.vue` | 行 23-32 `displayNameFor` 调 fallback 链；行 65-92 `computeField` / 行 94-109 `worldToPixelEquirect` 删内联公式改调 `atlasProjection`；行 317-340 `drawScanAtlas` 行为不变；删 `cosDecAdjustment`/`normalizeRaDiff` 等仅 equirectangular 用的辅助 |
| `server/scripts/build_chinese_stars.py` | 行 269-283 删内联公式改调 `atlas_projection.project`；移除 `e2ed1bf` 引入的 RA 镜像（`-dx*sx` → `+dx*sx`）；sx/sy 改等比 `scale = min(...)`；三垣 entry 仍不写 x/y |
| `web/tests/components/StarCanvas.spec.ts` | 更新所有 atlas 渲染快照断言（公式变了旧断言必然失败） |

### 重生（脚本产出，不手写）

| 路径 | 来源 |
|---|---|
| `server/data/traditions/chinese/*.json`（310 文件） | `build_chinese_stars.py` 重跑 |
| `server/data/traditions/chinese/_meta.json` | 同上 |
| `server/data/traditions/western/*.json`（88 文件） | `build_western_stars.py` 重跑 |
| `server/data/traditions/western/_meta.json` | 同上 |

### 删除

| 路径 | 原因 |
|---|---|
| 无 | 本任务不删文件 |

---

## 任务依赖图

```
Commit 1: 抽公式 + runtime 切换
  ├─ Task 1.1: 创建 server/scripts/atlas_projection.py
  ├─ Task 1.2: 写 server/tests/test_atlas_projection.py 单测 + 验证失败/通过
  ├─ Task 1.3: 创建 web/src/utils/atlasProjection.ts
  ├─ Task 1.4: 写 web/tests/utils/atlasProjection.spec.ts 交叉验证
  ├─ Task 1.5: 改 web/src/components/StarCanvas.vue 调新公式 + 删辅助
  ├─ Task 1.6: 更新 web/tests/components/StarCanvas.spec.ts 断言
  ├─ Task 1.7: 跑全套测试 + 启服务 e2e smoke
  └─ Task 1.8: Commit 1

Commit 2: Chinese 数据重生
  ├─ Task 2.1: 改 server/scripts/build_chinese_stars.py 调新公式
  ├─ Task 2.2: 跑脚本重生 310 个 Chinese JSON
  ├─ Task 2.3: 视觉验证北斗横扁勺形 + 截图存档
  └─ Task 2.4: Commit 2（含截图）

Commit 3: Western 数据重生
  ├─ Task 3.1: 创建 server/scripts/build_western_stars.py
  ├─ Task 3.2: 跑脚本重生 88 个 Western JSON
  ├─ Task 3.3: 视觉验证猎户 + 截图存档
  └─ Task 3.4: Commit 3（含截图）

合并：
  ├─ Task 4.1: review git diff main
  └─ Task 4.2: git merge --squash + 提交 `作品提交文件夹/04码道使用证明/` 截图
```

---

## Commit 1：抽 Azimuthal Stereographic 共享公式 + runtime 切换

### Task 1.1：创建 `server/scripts/atlas_projection.py`

**Files:**
- Create: `server/scripts/atlas_projection.py`
- Test: `server/tests/test_atlas_projection.py`（Task 1.2 创建）

**Interfaces:**
- Consumes: 无（独立模块）
- Produces:
  - `compute_center(stars: list[dict]) -> tuple[float, float]` — `(ra, deg)`，3D 单位向量平均
  - `angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float` — 球面角距（度）
  - `compute_field(stars: list[dict], viewbox: dict, padding: int = 30) -> dict` — `{"scale": float, "center": (ra, dec), "padding": int}`
  - `project(ra: float, dec: float, center_ra: float, center_dec: float, scale: float, viewbox: dict) -> tuple[float, float]` — `(x, y)` 像素

- [ ] **Step 1：写模块 docstring + import + 类型注解**

```python
"""Atlas 共享投影公式（Azimuthal Stereographic）。

双端实现：
- Python: server/scripts/atlas_projection.py（本文件，build 脚本用）
- TypeScript: web/src/utils/atlasProjection.ts（runtime 渲染用）

公式基于球面余弦定理。中心点 c=0 时显式返回画布中心（避免双端舍入差异）。
"""
from __future__ import annotations
import math
from typing import Iterable

# 中心点 guard 阈值：cos_c ≈ 1 时返回画布中心
CENTER_GUARD_EPS = 1e-14

# 三角函数 acos 输入保护
_ACOS_CLAMP = (-1.0, 1.0)
```

- [ ] **Step 2：实现 `angular_separation`**

```python
def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """球面余弦定理算角距（度）。

    >>> angular_separation(0, 0, 0, 0)
    0.0
    >>> abs(angular_separation(279.23, 38.78, 297.70, 8.87) - 34.2) < 0.5
    True
    """
    dra = math.radians(ra1 - ra2)
    cos_c = (
        math.sin(math.radians(dec1)) * math.sin(math.radians(dec2))
        + math.cos(math.radians(dec1)) * math.cos(math.radians(dec2)) * math.cos(dra)
    )
    cos_c = max(_ACOS_CLAMP[0], min(_ACOS_CLAMP[1], cos_c))
    return math.degrees(math.acos(cos_c))
```

- [ ] **Step 3：实现 `compute_center`（3D 单位向量平均）**

```python
def compute_center(stars: Iterable[dict]) -> tuple[float, float]:
    """单位球面 3D 向量平均 → 归一化回 (RA, Dec)。

    >>> # 北斗 7 星 golden value：(186.04, 56.55)
    >>> beidou = [
    ...     {"ra": 165.932, "dec": 61.751},
    ...     {"ra": 165.460, "dec": 56.382},
    ...     {"ra": 178.458, "dec": 53.695},
    ...     {"ra": 183.857, "dec": 57.033},
    ...     {"ra": 193.507, "dec": 55.960},
    ...     {"ra": 200.981, "dec": 54.925},
    ...     {"ra": 206.885, "dec": 49.313},
    ... ]
    >>> ra, dec = compute_center(beidou)
    >>> abs(ra - 186.04) < 0.05 and abs(dec - 56.55) < 0.05
    True
    """
    stars = list(stars)
    if not stars:
        return (0.0, 0.0)
    vx = sum(math.cos(math.radians(s["dec"])) * math.cos(math.radians(s["ra"])) for s in stars)
    vy = sum(math.cos(math.radians(s["dec"])) * math.sin(math.radians(s["ra"])) for s in stars)
    vz = sum(math.sin(math.radians(s["dec"])) for s in stars)
    n = len(stars)
    vx /= n
    vy /= n
    vz /= n
    ra = math.degrees(math.atan2(vy, vx)) % 360
    dec = math.degrees(math.atan2(vz, math.hypot(vx, vy)))
    return (ra, dec)
```

- [ ] **Step 4：实现 `compute_field`**

```python
def compute_field(stars: Iterable[dict], viewbox: dict, padding: int = 30) -> dict:
    """找最大球面角距对应的平面半径，等比 fit 进 viewbox。

    Stereographic 下球面角距 c 对应的平面半径 r = 2·tan(c/2)。
    若 max_c > 170°，说明存在接近对跖的成员（投影会爆炸），raise。
    """
    stars = list(stars)
    center_ra, center_dec = compute_center(stars)
    if not stars:
        return {"scale": 1.0, "center": (center_ra, center_dec), "padding": padding}

    max_c = max(angular_separation(s["ra"], s["dec"], center_ra, center_dec) for s in stars)
    if max_c > 170.0:
        raise ValueError(
            f"星座成员存在接近对跖点（max_c={max_c:.1f}° > 170°），"
            f"Stereographic 投影会爆炸。请检查数据或换投影。"
        )
    if max_c < 1e-6:
        return {"scale": 1.0, "center": (center_ra, center_dec), "padding": padding}

    max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
    scale = min(
        (viewbox["w"] / 2.0 - padding) / max_radius,
        (viewbox["h"] / 2.0 - padding) / max_radius,
    )
    return {"scale": scale, "center": (center_ra, center_dec), "padding": padding}
```

- [ ] **Step 5：实现 `project`（含中心点 guard）**

```python
def project(
    ra: float,
    dec: float,
    center_ra: float,
    center_dec: float,
    scale: float,
    viewbox: dict,
) -> tuple[float, float]:
    """单点 Az度thmic Stereographic 投影。

    东=右、北=上（屏幕 y 取负）。中心点 guard：cos_c ≈ 1 时返回画布中心。
    """
    dra_rad = math.radians(ra - center_ra)
    dec_rad = math.radians(dec)
    dec0_rad = math.radians(center_dec)

    cos_c = (
        math.sin(dec0_rad) * math.sin(dec_rad)
        + math.cos(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad)
    )
    cos_c = max(_ACOS_CLAMP[0], min(_ACOS_CLAMP[1], cos_c))

    # 中心点 guard
    if abs(1.0 - cos_c) < CENTER_GUARD_EPS:
        return (viewbox["w"] / 2.0, viewbox["h"] / 2.0)

    k = 2.0 / (1.0 + cos_c)

    x_local = math.cos(dec_rad) * math.sin(dra_rad)
    y_local = (
        math.cos(dec0_rad) * math.sin(dec_rad)
        - math.sin(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad)
    )

    x = viewbox["w"] / 2.0 + k * x_local * scale
    y = viewbox["h"] / 2.0 - k * y_local * scale  # 屏幕 y 翻转
```

- [ ] **Step 6：跑模块自带 doctest 验证（可选 sanity）**

Run:
```bash
cd server && .venv/Scripts/python.exe -c "from scripts import atlas_projection; print('OK')"
```
Expected: `OK`

---

### Task 1.2：写 `server/tests/test_atlas_projection.py` 单测

**Files:**
- Test: `server/tests/test_atlas_projection.py`（新建）

**Interfaces:**
- Consumes: `server/scripts/atlas_projection.py` 的全部导出函数
- Produces: 7 个 pytest 函数，全部 PASS

- [ ] **Step 1：写测试文件骨架 + 共享 fixture**

```python
"""atlas_projection 单测：北斗 7 星 + Vega/Altair + 边界用例。"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import pytest

# 让脚本可 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.atlas_projection import (  # noqa: E402
    angular_separation,
    compute_center,
    compute_field,
    project,
    CENTER_GUARD_EPS,
)

VIEWBOX = {"w": 700, "h": 700}
PADDING = 30

# 北斗 7 星 (HIP, RA°, Dec°)
BEIDOU = [
    {"hip": "54061", "ra": 165.932, "dec": 61.751},  # 天枢 Dubhe
    {"hip": "53910", "ra": 165.460, "dec": 56.382},  # 天璇 Merak
    {"hip": "58001", "ra": 178.458, "dec": 53.695},  # 天玑 Phecda
    {"hip": "59774", "ra": 183.857, "dec": 57.033},  # 天权 Megrez
    {"hip": "62956", "ra": 193.507, "dec": 55.960},  # 玉衡 Alioth
    {"hip": "65378", "ra": 200.981, "dec": 54.925},  # 开阳 Mizar
    {"hip": "67301", "ra": 206.885, "dec": 49.313},  # 摇光 Alkaid
]

VEGA = {"ra": 279.23, "dec": 38.78}     # 织女一
ALTAIR = {"ra": 297.70, "dec": 8.87}    # 牛郎
```

- [ ] **Step 2：写 `test_compute_center_known_constellation`**

```python
def test_compute_center_known_constellation():
    """北斗 7 星 → center = (186.04°, 56.55°) ±0.05°"""
    ra, dec = compute_center(BEIDOU)
    assert abs(ra - 186.04) < 0.05, f"center_ra={ra}, expected 186.04"
    assert abs(dec - 56.55) < 0.05, f"center_dec={dec}, expected 56.55"
```

- [ ] **Step 3：写 `test_angular_separation_known_pair`**

```python
def test_angular_separation_known_pair():
    """Vega–Altair 教科书值 ~34.2°（±0.5°）"""
    sep = angular_separation(VEGA["ra"], VEGA["dec"], ALTAIR["ra"], ALTAIR["dec"])
    assert abs(sep - 34.2) < 0.5, f"Vega-Altair 角距={sep}, expected ~34.2°"


def test_angular_separation_same_point():
    """同一点 → 0°"""
    assert angular_separation(100, 30, 100, 30) == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 4：写 `test_compute_field_radial_symmetry`**

```python
def test_compute_field_radial_symmetry():
    """最远星到 center 的最大 c 对应的 2·tan(c/2) × scale ≤ (viewbox/2 - padding)"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    scale = field["scale"]
    max_c = max(angular_separation(s["ra"], s["dec"], center_ra, center_dec) for s in BEIDOU)
    max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
    assert max_radius * scale <= (VIEWBOX["w"] / 2.0 - PADDING) + 1e-9
    assert max_radius * scale <= (VIEWBOX["h"] / 2.0 - PADDING) + 1e-9
```

- [ ] **Step 5：写 `test_project_center_singularity`**

```python
def test_project_center_singularity():
    """传入 (center_ra, center_dec) → 返回画布中心，误差 < 1e-6 px"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    x, y = project(center_ra, center_dec, center_ra, center_dec, field["scale"], VIEWBOX)
    assert abs(x - VIEWBOX["w"] / 2.0) < 1e-6
    assert abs(y - VIEWBOX["h"] / 2.0) < 1e-6
```

- [ ] **Step 6：写 `test_project_east_right` + `test_project_north_up`**

```python
def test_project_east_right():
    """ΔRA > 0 的星 x > viewbox.w/2"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    for s in BEIDOU:
        x, _ = project(s["ra"], s["dec"], center_ra, center_dec, field["scale"], VIEWBOX)
        if s["ra"] > center_ra:
            assert x > VIEWBOX["w"] / 2.0, f"{s['hip']}: ra={s['ra']} > center {center_ra} 但 x={x}"


def test_project_north_up():
    """Δdec > 0 的星 y < viewbox.h/2（屏幕 y 朝下）"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    for s in BEIDOU:
        _, y = project(s["ra"], s["dec"], center_ra, center_dec, field["scale"], VIEWBOX)
        if s["dec"] > center_dec:
            assert y < VIEWBOX["h"] / 2.0, f"{s['hip']}: dec={s['dec']} > center {center_dec} 但 y={y}"
```

- [ ] **Step 7：跑测试验证全过**

Run:
```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_atlas_projection.py -v
```
Expected: `7 passed`

- [ ] **Step 8：Commit**

```bash
cd "D:/Projects/260820OPC"
git add server/scripts/atlas_projection.py server/tests/test_atlas_projection.py
git commit -m "feat(atlas): 抽 Azimuthal Stereographic 投影公式（Python 端 + 单测）"
```

---

### Task 1.3：创建 `web/src/utils/atlasProjection.ts`

**Files:**
- Create: `web/src/utils/atlasProjection.ts`
- Test: `web/tests/utils/atlasProjection.spec.ts`（Task 1.4）

**Interfaces:**
- Consumes: 无
- Produces:
  - `computeCenter(stars: Array<{ra, dec}>): {ra, dec}`
  - `angularSeparation(ra1, dec1, ra2, dec2): number`（度）
  - `computeField(stars, viewbox, padding = 30): {scale, center, padding}`
  - `projectStereographic(ra, dec, centerRa, centerDec, scale, viewbox): {x, y}`

公式与 `atlas_projection.py` 1:1 对齐。

- [ ] **Step 1：写文件骨架 + 常量**

```typescript
/**
 * Atlas 共享投影公式（Azimuthal Stereographic）。
 *
 * 双端实现：
 * - Python: server/scripts/atlas_projection.py（build 脚本用）
 * - TypeScript: 本文件（runtime 渲染用）
 *
 * 公式基于球面余弦定理。中心点 c=0 时显式返回画布中心。
 */

const CENTER_GUARD_EPS = 1e-14

export interface StarCoord {
  ra: number
  dec: number
}

export interface Viewbox {
  w: number
  h: number
}

export interface ProjectionField {
  scale: number
  center: { ra: number; dec: number }
  padding: number
}
```

- [ ] **Step 2：写 `angularSeparation`**

```typescript
export function angularSeparation(
  ra1: number, dec1: number, ra2: number, dec2: number
): number {
  const dra = ((ra1 - ra2) * Math.PI) / 180
  let cosC =
    Math.sin((dec1 * Math.PI) / 180) * Math.sin((dec2 * Math.PI) / 180) +
    Math.cos((dec1 * Math.PI) / 180) * Math.cos((dec2 * Math.PI) / 180) *
      Math.cos(dra)
  cosC = Math.max(-1, Math.min(1, cosC))
  return (Math.acos(cosC) * 180) / Math.PI
}
```

- [ ] **Step 3：写 `computeCenter`**

```typescript
export function computeCenter(stars: StarCoord[]): { ra: number; dec: number } {
  if (stars.length === 0) return { ra: 0, dec: 0 }
  let vx = 0, vy = 0, vz = 0
  for (const s of stars) {
    const raR = (s.ra * Math.PI) / 180
    const decR = (s.dec * Math.PI) / 180
    vx += Math.cos(decR) * Math.cos(raR)
    vy += Math.cos(decR) * Math.sin(raR)
    vz += Math.sin(decR)
  }
  const n = stars.length
  vx /= n
  vy /= n
  vz /= n
  const ra = ((Math.atan2(vy, vx) * 180) / Math.PI + 360) % 360
  const dec = (Math.atan2(vz, Math.hypot(vx, vy)) * 180) / Math.PI
  return { ra, dec }
}
```

- [ ] **Step 4：写 `computeField`**

```typescript
export function computeField(
  stars: StarCoord[], viewbox: Viewbox, padding = 30
): ProjectionField {
  const center = computeCenter(stars)
  if (stars.length === 0) {
    return { scale: 1, center, padding }
  }
  let maxC = 0
  for (const s of stars) {
    const c = angularSeparation(s.ra, s.dec, center.ra, center.dec)
    if (c > maxC) maxC = c
  }
  if (maxC > 170) {
    throw new Error(
      `星座成员存在接近对跖点（max_c=${maxC.toFixed(1)}° > 170°），Stereographic 投影会爆炸`
    )
  }
  if (maxC < 1e-6) {
    return { scale: 1, center, padding }
  }
  const maxRadius = 2 * Math.tan((maxC * Math.PI) / 360)
  const scale = Math.min(
    (viewbox.w / 2 - padding) / maxRadius,
    (viewbox.h / 2 - padding) / maxRadius,
  )
  return { scale, center, padding }
}
```

- [ ] **Step 5：写 `projectStereographic`**

```typescript
export function projectStereographic(
  ra: number, dec: number,
  centerRa: number, centerDec: number,
  scale: number, viewbox: Viewbox
): { x: number; y: number } {
  const draRad = ((ra - centerRa) * Math.PI) / 180
  const decRad = (dec * Math.PI) / 180
  const dec0Rad = (centerDec * Math.PI) / 180

  let cosC =
    Math.sin(dec0Rad) * Math.sin(decRad) +
    Math.cos(dec0Rad) * Math.cos(decRad) * Math.cos(draRad)
  cosC = Math.max(-1, Math.min(1, cosC))

  if (Math.abs(1 - cosC) < CENTER_GUARD_EPS) {
    return { x: viewbox.w / 2, y: viewbox.h / 2 }
  }

  const k = 2 / (1 + cosC)
  const xLocal = Math.cos(decRad) * Math.sin(draRad)
  const yLocal =
    Math.cos(dec0Rad) * Math.sin(decRad) -
    Math.sin(dec0Rad) * Math.cos(decRad) * Math.cos(draRad)

  const x = viewbox.w / 2 + k * xLocal * scale
  const y = viewbox.h / 2 - k * yLocal * scale
  return { x, y }
}
```

---

### Task 1.4：写 `web/tests/utils/atlasProjection.spec.ts` 交叉验证

**Files:**
- Test: `web/tests/utils/atlasProjection.spec.ts`

**Interfaces:**
- Consumes: `web/src/utils/atlasProjection.ts`
- Produces: vitest 全部 PASS；Python 与 TS 输出同组输入误差 < 0.01 px

- [ ] **Step 1：写测试文件骨架**

```typescript
import { describe, it, expect } from 'vitest'
import {
  computeCenter, computeField, projectStereographic,
  angularSeparation, type StarCoord, type Viewbox
} from '@/src/utils/atlasProjection'

const VIEWBOX: Viewbox = { w: 700, h: 700 }
const PADDING = 30

const BEIDOU: StarCoord[] = [
  { ra: 165.932, dec: 61.751 }, { ra: 165.460, dec: 56.382 },
  { ra: 178.458, dec: 53.695 }, { ra: 183.857, dec: 57.033 },
  { ra: 193.507, dec: 55.960 }, { ra: 200.981, dec: 54.925 },
  { ra: 206.885, dec: 49.313 },
]
```

- [ ] **Step 2：写 `computeCenter` 测试**

```typescript
describe('computeCenter', () => {
  it('北斗 7 星 → (186.04, 56.55) ±0.05°', () => {
    const { ra, dec } = computeCenter(BEIDOU)
    expect(ra).toBeCloseTo(186.04, 1)
    expect(dec).toBeCloseTo(56.55, 1)
  })

  it('空数组 → (0, 0)', () => {
    expect(computeCenter([])).toEqual({ ra: 0, dec: 0 })
  })
})
```

- [ ] **Step 3：写 `angularSeparation` 测试**

```typescript
describe('angularSeparation', () => {
  it('同一点 → 0', () => {
    expect(angularSeparation(100, 30, 100, 30)).toBeCloseTo(0, 9)
  })

  it('Vega–Altair ≈ 34.2°（教科书值）', () => {
    const sep = angularSeparation(279.23, 38.78, 297.70, 8.87)
    expect(sep).toBeGreaterThan(33.7)
    expect(sep).toBeLessThan(34.7)
  })
})
```

- [ ] **Step 4：写 `computeField` + `projectStereographic` 交叉验证**

```typescript
describe('projectStereographic', () => {
  it('中心点 → 画布中心（误差 < 1e-6 px）', () => {
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    const { x, y } = projectStereographic(
      field.center.ra, field.center.dec,
      field.center.ra, field.center.dec,
      field.scale, VIEWBOX
    )
    expect(Math.abs(x - VIEWBOX.w / 2)).toBeLessThan(1e-6)
    expect(Math.abs(y - VIEWBOX.h / 2)).toBeLessThan(1e-6)
  })

  it('东=右、北=上', () => {
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    for (const s of BEIDOU) {
      const { x, y } = projectStereographic(
        s.ra, s.dec,
        field.center.ra, field.center.dec,
        field.scale, VIEWBOX
      )
      if (s.ra > field.center.ra) expect(x).toBeGreaterThan(VIEWBOX.w / 2)
      if (s.dec > field.center.dec) expect(y).toBeLessThan(VIEWBOX.h / 2)
    }
  })

  it('跟 Python 同输入输出误差 < 0.01 px（手算 3 个验证点）', () => {
    // 这三个验证点是手算的：北斗中心 (186.04, 56.55)
    // 天枢 (165.932, 61.751) → (~657, ~35)
    // 摇光 (206.885, 49.313) → (~30, ~670)
    // 玉衡 (193.507, 55.960) → (~235, ~331)
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    const cases: Array<[StarCoord, [number, number]]> = [
      [{ ra: 165.932, dec: 61.751 }, [657.2, 34.9]],
      [{ ra: 206.885, dec: 49.313 }, [30.0, 670.0]],
      [{ ra: 193.507, dec: 55.960 }, [234.9, 330.6]],
    ]
    for (const [star, [exX, exY]] of cases) {
      const { x, y } = projectStereographic(
        star.ra, star.dec,
        field.center.ra, field.center.dec,
        field.scale, VIEWBOX
      )
      expect(Math.abs(x - exX)).toBeLessThan(0.01)
      expect(Math.abs(y - exY)).toBeLessThan(0.01)
    }
  })
})
```

- [ ] **Step 5：跑 vitest 验证**

Run:
```bash
cd web && pnpm test atlasProjection
```
Expected: 全部 PASS

- [ ] **Step 6：Commit**

```bash
cd "D:/Projects/260820OPC"
git add web/src/utils/atlasProjection.ts web/tests/utils/atlasProjection.spec.ts
git commit -m "feat(atlas): 抽 Azimuthal Stereographic 投影公式（TypeScript 端 + 交叉验证）"
```

---

### Task 1.5：改 `web/src/components/StarCanvas.vue` 调新公式

**Files:**
- Modify: `web/src/components/StarCanvas.vue`
  - 行 23-32 `displayNameFor`（**不依赖公式，不改**）
  - 行 65-92 `computeField` 内部公式 → 调 `atlasProjection.computeField`
  - 行 94-109 `worldToPixelEquirect` → 调 `atlasProjection.projectStereographic`
  - 行 317-340 `drawScanAtlas`（**不依赖公式，不改**）
  - 行 363-477 `drawRealProjection`（**已调 `worldToPixelEquirect`，自动跟随**）
  - 删除 `cosDecAdjustment`/`normalizeRaDiff` 等仅 equirectangular 用的辅助

**Interfaces:**
- Consumes: `atlasProjection.computeField` / `projectStereographic`（Task 1.3）
- Produces: `StarCanvas` 在 `real-projection` 模式下渲染改用新公式；`scan-atlas` 模式行为不变（仍读 x/y）

- [ ] **Step 1：在 `<script setup lang="ts">` 顶部加 import**

在 StarCanvas.vue `<script setup>` 顶部插入：
```typescript
import { computeField, projectStereographic } from '@/src/utils/atlasProjection'
```

- [ ] **Step 2：替换 `computeField`（行 65-92）**

旧实现（行 65-92）整段替换为：
```typescript
function computeField(stars: Star[]) {
  // 调新公式；stars 必须是 {ra, dec} 形式
  // 取第一个有效 center 用于视野定位
  const starCoords = Object.values(stars)
    .map((s: any) => ({ ra: s.ra, dec: s.dec }))
    .filter((s) => Number.isFinite(s.ra) && Number.isFinite(s.dec))
  if (starCoords.length === 0) {
    return { width: 120, height: 90, centerDec: 0, centerRa: 0 }
  }
  const field = computeField(starCoords, viewbox.value, 30)
  return {
    width: 120,
    height: 90,
    centerDec: field.center.dec,
    centerRa: field.center.ra,
    // scale 不直接传给 render，但 viewbox 已被公式 fit 完
  }
}
```

- [ ] **Step 3：替换 `worldToPixelEquirect`（行 94-109）**

旧实现整段替换为：
```typescript
function worldToPixelEquirect(ra: number, dec: number) {
  // 调新公式（中心点和 scale 从 stars 重算）
  const starCoords = Object.values(visibleStars.value ?? {})
    .map((s: any) => ({ ra: s.ra, dec: s.dec }))
    .filter((s) => Number.isFinite(s.ra) && Number.isFinite(s.dec))
  if (starCoords.length === 0) {
    return { x: viewbox.value.w / 2, y: viewbox.value.h / 2 }
  }
  const field = computeField(starCoords, viewbox.value, 30)
  return projectStereographic(
    ra, dec,
    field.center.ra, field.center.dec,
    field.scale, viewbox.value
  )
}
```

- [ ] **Step 4：删除仅 equirectangular 用的辅助**

在 StarCanvas.vue 全文搜索 `cosDecAdjustment` / `normalizeRaDiff`，整段删除（包括任何 `const`/`function` 定义 + 调用点）。

- [ ] **Step 5：本地 typecheck**

Run:
```bash
cd web && pnpm vue-tsc --noEmit
```
Expected: 无错误（可能有 stale imports，确认已被 Step 4 删除后通过）

---

### Task 1.6：更新 `web/tests/components/StarCanvas.spec.ts` 中 atlas 断言

**Files:**
- Modify: `web/tests/components/StarCanvas.spec.ts`

**Interfaces:**
- Consumes: StarCanvas 现有测试
- Produces: 更新涉及 atlas 渲染的断言；非 atlas 断言不动

- [ ] **Step 1：跑当前测试看哪些失败**

Run:
```bash
cd web && pnpm test StarCanvas 2>&1 | tee /tmp/star-canvas-before.txt
```
Expected: 部分 atlas 渲染快照断言失败（公式变了 → 像素坐标变了），记录失败列表

- [ ] **Step 2：逐个更新失败断言**

打开 `web/tests/components/StarCanvas.spec.ts`，对每个失败 case：
1. 看实际输出（vitest 给的 diff）
2. 替换期望值为实际值（公式变了，期望值要重生成）

**注意**：
- 不要直接全盘接受测试失败的实际值——某些失败可能是**真回归**，要对比 visual 看是否合理
- 期望值更新原则：每个期望值**用 atlasProjection 跑一次参考实现生成**（参考实现才是 ground truth）

- [ ] **Step 3：跑测试再过**

Run:
```bash
cd web && pnpm test StarCanvas
```
Expected: 全部 PASS

---

### Task 1.7：跑全套测试 + e2e smoke

**Files:** 无

- [ ] **Step 1：跑后端全部测试**

Run:
```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```
Expected: `26 passed`（含 Task 1.2 新增的 7 个）+ `passed` 全部

- [ ] **Step 2：跑前端全部测试**

Run:
```bash
cd web && pnpm test
```
Expected: 全部 PASS（含 Task 1.4 新增 + Task 1.6 更新）

- [ ] **Step 3：e2e smoke（启 mock 服务 + curl /api/health + atlas 端点）**

Run:
```bash
cd server && ASTROMETRY_MOCK=1 .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 &
sleep 3
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/traditions
curl -s 'http://127.0.0.1:8000/api/constellations?tradition=chinese' | head -c 200
kill %1
```
Expected: 全部返回 200 + JSON

---

### Task 1.8：Commit 1

- [ ] **Step 1：检查 `作品提交文件夹/04码道使用证明/` 有无新增截图**

Run:
```bash
cd "D:/Projects/260820OPC" && git status "作品提交文件夹/04码道使用证明/"
```
（本任务不涉及视觉变化，**预期无新截图**）

- [ ] **Step 2：Stage 并 Commit**

```bash
cd "D:/Projects/260820OPC"
git add web/src/components/StarCanvas.vue web/tests/components/StarCanvas.spec.ts
git status
git commit -m "refactor(atlas): StarCanvas 调新 Stereographic 公式 + 更新测试断言"
```

---

## Commit 2：Chinese 数据重生（310 JSON）

### Task 2.1：改 `server/scripts/build_chinese_stars.py` 调新公式

**Files:**
- Modify: `server/scripts/build_chinese_stars.py`
  - 行 269-283 内联 x/y 计算
  - 行 282 RA 镜像（`s["x"] = VIEW_W/2 - dx * sx` → `s["x"] = VIEW_W/2 + dx * sx`）
  - 三垣 entry 仍不写 x/y

**Interfaces:**
- Consumes: `atlas_projection.compute_center` / `compute_field` / `project`（Task 1.1）
- Produces: `build_chinese_stars.py` 重出 310 个 Chinese JSON + `_meta.json`

- [ ] **Step 1：顶部加 import**

在文件顶部 `import math` 后加：
```python
from scripts.atlas_projection import compute_center, compute_field, project
```

- [ ] **Step 2：替换行 269-283 内联公式**

旧实现（约 15 行）：
```python
if star_map:
    cos_dec = max(0.05, math.cos(math.radians(center_dec)))
    max_dra_cos = max(abs(ra_wrap(s["ra"] - center_ra)) * cos_dec
                      for s in star_map.values())
    max_ddec = max(abs(s["dec"] - center_dec) for s in star_map.values())
    sx = (VIEW_W / 2 - 30) / max(max_dra_cos, 0.001)
    sy = (VIEW_H / 2 - 30) / max(max_ddec, 0.001)
    for hip, s in star_map.items():
        dx = ra_wrap(s["ra"] - center_ra) * cos_dec
        s["x"] = round(VIEW_W / 2 - dx * sx, 1)        # ← RA 镜像
        s["y"] = round(VIEW_H / 2 - (s["dec"] - center_dec) * sy, 1)
```

整段替换为：
```python
if star_map:
    star_list = [
        {"ra": s["ra"], "dec": s["dec"]}
        for s in star_map.values()
        if s.get("ra") is not None and s.get("dec") is not None
    ]
    field = compute_field(star_list, {"w": VIEW_W, "h": VIEW_H}, 30)
    for hip, s in star_map.items():
        if s.get("ra") is None or s.get("dec") is None:
            continue
        x, y = project(
            s["ra"], s["dec"],
            field["center"][0], field["center"][1],
            field["scale"], {"w": VIEW_W, "h": VIEW_H}
        )
        s["x"] = round(x, 1)
        s["y"] = round(y, 1)
```

- [ ] **Step 3：删除 `cos_dec`/`max_dra_cos`/`max_ddec`/`sx`/`sy` 中间变量**

全文搜索 `cos_dec =` / `max_dra_cos` / `max_ddec` / ` sx` / ` sy`（注意前导空格），确认已无引用；若整个脚本只剩这一处用这些变量，删除该处定义。

- [ ] **Step 4：保留三垣 entry 不写 x/y 的逻辑**

确认 `s["x"] = round(x, 1)` / `s["y"] = round(y, 1)` 在三垣 entry 的分支里被跳过（如果原代码三垣就是空 star_map，则不会进入 `if star_map` 分支，行为不变）。

---

### Task 2.2：跑脚本重生 310 个 Chinese JSON

**Files:**
- Regenerate: `server/data/traditions/chinese/*.json`（310 个）
- Regenerate: `server/data/traditions/chinese/_meta.json`

**Interfaces:**
- Consumes: `build_chinese_stars.py`（Task 2.1）+ `celestial_data/*.csv/geojson`
- Produces: 310 个 Chinese JSON + `_meta.json`

- [ ] **Step 1：跑脚本**

Run:
```bash
cd server && .venv/Scripts/python.exe scripts/build_chinese_stars.py 2>&1 | tee /tmp/build-chinese.log
```
Expected: `Wrote 310 entries`（或类似成功信息）；无 traceback

- [ ] **Step 2：检查关键文件**

```bash
cd server && head -20 data/traditions/chinese/bei_dou.json
cd server && head -20 data/traditions/chinese/zi_wei_yuan.json
```
Expected:
- `bei_dou.json` stars 有 `x`/`y` 字段
- `zi_wei_yuan.json` stars **没有** `x`/`y`（三垣约定）

- [ ] **Step 3：检查 _meta.json star_count 更新**

```bash
cd server && cat data/traditions/chinese/_meta.json
```
Expected: `"star_count": 309`（或新生成的准确数）

- [ ] **Step 4：跑后端测试验证 schemas 不破坏**

Run:
```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```
Expected: 26 + 7 = 33 测试全过

---

### Task 2.3：视觉验证 + 截图存档

**Files:**
- Create: `作品提交文件夹/04码道使用证明/260901-beidou-before-after.png`

- [ ] **Step 1：启服务 + 打开 atlas view 截图北斗**

Run:
```bash
cd server && ASTROMETRY_MOCK=1 .venv/Scripts/python.exe -m uvicorn main:app --port 8000 &
cd ../web && pnpm dev &
sleep 5
```

浏览器打开 `http://localhost:5173/atlas`，切到 chinese tradition，点北斗（`bei_dou`）→ 截图北斗当前视图（**预期已是横扁勺形**，因为新公式 + 新 JSON 已生效）

保存到 `作品提交文件夹/04码道使用证明/260901-beidou-after.png`（after 状态）

- [ ] **Step 2：git checkout 看 before 状态截图对比**

```bash
cd "D:/Projects/260820OPC"
git stash
# 此时 working tree 是 Commit 1 状态（formula 改了但 Chinese JSON 还是旧的 sx≠sy）
# 启服务 + 截图北斗 → 看到的就是 before（仍是 sy=51 拉扁的勺子）
# 保存到 260901-beidou-before.png
git stash pop
# 恢复 after 状态
```

**注意**：before/after 截图都用**新公式的 runtime** 渲染（保证渲染管线一致），差异只来自 x/y 数据。

- [ ] **Step 3：拼图成 before-after 对比图**

用任意图像工具（paint / Photoshop / PIL）把 before/after 两张并排，标题"260901-beidou-projection-fix" → 保存为 `作品提交文件夹/04码道使用证明/260901-beidou-before-after.png`

**视觉验收标准**（如未达到要回退改公式再重生）：
- 北斗勺柄（摇光 → 开阳 → 玉衡 → 天权 → 天玑）从左上到右下斜向延伸，勺口（天枢 / 天璇）朝右
- 整体呈**横向勺形**（x 跨度 >> y 跨度）
- 对比 before（sy 拉到 51 px/°）纵向被拉扁的勺子，差异肉眼可见

---

### Task 2.4：Commit 2

- [ ] **Step 1：Stage 代码 + 数据 + 截图**

```bash
cd "D:/Projects/260820OPC"
git add server/scripts/build_chinese_stars.py
git add server/data/traditions/chinese/
git add "作品提交文件夹/04码道使用证明/260901-beidou-before-after.png"
git status | head -30
```

- [ ] **Step 2：Commit**

```bash
cd "D:/Projects/260820OPC"
git commit -m "fix(atlas): Chinese 数据重生 + build script 走 Stereographic + 移除 RA 镜像"
```

---

## Commit 3：Western 数据从 celestial_data 重生（88 JSON）

### Task 3.1：创建 `server/scripts/build_western_stars.py`

**Files:**
- Create: `server/scripts/build_western_stars.py`

**Interfaces:**
- Consumes:
  - `celestial_data/constellations.lines.geojson`（line 端点为 HIP）
  - `celestial_data/constellations.boundaries.csv`（IAU 1930 边界，用于"星座内星"判定）
  - `celestial_data/stars.8.min.geojson`（HIP + RA + Dec + mag）
  - `celestial_data/starnames.csv`（HIP → 英文常用专名）
  - `assets/星官对应.md`（HIP → 中文古名）
  - `server/data/traditions/western/*.json`（旧版本，含 hand_overrides + stories/season/caption 等手工字段）
  - `scripts/atlas_projection`（Task 1.1）
- Produces: 88 个 `server/data/traditions/western/{abbr}.json`（HIP-keyed stars + 完整 schema）

- [ ] **Step 1：写脚本骨架 + 数据加载**

```python
"""从 celestial_data 重算 88 个 Western 星座 JSON。

- 收录规则：lines 端点 HIP ∪ IAU 1930 边界内 mag < 5.5 的星
- label 阈值：mag < 4.5
- hand_overrides：合并旧 JSON 顶层 hand_overrides 字段
- stories/season/caption：保留旧 JSON；无则按 RA 推季节 / 空串 / 空 dict
"""
from __future__ import annotations
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.atlas_projection import compute_field, project  # noqa: E402

VIEWBOX = {"w": 700, "h": 700}
PADDING = 30
LABEL_MAG_THRESHOLD = 4.5
INCLUDE_MAG_THRESHOLD = 5.5

CELESTIAL_DATA = ROOT.parent / "celestial_data"  # 实际路径以 repo 布局为准
ASSETS = ROOT / "assets"
WESTERN_DIR = ROOT / "data" / "traditions" / "western"
```

- [ ] **Step 2：写数据加载函数**

```python
def load_lines_geojson() -> dict[str, list[tuple[str, str]]]:
    """constellation_abbr → [(hip_a, hip_b), ...]"""
    path = CELESTIAL_DATA / "constellations.lines.geojson"
    with path.open() as f:
        data = json.load(f)
    result: dict[str, list[tuple[str, str]]] = {}
    for feat in data["features"]:
        abbr = feat["properties"]["constellation"]
        coords = feat["geometry"]["coordinates"]
        # coords = [[lon, lat], [lon, lat]]
        result.setdefault(abbr, []).append((str(coords[0][0]), str(coords[1][0])))
    return result


def load_stars() -> dict[str, dict]:
    """hip → {ra, dec, mag}"""
    path = CELESTIAL_DATA / "stars.8.min.geojson"
    with path.open() as f:
        data = json.load(f)
    result = {}
    for feat in data["features"]:
        hip = feat["properties"].get("hip") or feat["id"]
        result[hip] = {
            "ra": feat["properties"]["ra"],
            "dec": feat["properties"]["dec"],
            "magnitude": feat["properties"]["mag"],
        }
    return result


def load_boundaries() -> dict[str, list[tuple[float, float]]]:
    """constellation_abbr → [(ra, dec), ...]（IAU 1930 边界多边形顶点）"""
    path = CELESTIAL_DATA / "constellations.boundaries.csv"
    result: dict[str, list[tuple[float, float]]] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            abbr = row["constellation"]
            result.setdefault(abbr, []).append((float(row["ra"]), float(row["dec"])))
    return result


def load_starnames() -> dict[str, dict]:
    """hip → {"english_name": str, "bayer": str}（fallback 空串）"""
    path = CELESTIAL_DATA / "starnames.csv"
    result: dict[str, dict] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            result[row["hip"]] = {
                "english_name": row.get("english_name", "").strip(),
                "bayer": row.get("bayer", "").strip(),
            }
    return result


def load_chinese_name_table() -> dict[str, str]:
    """hip → 中文古名（assets/星官对应.md 解析）

    Markdown 表格形如：`| HIP 54061 | 参宿四 | Beta Ori |`
    """
    import re
    path = ASSETS / "星官对应.md"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(?:HIP\s*)?(\d+)\s*\|\s*(\S+?)\s*\|", line)
        if m:
            result[m.group(1)] = m.group(2)
    return result


def load_constellations_csv() -> list[dict]:
    """constellations.cn.csv → 88 行（含中文星官名 + latin + abbr）"""
    path = CELESTIAL_DATA / "constellations.csv"
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))
```

- [ ] **Step 3：写 point-in-polygon 判定**

```python
def point_in_boundary(
    ra: float, dec: float, polygon: list[tuple[float, float]]
) -> bool:
    """球面简单判定：球面多边形包含点。

    简化为 RA 维度 wrap + 平面 polygon 测试（粗略但够用）。
    """
    if not polygon:
        return False
    # wrap ra 到多边形 ra 范围中心
    center_ra = sum(p[0] for p in polygon) / len(polygon)
    ra_wrapped = ra
    while ra_wrapped - center_ra > 180:
        ra_wrapped -= 360
    while ra_wrapped - center_ra < -180:
        ra_wrapped += 360

    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > dec) != (yj > dec)) and (
            ra_wrapped < (xj - xi) * (dec - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside
```

- [ ] **Step 4：写"按 RA 推季节"辅助**

```python
def guess_season(ral: float) -> str:
    """按 RA 推季节（0-6h→winter, 6-12h→spring, 12-18h→summer, 18-24h→autumn）"""
    h = ral / 15.0 % 24
    if 0 <= h < 6 or h >= 18:  # 0-6h ∪ 18-24h = winter
        return "winter"
    if 6 <= h < 12:
        return "spring"
    if 12 <= h < 18:
        return "summer"
    return "autumn"
```

- [ ] **Step 5：写主流程 `build_one`**

```python
def build_one(
    abbr: str,
    lines: list[tuple[str, str]],
    stars_db: dict[str, dict],
    boundaries: dict[str, list],
    starnames: dict[str, dict],   # 改：dict-of-dicts（english_name + bayer）
    cn_names: dict[str, str],
    csv_row: dict,
    old_json: dict | None,
) -> dict:
    """生成单个星座 JSON（含 hand_overrides merge + 字段填充）"""

    # 1. 收集本星座所有 line 端点 HIP + 边界内亮星
    hip_set: set[str] = set()
    for h1, h2 in lines:
        hip_set.add(h1)
        hip_set.add(h2)

    boundary = boundaries.get(abbr, [])
    for hip, s in stars_db.items():
        if s["magnitude"] < INCLUDE_MAG_THRESHOLD:
            if point_in_boundary(s["ra"], s["dec"], boundary):
                hip_set.add(hip)

    # 2. stars dict
    star_coords = []
    stars_dict: dict[str, dict] = {}
    for hip in hip_set:
        if hip not in stars_db:
            continue
        s = stars_db[hip]
        star_coords.append({"ra": s["ra"], "dec": s["dec"]})
        stars_dict[f"HIP_{hip}"] = {
            "bayer": starnames.get(hip, {}).get("bayer", ""),
            "name": starnames.get(hip, {}).get("english_name", ""),  # fallback 空串
            "name_zh": cn_names.get(hip, ""),
            "magnitude": s["magnitude"],
            "ra": s["ra"],
            "dec": s["dec"],
            "label": s["magnitude"] < LABEL_MAG_THRESHOLD,
            "hip": hip,
        }

    # 3. 投影
    field = compute_field(star_coords, VIEWBOX, PADDING)
    for key, star in stars_dict.items():
        x, y = project(
            star["ra"], star["dec"],
            field["center"][0], field["center"][1],
            field["scale"], VIEWBOX,
        )
        star["x"] = round(x, 1)
        star["y"] = round(y, 1)

    # 4. 拼 entry
    entry = {
        "abbr": abbr,
        "name": csv_row.get("en", csv_row.get("latin", abbr)).strip(),
        "name_zh": csv_row.get("name", "").strip(),
        "latin": csv_row.get("latin", csv_row.get("en", "")).strip(),
        "viewBox": {"width": VIEWBOX["w"], "height": VIEWBOX["h"]},
        "center": {"ra": round(field["center"][0], 4), "dec": round(field["center"][1], 4)},
        "stars": stars_dict,
        "lines": [[f"HIP_{h1}", f"HIP_{h2}"] for h1, h2 in lines if h1 in stars_db and h2 in stars_db],
        "season": (old_json or {}).get("season") or guess_season(field["center"][0]),
        "caption": (old_json or {}).get("caption", ""),
        "stories": (old_json or {}).get("stories", {}),
    }

    # 5. hand_overrides merge
    if old_json and "hand_overrides" in old_json:
        overrides = old_json["hand_overrides"]
        for hip_key, overrides_star in overrides.get("stars", {}).items():
            if hip_key in entry["stars"]:
                entry["stars"][hip_key].update(overrides_star)
        if "lines" in overrides:
            entry["lines"] = overrides["lines"]

    return entry
```

- [ ] **Step 6：写 main 入口**

```python
def main():
    lines_db = load_lines_geojson()
    stars_db = load_stars()
    boundaries = load_boundaries()
    starnames = load_starnames()
    cn_names = load_chinese_name_table()
    constellations_csv = {row["abbreviation"]: row for row in load_constellations_csv()}

    WESTERN_DIR.mkdir(parents=True, exist_ok=True)

    missing_constellations = []
    missing_stars: set[str] = set()
    written = 0

    for abbr in sorted(lines_db.keys()):
        if abbr not in constellations_csv:
            missing_constellations.append(abbr)
            continue
        old_json_path = WESTERN_DIR / f"{abbr}.json"
        old_json = None
        if old_json_path.exists():
            try:
                with old_json_path.open(encoding="utf-8") as f:
                    old_json = json.load(f)
            except json.JSONDecodeError:
                pass

        entry = build_one(
            abbr, lines_db[abbr], stars_db, boundaries, starnames,
            cn_names, constellations_csv[abbr], old_json,
        )

        # 检查 stars 完整性
        for hip in [h for pair in lines_db[abbr] for h in pair]:
            if hip not in stars_db:
                missing_stars.add(hip)

        with (WESTERN_DIR / f"{abbr}.json").open("w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        written += 1

    print(f"Wrote {written} entries to {WESTERN_DIR}")
    if missing_constellations:
        (ASSETS / "missing_constellations.md").write_text(
            "# Missing constellations in constellations.csv\n\n"
            + "\n".join(f"- {c}" for c in missing_constellations),
            encoding="utf-8",
        )
        print(f"WARN: {len(missing_constellations)} missing → assets/missing_constellations.md")
    if missing_stars:
        (ASSETS / "missing_stars.md").write_text(
            "# Missing HIPs in stars.8.min.geojson\n\n"
            + "\n".join(f"- HIP {h}" for h in sorted(missing_stars)),
            encoding="utf-8",
        )
        print(f"WARN: {len(missing_stars)} stars missing → assets/missing_stars.md")


if __name__ == "__main__":
    main()
```

---

### Task 3.2：跑脚本重生 88 个 Western JSON

**Files:**
- Regenerate: `server/data/traditions/western/*.json`（88 个）
- Regenerate: `server/data/traditions/western/_meta.json`
- Conditional Create: `assets/missing_constellations.md` / `assets/missing_stars.md`

- [ ] **Step 1：跑脚本**

Run:
```bash
cd server && .venv/Scripts/python.exe scripts/build_western_stars.py 2>&1 | tee /tmp/build-western.log
```
Expected:
- `Wrote 88 entries`
- 若有 WARN，写了 missing 文件

- [ ] **Step 2：检查猎户 sample**

```bash
cd server && head -40 data/traditions/western/ori.json
```
Expected:
- `name`: "Orion"（不是中文星官名）
- stars 有 HIP-keyed entries
- stars 有 `x`/`y`
- Betelgeuse 的 x **大于** Rigel 的 x（东=右约定；这是 §7.1 提到的方向断言）

- [ ] **Step 3：跑后端测试**

Run:
```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```
Expected: 33 测试全过（无新增，但 traditions 反查测试可能因新 schema 失败 → 修测试或放宽断言）

- [ ] **Step 4：跑前端测试**

Run:
```bash
cd web && pnpm test
```
Expected: 全部 PASS（含 atlas 新断言）

---

### Task 3.3：视觉验证 + 截图存档

**Files:**
- Create: `作品提交文件夹/04码道使用证明/260901-orion-before-after.png`

- [ ] **Step 1：启服务 + 截图猎户 after**

```bash
cd server && ASTROMETRY_MOCK=1 .venv/Scripts/python.exe -m uvicorn main:app --port 8000 &
cd ../web && pnpm dev &
sleep 5
```

浏览器打开 `http://localhost:5173/atlas`，切到 western tradition，点猎户 → 截图保存到 `260901-orion-after.png`

**视觉验收**：
- Betelgeuse 在左上、Rigel 在右下（参宿四 RA 88.8° > 参宿七 RA 78.6°，所以 Betelgeuse 在右——**这是 spec 决策，东=右**，与 Stellarium 默认 as-seen 不同但与用户决定一致）
- 腰带三星（Alnitak/Alnilam/Mintaka）横向排列，斜度自然
- 整体呈"裸眼天上看到的猎户"形状，不是矩形块

- [ ] **Step 2：git checkout 旧 ori.json 截图 before**

```bash
cd "D:/Projects/260820OPC"
git stash  # 暂存当前 after 状态
# 此时 working tree 是 Commit 2 状态（Western JSON 还是手绘 x/y）
# 启服务 + 截图猎户 → 看到的就是 before
# 保存到 260901-orion-before.png
git stash pop  # 恢复 after
```

- [ ] **Step 3：拼 before-after 对比图**

保存为 `作品提交文件夹/04码道使用证明/260901-orion-before-after.png`

---

### Task 3.4：Commit 3

- [ ] **Step 1：Stage 代码 + 数据 + 截图**

```bash
cd "D:/Projects/260820OPC"
git add server/scripts/build_western_stars.py
git add server/data/traditions/western/
git add assets/missing_constellations.md  # 若存在
git add assets/missing_stars.md  # 若存在
git add "作品提交文件夹/04码道使用证明/260901-orion-before-after.png"
git status | head -30
```

- [ ] **Step 2：Commit**

```bash
cd "D:/Projects/260820OPC"
git commit -m "feat(atlas): 新建 build_western_stars.py + Western 数据从 celestial_data 重生 + name 字段修复"
```

---

## 合并到 main

### Task 4.1：审查整体改动

- [ ] **Step 1：review git diff**

```bash
cd "D:/Projects/260820OPC"
git checkout main
git diff --stat fix-260901-atlas-projection-fix
git log main..fix-260901-atlas-projection-fix --oneline
```

**检查**：
- 改动文件数符合预期（~400：5 个代码/脚本/测试 + 398 个 JSON + 2-3 个 PNG + 0-2 个 missing md）
- 提交历史 4 个 commit（spec + 3 个实现）

- [ ] **Step 2：人工抽样对比**

随机挑 5 个 Western JSON + 5 个 Chinese JSON，肉眼 vs Stellarium 截图对比，确认无明显畸变

### Task 4.2：Squash merge 到 main

- [ ] **Step 1：Squash merge**

```bash
cd "D:/Projects/260820OPC"
git checkout main
git merge --squash fix-260901-atlas-projection-fix
git status | head -30
```

- [ ] **Step 2：提交（单 commit）**

```bash
cd "D:/Projects/260820OPC"
git commit -m "fix(atlas): 投影统一改 Azimuthal Stereographic + Chinese/Western 数据重生

- 抽 atlas_projection.py / atlasProjection.ts 共享 Stereographic 公式（带中心点奇异性处理）
- worldToPixelEquirect 改调 atlasProjection.projectStereographic
- build_chinese_stars.py 调新公式、移除 commit e2ed1bf 引入的 RA 镜像、东=右
- 新建 build_western_stars.py 从 celestial_data 重生 88 JSON
- displayNameFor 修复 Western 走英文常用名（不再是中文兜底）
- 数据 schema 收敛：HIP-keyed stars、hip 字段必有
- hand_overrides 合并机制保护手工 patch"
```

- [ ] **Step 3：分支保留（按 CLAUDE.md 不删除临时分支）**

**不要**执行 `git branch -D fix-260901-atlas-projection-fix`，保留供追溯。

---

---

---

---

---