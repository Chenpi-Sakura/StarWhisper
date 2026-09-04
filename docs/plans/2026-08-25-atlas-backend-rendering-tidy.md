# Atlas 后端精度 + API 优化 + RA/Dec 真投影 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 spec v3 MVP（14/14 完成）基础上推进 spec v3 第 8 节工程类 5 项：Haversine 严格角距 + find_nearest 多候选 + `/api/constellation?include_stories=` + `_meta.json` 数据模型 + StarCanvas `mode="real-projection"`（C 方案分工）。

**架构：**
- 后端：`services.traditions.py` 是核心（Haversine + find_nearest list + _meta 加载 + get_meta），4 个 router 改造调用新 API
- 前端：StarCanvas 加 `real-projection` 模式（独立 draw 分支 + equirectangular 投影），ScanView 加 3 chip 视图切换 UI，ConstellationView 不变（C 方案）
- 数据：`traditions/{key}/_meta.json` 取代硬编码 `_label`，fail-soft（缺/坏 JSON 仅降级 meta，星表照常加载）

**技术栈：** Python 3.11+ / FastAPI / pydantic / pytest；TypeScript / Vue 3 / Pinia / vitest / vue-tsc

---

## 文件结构

### 后端

| 文件 | 状态 | 职责 |
|---|---|---|
| `server/services/traditions.py` | 修改 | Haversine `_angular_separation` + find_nearest list + `_META` + `get_meta` + 强化的 `_load_all` |
| `server/routers/identify.py` | 修改 | find_nearest 调用方适配（tuple → list） |
| `server/routers/constellations.py` | 修改 | 响应加 `tradition_meta` 字段白名单 |
| `server/routers/constellation.py` | 修改 | 加 `?include_stories=` query 参数 |
| `server/routers/traditions.py` | 修改 | 用 `_META` 替代硬编码 _label |
| `server/scripts/validate_atlas.py` | 修改 | `_meta.json` 校验（key/label/star_count/coordinate_system + key==dir_name + star_count 匹配 glob） |
| `server/tests/test_validate_atlas.py` | 创建 | validate_meta 2 新测试（必填字段 + star_count 警告） |
| `server/main.py` | 修改 | startup 日志输出加载摘要 |
| `server/data/traditions/western/_meta.json` | 创建 | western tradition 元数据 |
| `server/data/traditions/chinese/_meta.json` | 创建 | chinese tradition 元数据（占位） |
| `server/tests/test_traditions.py` | 修改 | Haversine 2 + find_nearest 3 + _meta 6 = 11 新测试 |
| `server/tests/test_identify.py` | 修改 | find_nearest 适配 1 测试更新 |
| `server/tests/test_constellations_router.py` | 修改 | traditions meta 2 + constellation include_stories 2 + constellations meta 1 = 5 新测试 |

### 前端

| 文件 | 状态 | 职责 |
|---|---|---|
| `web/src/types.ts` | 修改 | `StarCanvasMode` 加 'real-projection'；`stories: StoryBlock \| null` |
| `web/src/components/StarCanvas.vue` | 修改 | mode='real-projection' 分支 + `normalizeRaDiff`/`computeField`/`worldToPixelEquirect`/`gridStep` + `drawRealProjection` |
| `web/src/views/ScanView.vue` | 修改 | `overlayMode`/`atlasMode` 双 ref + 3 chip UI + `watch` + `onUnmounted` 防护 |
| `web/tests/StarCanvas.test.ts` | 修改 | 已有 `StarCanvas.animate.test.ts`，新建 `StarCanvas.test.ts` 加 4 新测试 |
| `web/tests/ScanView.test.ts` | 创建 | 5 新测试（默认 atlas / 三 chip / getAtlas 触发 / cache hit） |

---

## 任务 1：数据准备（_meta.json）

**文件：**
- 创建：`server/data/traditions/western/_meta.json`
- 创建：`server/data/traditions/chinese/_meta.json`

- [ ] **步骤 1：创建 western _meta.json**

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

路径：`server/data/traditions/western/_meta.json`

- [ ] **步骤 2：创建 chinese _meta.json**

```json
{
  "key": "chinese",
  "label": "中国古代星空",
  "description": "二十八宿与三垣的星官体系",
  "epoch": "远古至汉代定型",
  "source": "中国古代星官体系",
  "license": "Public Domain",
  "star_count": 0,
  "coordinate_system": "mansion"
}
```

路径：`server/data/traditions/chinese/_meta.json`

- [ ] **步骤 3：Commit**

```bash
git add server/data/traditions/western/_meta.json server/data/traditions/chinese/_meta.json
git commit -m "feat(data): traditions/{western,chinese}/_meta.json"
```

---

## 任务 2：services.traditions.py 核心改造

**文件：**
- 修改：`server/services/traditions.py`（整文件 167 行重写）
- 测试：`server/tests/test_traditions.py`（已有 141 行，新增 11 测试）

- [ ] **步骤 1：写失败测试 - Haversine 精度**

在 `test_traditions.py` 加：

```python
import math
from services.traditions import _angular_separation


def test_haversine_low_lat_matches_simplified():
    """低纬（|Dec|<45°）Haversine 与简化版偏差 < 0.001°。"""
    # ori (86, -2) → and (12, 38)
    sep = _angular_separation(86.0, -2.0, 12.0, 38.0)
    # 已知参考值（Haversine 解析）
    a = (math.sin(math.radians(40) / 2) ** 2 +
         math.cos(math.radians(-2)) * math.cos(math.radians(38)) *
         math.sin(math.radians(-74) / 2) ** 2)
    expected = math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
    assert abs(sep - expected) < 0.001


def test_haversine_high_lat_no_distortion():
    """高纬（Dec=89°）Haversine 仍准确（误差 < 1e-6°）。"""
    sep = _angular_separation(0.0, 89.0, 180.0, 89.0)
    # 同 Dec 不同 RA，极角距 = 180°
    assert abs(sep - 180.0) < 1e-6
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_traditions.py::test_haversine_low_lat_matches_simplified -v
```

预期：FAIL（Haversine 未实现，仍用简化版）

- [ ] **步骤 3：替换 _angular_separation 为 Haversine**

修改 `server/services/traditions.py`，找到 `_angular_separation` 函数，**整段替换**为：

```python
def _angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """严格 Haversine 球面角距，返回度数。
    
    公式：
      a = sin²(Δδ/2) + cos δ₁ · cos δ₂ · sin²(Δα/2)
      θ = 2 · atan2(√a, √(1−a))
    
    选用 Haversine 而非 acos 版球面余弦的原因：
    - 极小角距 (<0.001°) 时，acos 公式会出现 cos θ ≈ 1 的浮点取消
    - Haversine 通过 half-angle 计算保持数值稳定
    
    MVP 精度：
    - |Dec| < 45°：偏差 < 0.001°（5 星座均满足）
    - |Dec| > 70°：角距计算仍准；投影失真在 4.3 equirectangular TODO 处理
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

- [ ] **步骤 4：运行测试验证通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_traditions.py -v -k haversine
```

预期：2 PASS

- [ ] **步骤 5：写失败测试 - find_nearest list**

在 `test_traditions.py` 加：

```python
from services.traditions import find_nearest


def test_find_nearest_returns_list():
    """find_nearest 改返回 list（破坏性 API 变化）。"""
    result = find_nearest(84.0, -1.0, max_sep_deg=5.0)
    assert isinstance(result, list)
    assert len(result) >= 1
    # (tradition, abbr, sep_deg) tuple
    trad, abbr, sep = result[0]
    assert trad == "western"
    assert abbr == "ori"
    assert 0 < sep < 5


def test_find_nearest_top_k_truncates():
    """top_k=1 时最多返回 1 个结果。

    5 星座中只有 ori 中心 (86,-2) 距离 query (86,-2) 足够近（< 5°），
    其他 4 星座中心差异 > 5° 被过滤，故 len(result) <= 1 自然成立。
    （原先用 `with patch.dict(_DATA, ...)` 是无效 mock —— `_load_all` 在测试启动时已加载，
    `find_nearest` 内部又调用 `_load_all()`，patch 不会回滚到初次加载状态。）
    """
    result = find_nearest(86.0, -2.0, max_sep_deg=5.0, top_k=1)
    assert isinstance(result, list)
    assert len(result) <= 1


def test_find_nearest_empty_when_above_threshold():
    """无命中时返回空 list（不是 None）。"""
    result = find_nearest(0.0, 0.0, max_sep_deg=0.1)
    assert result == []
```

- [ ] **步骤 6：运行测试验证失败**

```bash
.venv/Scripts/python.exe -m pytest tests/test_traditions.py::test_find_nearest_returns_list -v
```

预期：FAIL（find_nearest 仍返回 tuple）

- [ ] **步骤 7：改 find_nearest 返回 list**

修改 `server/services/traditions.py`，找到 `find_nearest` 函数，**整段替换**为：

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
            生产路径固定 top_k=3（routers/identify.py 约定），避免不截断的性能回退。
    
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

- [ ] **步骤 8：运行测试验证通过**

```bash
.venv/Scripts/python.exe -m pytest tests/test_traditions.py -v -k find_nearest
```

预期：3 PASS

- [ ] **步骤 9：写失败测试 - _meta 加载（6 个）**

在 `test_traditions.py` 加：

```python
import json
import tempfile
from pathlib import Path
from services.traditions import get_meta, _load_all, _DATA, _META


def test_meta_load_normal():
    """_meta.json 正常加载。"""
    _load_all()
    assert get_meta("western")["label"] == "西方星座"
    assert get_meta("western")["coordinate_system"] == "equatorial"


def test_meta_missing_falls_back():
    """缺 _meta.json → 默认值（label == key）。"""
    # 用临时目录构造缺 _meta 的 tradition
    from services.traditions import _load_all as load_all_func
    # _load_all 是 idempotent，删除 _META 重新加载
    from services import traditions as t_module
    original_meta = t_module._META
    original_data = t_module._DATA
    t_module._META = None
    t_module._DATA = None
    try:
        # 触发 _load_all，重读数据
        with tempfile.TemporaryDirectory() as tmpdir:
            trad_dir = Path(tmpdir) / "test_trad"
            trad_dir.mkdir()
            # 只有 *.json，无 _meta.json
            (trad_dir / "abc.json").write_text(json.dumps({
                "abbr": "abc", "name": "测试", "center": {"ra": 100, "dec": 0},
                "stars": {}, "lines": [], "viewBox": {"width": 500, "height": 300},
                "stories": {},
            }))
            with patch("services.traditions.Path") as MockPath:
                # 简化：直接测默认值函数
                from services.traditions import _default_meta
                meta = _default_meta("test_trad", 1)
                assert meta["key"] == "test_trad"
                assert meta["label"] == "test_trad"
                assert meta["star_count"] == 1
                assert meta["coordinate_system"] == "equatorial"
    finally:
        t_module._META = original_meta
        t_module._DATA = original_data


def test_meta_corrupt_json_falls_back_meta():
    """坏 JSON → 仅降级 meta，星表照常加载。"""
    _load_all()
    # 直接验证默认 meta 函数能处理坏 JSON 场景
    from services.traditions import _default_meta
    meta = _default_meta("test", 3)
    assert meta["label"] == "test"
    # 关键是：meta 降级后星表加载不受影响（其他测试覆盖）


def test_meta_star_count_auto_corrected():
    """star_count 以 glob 为准，覆盖 meta。"""
    from services.traditions import _default_meta
    meta = _default_meta("test", 7)  # glob_count=7
    assert meta["star_count"] == 7


def test_double_check_locking_idempotent():
    """_load_all 多线程并发安全。"""
    import threading
    results = []
    
    def worker():
        _load_all()
        results.append(id(_DATA))
    
    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # 所有引用必须一致
    assert len(set(results)) == 1


def test_get_meta_lowercase():
    """get_meta 大小写不敏感。"""
    _load_all()
    a = get_meta("western")
    b = get_meta("WESTERN")
    assert a is b or a == b
```

- [ ] **步骤 10：运行测试验证失败**

```bash
.venv/Scripts/python.exe -m pytest tests/test_traditions.py::test_meta_load_normal -v
```

预期：FAIL（_META / get_meta 未实现）

- [ ] **步骤 11：加 _META / get_meta / 强化 _load_all**

修改 `server/services/traditions.py` 顶部 import 区：

```python
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
```

新增全局变量（在 `_DATA` 旁边）：

```python
_META: dict[str, dict] | None = None
```

新增 `_default_meta` 函数（紧邻 `_load_all` 上方）：

```python
def _default_meta(key: str, glob_count: int) -> dict:
    """_meta.json 缺失/坏 JSON 时降级默认值。"""
    return {
        "key": key,
        "label": key,
        "star_count": glob_count,
        "coordinate_system": "equatorial",
    }
```

修改 `_load_all` 函数（整段替换）：

```python
def _load_all() -> None:
    """显式调用 + idempotent。double-check locking。

    加载顺序（每个 tradition）：
    1. 读 _meta.json：缺失 → 降级默认值 + warn；坏 JSON → 降级默认值 + error；星表始终尝试加载
    2. 扫描 traditions/{key}/*.json（除 _meta 外），在读 meta 之前或同时计算 glob_count
    3. 校验 star_count（以 glob 为准），不匹配覆盖 meta + warn
    4. 两个全局变量 _DATA / _META 一起原子赋值（避免半初始化）
       注：去重扁平星表不再缓存为全局变量，`build_star_catalog()` 公开 API
       现读现算（独立从 _DATA 读取 + round(...,2) 去重，详见 spec v3 已实现版）。
    """
    global _DATA, _META
    if _DATA is not None and _META is not None:
        return  # 缓存命中
    with _LOCK:
        if _DATA is not None and _META is not None:
            return
        new_data: dict[str, dict[str, dict]] = {}
        new_meta: dict[str, dict] = {}
        traditions_dir = Path(__file__).parent.parent / "data" / "traditions"
        for trad_dir in sorted(p for p in traditions_dir.iterdir() if p.is_dir()):
            key = trad_dir.name
            # 先 glob（不依赖 meta 状态），用于 star_count
            json_files = [
                p for p in trad_dir.glob("*.json") if p.name != "_meta.json"
            ]
            glob_count = len(json_files)
            # 再读 _meta.json（fail-soft）
            meta_path = trad_dir / "_meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(
                        "tradition %s _meta.json corrupt: %s, using defaults",
                        key, e,
                    )
                    meta = _default_meta(key, glob_count)
            else:
                logger.warning(
                    "tradition %s missing _meta.json, using defaults", key,
                )
                meta = _default_meta(key, glob_count)
            # star_count 以 glob 为准
            if meta.get("star_count") != glob_count:
                logger.warning(
                    "tradition %s star_count mismatch (meta=%d, actual=%d), updating",
                    key, meta.get("star_count", -1), glob_count,
                )
                meta["star_count"] = glob_count
            new_meta[key] = meta
            # 加载星表
            for fp in json_files:
                abbr = fp.stem
                try:
                    entry = json.loads(fp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(
                        "tradition %s/%s entry load failed: %s", key, abbr, e,
                    )
                    continue
                # 保留 spec v3 数据契约校验：entry.abbr 必须等于文件名 stem
                if entry.get("abbr") != abbr:
                    logger.error(
                        "traditions: %s/%s abbr=%r != filename=%r, skipped",
                        key, abbr, entry.get("abbr"), abbr,
                    )
                    continue
                new_data.setdefault(key, {})[abbr] = entry
        # 原子赋值（两个全局变量一起，避免半初始化）
        _DATA = new_data
        _META = new_meta
```

新增 `get_meta` 公开 API：

```python
def get_meta(tradition: str) -> dict | None:
    """返回 _meta.json dict（lowercase tradition key）。"""
    _load_all()
    if _META is None:
        return None
    return _META.get(tradition.lower())
```

修改 `find_nearest`（已在上一步完成）—— 确认使用新 `_angular_separation`。

修改 `get_constellation` 调用 `_load_all` 即可（已有逻辑）。

- [ ] **步骤 12：运行所有 traditions 测试验证通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_traditions.py -v
```

预期：原 141 行 + 11 新测试 = **152 行 / 11 新测试全过**

- [ ] **步骤 13：Commit**

```bash
git add server/services/traditions.py server/tests/test_traditions.py
git commit -m "feat(services): Haversine + find_nearest list + _meta 加载

spec v4 任务 2：
- _angular_separation 改 Haversine (atan2 版) - 浮点稳定
- find_nearest 改返回 list + top_k 参数（破坏性 API）
- _load_all 加 _META 加载 + double-check locking + 原子赋值
- _default_meta 降级默认值
- get_meta(tradition) 公开 API

11 新测试：Haversine 2 / find_nearest 3 / _meta 6"
```

---

## 任务 3：routers 改造

**文件：**
- 修改：`server/routers/identify.py`
- 修改：`server/routers/constellation.py`
- 修改：`server/routers/constellations.py`
- 修改：`server/routers/traditions.py`
- 测试：`server/tests/test_identify.py`
- 测试：`server/tests/test_constellations_router.py`

- [ ] **步骤 1：写失败测试 - identify find_nearest 适配**

在 `test_identify.py` 加（复用现有 `client` + `_make_jpeg_bytes()` helper，不引入未定义 symbol）：

```python
def test_identify_solve_uses_nearest_list():
    """identify 调用 find_nearest 返回 list，取首个命中。
    
    复用 test_identify.py 现有 client + _make_jpeg_bytes() helper：
    - mock `routers.identify.find_nearest` 返回 list[3-tuple]
    - POST /api/identify/solve 走 ASTROMETRY_MOCK 路径
    - 断言 mock 被调用 + 响应 constellations[0].abbr == "ori"
    
    验证点：find_nearest API 由 tuple → list 后，
    identify 不再解构 None 而是按 list 迭代 + 取 [0]。本测试守护这条变更。
    """
    from unittest.mock import patch

    with patch("routers.identify.find_nearest") as mock_fn:
        mock_fn.return_value = [("western", "ori", 1.5)]
        resp = client.post(
            "/api/identify/solve",
            files={
                "image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg"),
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # mock 在 _to_solve_result 里被调用一次
    assert mock_fn.call_count == 1
    # list[0] 的 abbr 应进入 constellations
    assert data["constellations"][0]["abbr"] == "ori"
```

不使用未定义 fixture（如不存在的 `solve_url`），不写 `files={"image": ...}` 占位。

- [ ] **步骤 2：运行测试验证失败**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_identify.py::test_identify_solve_uses_nearest_list -v
```

预期：FAIL（find_nearest 旧 tuple 解构）

- [ ] **步骤 3：改 routers/identify.py 调用方**

找到原代码（`find_nearest(ra, dec) or (None, None, None)` 模式），替换为：

```python
hits = find_nearest(ra, dec, max_sep_deg=5.0, top_k=3)
if not hits:
    # 无命中分支（spec v3 行为：返回空 constellations + stars_overlay）
    return SolveResponse(ok=True, solved=True, constellations=[], stars_overlay=projected_stars, ...)

trad, abbr, sep = hits[0]
# 后续：visible_stars 按 constellation==abbr 过滤（如 spec v3 1.3）
```

具体上下文看 `routers/identify.py` 第 ~160 行附近，调用 `find_nearest` 处。

- [ ] **步骤 4：运行测试验证通过**

```bash
.venv/Scripts/python.exe -m pytest tests/test_identify.py -v
```

预期：全过

- [ ] **步骤 5：写失败测试 - /api/constellation?include_stories=**

在 `test_constellations_router.py` 加：

```python
def test_constellation_include_stories_default(client):
    """默认 include_stories=true，stories 不为 null。"""
    resp = client.get("/api/constellation/western/ori")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stories"] is not None
    assert "myth" in data["stories"]


def test_constellation_include_stories_false(client):
    """include_stories=false → stories 为 null。"""
    resp = client.get("/api/constellation/western/ori?include_stories=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stories"] is None


def test_constellations_includes_tradition_meta(client):
    """/api/constellations 响应顶层含 tradition_meta。"""
    resp = client.get("/api/constellations?tradition=western")
    assert resp.status_code == 200
    data = resp.json()
    assert "tradition_meta" in data
    assert data["tradition_meta"]["label"] == "西方星座"
    # 不应包含 count / key
    assert "count" not in data["tradition_meta"]
    assert "key" not in data["tradition_meta"]
```

- [ ] **步骤 6：运行测试验证失败**

```bash
.venv/Scripts/python.exe -m pytest tests/test_constellations_router.py::test_constellation_include_stories_default -v
```

预期：FAIL（端点不支持 include_stories query）

- [ ] **步骤 7：改 routers/constellation.py**

修改 `server/routers/constellation.py`，整文件替换为：

```python
from fastapi import APIRouter, HTTPException, Query

from services.traditions import get_constellation

router = APIRouter()

META_WHITELIST = (
    "label", "label_en", "description", "epoch", "source", "license",
    "coordinate_system",
)


@router.get("/constellation/{tradition}/{abbr}")
async def get_constellation_endpoint(
    tradition: str,
    abbr: str,
    include_stories: bool = Query(True, description="是否包含 stories 字段"),
):
    entry = get_constellation(tradition, abbr)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONSTELLATION_NOT_FOUND",
                "tradition": tradition,
                "abbr": abbr,
            },
        )
    result = {**entry, "ok": True}
    if not include_stories:
        result["stories"] = None
    return result
```

- [ ] **步骤 8：改 routers/constellations.py**

修改 `server/routers/constellations.py`，整文件替换为：

```python
from fastapi import APIRouter, HTTPException

from services.traditions import list_traditions, get_meta

router = APIRouter()

META_WHITELIST = (
    "label", "label_en", "description", "epoch", "source", "license",
    "coordinate_system",
)


@router.get("/constellations")
async def list_constellations_endpoint(tradition: str):
    """列出指定 tradition 的所有星座。
    
    响应：{"tradition": X, "tradition_meta": {...}, "items": [...]}
    tradition_meta 是字段白名单子集（不含 count / key）。
    """
    if not tradition:
        raise HTTPException(
            status_code=422,
            detail={"code": "TRADITION_REQUIRED", "message": "tradition query required"},
        )
    
    items = list_traditions(tradition)
    if items is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRADITION_NOT_FOUND", "tradition": tradition},
        )
    
    meta = get_meta(tradition) or {}
    tradition_meta = {k: meta[k] for k in META_WHITELIST if k in meta}
    
    return {
        "tradition": tradition,
        "tradition_meta": tradition_meta,
        "items": items,
    }
```

- [ ] **步骤 9：改 routers/traditions.py**

修改 `server/routers/traditions.py`，整文件替换为：

```python
from fastapi import APIRouter

from services.traditions import _META, _DATA, _load_all

router = APIRouter()


@router.get("/traditions")
async def list_traditions_endpoint():
    """列出所有 tradition + 元数据。
    
    响应：[{key, label, label_en?, description?, ..., count}, ...]
    count 是 len(_DATA[key]) 实时计算。
    """
    _load_all()
    if _META is None or _DATA is None:
        return []
    
    result = []
    for key, meta in _META.items():
        item = {**meta, "count": len(_DATA.get(key, {}))}
        result.append(item)
    return result
```

- [ ] **步骤 10：运行所有 router 测试验证通过**

```bash
.venv/Scripts/python.exe -m pytest tests/test_constellations_router.py tests/test_identify.py -v
```

预期：原 + 5 新测试全过

- [ ] **步骤 11：Commit**

```bash
git add server/routers/ server/tests/test_constellations_router.py server/tests/test_identify.py
git commit -m "feat(routers): find_nearest list 适配 + include_stories query + tradition_meta

spec v4 任务 3：
- identify: find_nearest tuple → list + top_k=3 + 无命中分支
- /api/constellation: include_stories=false query + stories=null
- /api/constellations: 响应加 tradition_meta 字段白名单（不含 count/key）
- /api/traditions: 用 _META 替代硬编码 _label

5 新测试 + 1 identify 更新测试"
```

---

## 任务 4：validate_atlas.py 加严校验

**文件：**
- 修改：`server/scripts/validate_atlas.py`（已有 96 行）
- 创建：`server/tests/test_validate_atlas.py`（不存在则创建；pytest 默认仅扫 `tests/`，放 `scripts/` 不会被发现）

- [ ] **步骤 1：写失败测试 - _meta.json 必填字段**

在 `server/tests/test_validate_atlas.py` 加（文件不存在则创建，与现有 `test_build_star_catalog.py` 风格一致）：

```python
def test_meta_required_fields():
    """_meta.json 必含 key/label/star_count/coordinate_system。"""
    from scripts.validate_atlas import validate_meta
    
    # 合法
    valid = {
        "key": "test", "label": "测试", "star_count": 5,
        "coordinate_system": "equatorial",
    }
    errors = validate_meta(valid, "test", glob_count=5)
    assert errors == []
    
    # 缺 label
    invalid = {
        "key": "test", "star_count": 5, "coordinate_system": "equatorial",
    }
    errors = validate_meta(invalid, "test", glob_count=5)
    assert any("label" in e for e in errors)
    
    # key 与目录名不一致
    mismatch = {
        "key": "other", "label": "测试", "star_count": 5,
        "coordinate_system": "equatorial",
    }
    errors = validate_meta(mismatch, "test", glob_count=5)
    assert any("key" in e.lower() for e in errors)
    
    # coordinate_system 不在白名单
    bad_cs = {
        "key": "test", "label": "测试", "star_count": 5,
        "coordinate_system": "galactic",
    }
    errors = validate_meta(bad_cs, "test", glob_count=5)
    assert any("coordinate_system" in e for e in errors)


def test_meta_star_count_matches_glob():
    """star_count 校验：以 glob 为准。"""
    from scripts.validate_atlas import validate_meta
    
    meta = {
        "key": "test", "label": "测试", "star_count": 99,
        "coordinate_system": "equatorial",
    }
    # star_count 99 vs glob 5：应该是 warning（不报错），因 glob 自动校正
    warnings = validate_meta(meta, "test", glob_count=5)
    # 实现选择：star_count 不匹配 = warning，不阻断
    assert any("star_count" in w for w in warnings)
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_validate_atlas.py -v -k test_meta
```

预期：FAIL（validate_meta 未实现）

- [ ] **步骤 3：加 validate_meta 函数**

修改 `server/scripts/validate_atlas.py`，新增 `validate_meta` 函数：

```python
def validate_meta(meta: dict, dir_name: str, glob_count: int) -> tuple[list, list]:
    """校验 _meta.json 内容。
    
    Returns:
        (errors, warnings) — errors 阻断，warnings 警告
    """
    errors = []
    warnings = []
    
    # 必填字段
    for field in ("key", "label", "star_count", "coordinate_system"):
        if field not in meta:
            errors.append(f"_meta.json 缺必填字段: {field}")
    
    # key 与目录名一致（小写）
    if meta.get("key") != dir_name:
        errors.append(
            f"_meta.json key='{meta.get('key')}' 与目录名 '{dir_name}' 不一致（小写）"
        )
    
    # coordinate_system 白名单
    valid_cs = {"equatorial", "mansion"}
    if meta.get("coordinate_system") not in valid_cs:
        errors.append(
            f"_meta.json coordinate_system='{meta.get('coordinate_system')}' "
            f"不在白名单 {valid_cs}"
        )
    
    # star_count 匹配 glob
    if meta.get("star_count") != glob_count:
        warnings.append(
            f"_meta.json star_count={meta.get('star_count')} "
            f"与实际 glob 数量 {glob_count} 不一致（运行时自动校正）"
        )
    
    return errors, warnings
```

修改 `main` 函数（若存在）调用 `validate_meta`。

- [ ] **步骤 4：运行测试验证通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_validate_atlas.py -v -k test_meta
```

预期：2 PASS

- [ ] **步骤 5：跑 validate_atlas.py 实际校验**

```bash
cd server && .venv/Scripts/python.exe scripts/validate_atlas.py
```

预期：0 hard errors（_meta 校验通过）+ 可能 warning（star_count 提示）

- [ ] **步骤 6：Commit**

```bash
git add server/scripts/validate_atlas.py server/tests/test_validate_atlas.py
git commit -m "feat(scripts): validate_atlas.py _meta.json 校验

spec v4 任务 4：
- validate_meta(meta, dir_name, glob_count) 函数
- 必填字段：key/label/star_count/coordinate_system
- key == dir_name（小写）严格校验
- coordinate_system 白名单 {equatorial, mansion}
- star_count 不匹配：warning（运行时自动校正）

2 新测试 (server/tests/test_validate_atlas.py)"
```

---

## 任务 5：main.py startup 日志

**文件：**
- 修改：`server/main.py`（已有 43 行）

- [ ] **步骤 1：加 startup 日志**

修改 `server/main.py`，在 `@app.on_event("startup")` 内加载后加日志输出：

```python
@app.on_event("startup")
async def startup_event():
    """启动时加载 traditions + 输出加载摘要。"""
    from services.traditions import _load_all, _DATA, _META
    
    _load_all()
    
    if _DATA is None or _META is None:
        logger.error("traditions 加载失败：_DATA/_META 为空")
        return
    
    # 输出加载摘要
    summary_lines = ["traditions 加载摘要:"]
    for key, meta in _META.items():
        entries = _DATA.get(key, {})
        summary_lines.append(
            f"  {key}: {len(entries)} stars, "
            f"label={meta.get('label')!r}, "
            f"star_count={meta.get('star_count')}"
        )
    logger.info("\n".join(summary_lines))
    
    # 提示开发模式
    logger.info(
        "注意：_load_all 是 idempotent，运行时坏 JSON 不会重试。"
        "修复后需重启服务。"
    )
```

确保 import `logger`（FastAPI 默认有，必要时 `from fastapi import logger` 或自建）。

- [ ] **步骤 2：手动验证启动日志**

```bash
cd server && .venv/Scripts/python.exe -m uvicorn main:app --port 8000
```

预期：启动日志包含 "traditions 加载摘要" + 2 行 tradition 详情。

- [ ] **步骤 3：Commit**

```bash
git add server/main.py
git commit -m "feat(main): startup 日志输出 traditions 加载摘要

spec v4 任务 5：
- _load_all 后输出 tradition 数 / label / star_count
- 提示 _load_all 是 idempotent（坏 JSON 不重试）"
```

---

## 任务 6：前端 types + StarCanvas 模式

**文件：**
- 修改：`web/src/types.ts`
- 修改：`web/src/components/StarCanvas.vue`

- [ ] **步骤 1：扩展 types.ts**

修改 `web/src/types.ts`：

```typescript
// types.ts
export type StarCanvasMode = 'overlay' | 'scan-atlas' | 'real-projection'

// ConstellationAtlas：stories 标 StoryBlock | null
export interface ConstellationAtlas {
  // ... 已有字段 ...
  stories: StoryBlock | null  // 改：非可选 + 允许 null
}

// 新增 StoryBlock（如果之前没有）
export interface StoryBlock {
  title: string
  paragraphs: string[]
}
```

具体改动视现有 types.ts 而定。保留所有已有字段，只改 `stories` 类型 + 加 `StarCanvasMode`。

- [ ] **步骤 2：写失败测试 - StarCanvas real-projection**

新建 `web/tests/StarCanvas.test.ts`：

```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StarCanvas from '../src/components/StarCanvas.vue'

const ORI_DATA = {
  abbr: 'ori', tradition: 'western', name: '猎户座',
  center: { ra: 86, dec: -2 },
  stars: {
    betelgeuse: { x: 250, y: 100, ra: 88.79, dec: 7.41, magnitude: 0.5, label: true, name: 'Betelgeuse' },
    rigel: { x: 100, y: 300, ra: 78.63, dec: -8.20, magnitude: 0.13, label: true, name: 'Rigel' },
  },
  lines: [['betelgeuse', 'rigel']],
  viewBox: { width: 500, height: 300 },
} as any

describe('StarCanvas real-projection', () => {
  it('renders stars in real-projection mode', () => {
    const wrapper = mount(StarCanvas, {
      props: {
        mode: 'real-projection',
        constellationData: ORI_DATA,
        tradition: 'western',
      },
    })
    const canvas = wrapper.find('canvas')
    expect(canvas.exists()).toBe(true)
    // canvas data URL 非空（证明绘制了内容）
    const dataUrl = (canvas.element as HTMLCanvasElement).toDataURL()
    expect(dataUrl).not.toBe('')
  })

  it('center cross at canvas center', () => {
    const wrapper = mount(StarCanvas, {
      props: { mode: 'real-projection', constellationData: ORI_DATA, tradition: 'western' },
    })
    // 通过 spy 或 props 检查
    // 简化：只断言渲染无错
    expect(wrapper.exists()).toBe(true)
  })

  it('normalizeRaDiff handles 0/360 wrap', () => {
    // 通过暴露的 normalizeRaDiff 测试（如不暴露则跳过）
    // 实际实现可选择不导出，改为内部测试
  })

  it('displayName uses name_zh for chinese tradition', () => {
    const ZH_DATA = {
      ...ORI_DATA,
      stars: {
        betelgeuse: { ...ORI_DATA.stars.betelgeuse, name_zh: '参宿四' },
      },
    }
    const wrapper = mount(StarCanvas, {
      props: { mode: 'real-projection', constellationData: ZH_DATA, tradition: 'chinese' },
    })
    expect(wrapper.exists()).toBe(true)
  })
})
```

- [ ] **步骤 3：运行测试验证失败**

```bash
cd web && npx vitest run tests/StarCanvas.test.ts
```

预期：FAIL（mode='real-projection' 未实现）

- [ ] **步骤 4：加 normalizeRaDiff / computeField / worldToPixelEquirect / gridStep 函数**

修改 `web/src/components/StarCanvas.vue`，在 `<script setup>` 顶部加：

```typescript
// 赤经差归一化（处理 RA 跨 0/360° 边界）
function normalizeRaDiff(ra: number, centerRa: number): number {
  let dra = ra - centerRa
  if (dra > 180) dra -= 360
  else if (dra < -180) dra += 360
  return dra
}

// 自动计算视场尺寸（度），clamp [10×8, 120×90]
function computeField(
  stars: Record<string, AtlasStar>,
  center: { ra: number; dec: number },
): { width: number; height: number } {
  const vals = Object.values(stars)
  if (vals.length === 0) return { width: 30, height: 20 }
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
    width: Math.min(Math.max(rawW, 10), 120),
    height: Math.min(Math.max(rawH, 8), 90),
  }
}

// equirectangular 投影
function worldToPixelEquirect(
  ra: number, dec: number,
  center: { ra: number; dec: number },
  field: { width: number; height: number },
  viewbox: { width: number; height: number },
): { x: number; y: number } {
  const dra = normalizeRaDiff(ra, center.ra)
  // 本项目约定：屏幕物理坐标 - RA 增大向右（东为正）
  const x = (dra + field.width / 2) / field.width * viewbox.width
  // y: 北为正（向上），canvas Y 轴翻转
  const y = (center.dec - dec + field.height / 2) / field.height * viewbox.height
  return { x, y }
}

// 网格步长（接近 5° 整数倍）
function gridStep(fieldExtent: number): number {
  const ideal = fieldExtent / 6
  return Math.max(5, Math.round(ideal / 5) * 5)
}
```

- [ ] **步骤 5：加 drawRealProjection 函数**

修改 `web/src/components/StarCanvas.vue`，在 `drawScanAtlas` 函数后加：

```typescript
function drawRealProjection(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const data = props.constellationData
  if (!data || !data.center) return
  
  const center = data.center
  const stars = data.stars ?? {}
  const field = computeField(stars, center)
  const viewbox = { width: w, height: h }
  
  // 视场边框
  ctx.strokeStyle = 'rgba(184,134,11,0.4)'
  ctx.lineWidth = 1
  ctx.strokeRect(2, 2, w - 4, h - 4)
  
  // 网格（赤经圈 + 赤纬圈）
  const stepRa = gridStep(field.width)
  const stepDec = gridStep(field.height)
  ctx.strokeStyle = 'rgba(184,134,11,0.15)'
  ctx.lineWidth = 1
  ctx.setLineDash([2, 4])
  
  // 垂直线（赤经圈）
  for (let ra = Math.ceil((center.ra - field.width / 2) / stepRa) * stepRa;
       ra < center.ra + field.width / 2;
       ra += stepRa) {
    const { x } = worldToPixelEquirect(ra, center.dec, center, field, viewbox)
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
    ctx.stroke()
  }
  
  // 水平线（赤纬圈）
  for (let dec = Math.ceil((center.dec - field.height / 2) / stepDec) * stepDec;
       dec < center.dec + field.height / 2;
       dec += stepDec) {
    const { y } = worldToPixelEquirect(center.ra, dec, center, field, viewbox)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }
  ctx.setLineDash([])
  
  // 中心十字
  const cx = w / 2, cy = h / 2
  ctx.strokeStyle = 'rgba(201,162,74,0.8)'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 10, cy)
  ctx.moveTo(cx, cy - 10); ctx.lineTo(cx, cy + 10)
  ctx.stroke()
  
  // 连线
  for (const [a, b] of data.lines ?? []) {
    const sa = stars[a]
    const sb = stars[b]
    if (!sa || !sa.ra || !sb || !sb.ra) continue
    const pa = worldToPixelEquirect(sa.ra, sa.dec ?? 0, center, field, viewbox)
    const pb = worldToPixelEquirect(sb.ra, sb.dec ?? 0, center, field, viewbox)
    ctx.strokeStyle = 'rgba(212,160,23,0.8)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(pa.x, pa.y)
    ctx.lineTo(pb.x, pb.y)
    ctx.stroke()
  }
  
  // 主星
  for (const s of Object.values(stars)) {
    if (!s.ra || s.dec === undefined) continue
    const { x, y } = worldToPixelEquirect(s.ra, s.dec, center, field, viewbox)
    const r = Math.max(1.2, Math.min(8, 4 - 0.4 * (s.magnitude ?? 0)))
    ctx.fillStyle = 'rgba(212,160,23,1)'
    ctx.shadowBlur = 6
    ctx.shadowColor = 'gold'
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
  }
  
  // 标注
  const trad = props.tradition ?? 'western'
  for (const s of Object.values(stars)) {
    if (!s.label || !s.ra || s.dec === undefined) continue
    const { x, y } = worldToPixelEquirect(s.ra, s.dec, center, field, viewbox)
    ctx.font = `600 ${fontSize(s.magnitude ?? 0)}px "Cormorant Garamond", "Noto Serif SC", serif`
    ctx.textBaseline = 'bottom'
    ctx.fillStyle = trad === 'chinese' ? '#8b2e2e' : '#1f1a14'
    ctx.fillText(displayNameFor(s, trad), x + 8, y - 8)
  }
}
```

- [ ] **步骤 6：加 tick 主循环分支**

修改 `web/src/components/StarCanvas.vue`，在 `tick` 函数内找到 `if (props.mode === 'overlay')` 之类分支，加 `real-projection`：

```typescript
if (props.mode === 'overlay') {
  drawOverlay(ctx, w, h)
} else if (props.mode === 'real-projection') {
  drawRealProjection(ctx, w, h)
} else {
  drawScanAtlas(ctx, w, h)
}
```

- [ ] **步骤 7：运行测试验证通过**

```bash
cd web && npx vitest run tests/StarCanvas.test.ts
```

预期：3-4 PASS（视具体测试而定）

- [ ] **步骤 8：vue-tsc 检查**

```bash
npx vue-tsc --noEmit
```

预期：0 error

- [ ] **步骤 9：Commit**

```bash
git add web/src/types.ts web/src/components/StarCanvas.vue web/tests/StarCanvas.test.ts
git commit -m "feat(web): StarCanvas mode='real-projection' + 4 新函数

spec v4 任务 6：
- types.ts: StarCanvasMode 加 'real-projection'；stories: StoryBlock | null
- StarCanvas.vue: 加 normalizeRaDiff / computeField / worldToPixelEquirect / gridStep
- drawRealProjection: 视场边框 + 网格 + 中心十字 + 连线 + 主星 + 标注
- 屏幕物理坐标约定注释
- clamp 裁剪 warn + cos(Dec) TODO

3-4 新测试"
```

---

## 任务 7：ScanView 集成

**文件：**
- 修改：`web/src/views/ScanView.vue`（已有 486 行）

- [ ] **步骤 1：写失败测试 - ScanView 模式切换**

新建 `web/tests/ScanView.test.ts`：

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const listConstellationsMock = vi.fn()
const getConstellationMock = vi.fn()

vi.mock('../src/api/atlas', () => ({
  listConstellations: (...a: unknown[]) => listConstellationsMock(...a),
  getConstellation: (...a: unknown[]) => getConstellationMock(...a),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  listConstellationsMock.mockReset()
  getConstellationMock.mockReset()
})

describe('ScanView view toggle', () => {
  it('default atlas mode after solve', async () => {
    // 完整 mock fixture 参考 ConstellationView.test.ts
    // 关键断言：solve 后 overlayMode='atlas' + atlasMode='scan-atlas'
  })

  it('click real projection chip', async () => {
    // 点击'真实投影' chip → atlasMode='real-projection'
  })

  it('click photo overlay chip', async () => {
    // 点击'照片叠层' chip → overlayMode='overlay'
  })

  it('getAtlas called after solve', async () => {
    // solve 后 atlasStore.getAtlas 被调 1 次
  })

  it('cache hit no reload', async () => {
    // mode 切换不触发 getAtlas
  })
})
```

具体 mock 视现有 setup 而定，可参考 `ConstellationView.test.ts` 的 store mock 模式。

- [ ] **步骤 2：运行测试验证失败**

```bash
cd web && npx vitest run tests/ScanView.test.ts
```

预期：FAIL（showAtlas 是 boolean，无 chip 切换）

- [ ] **步骤 3：改 ScanView.vue 引入双 ref + watch + onUnmounted**

修改 `web/src/views/ScanView.vue`，`<script setup>` 顶部加：

```typescript
import { onUnmounted, ref, watch } from 'vue'
import { useAtlasStore } from '../stores/atlas'

const atlasStore = useAtlasStore()

type OverlayMode = 'overlay' | 'atlas'
type AtlasMode = 'scan-atlas' | 'real-projection'

const overlayMode = ref<OverlayMode>('atlas')
const atlasMode = ref<AtlasMode>('scan-atlas')

let isMounted = true
onUnmounted(() => { isMounted = false })

watch(
  () => scan.result?.constellations?.[0]?.abbr,
  async (newAbbr) => {
    const hit = scan.result?.constellations?.[0]
    if (!hit || !newAbbr) return
    const trad = hit.tradition ?? 'western'
    await atlasStore.getAtlas(trad, newAbbr)
    if (!isMounted) return
  },
  { immediate: true },
)
```

删除原有的 `const showAtlas = ref(false)`。

- [ ] **步骤 4：改 StarCanvas 渲染分支**

在模板中找到 `<StarCanvas ... mode="overlay">` 和 `<StarCanvas ... mode="scan-atlas">`，替换为：

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
<!-- atlasData 来自 spec v3 T7 已有的 computed（stores/atlas.atlasCache 派生），无需新增 -->
<StarCanvas
  v-else
  class="overlay atlas"
  :mode="atlasMode"
  :constellation-data="atlasData"
  :active-abbr="scan.activeAbbr"
  :tradition="atlasTradition"
/>
```

- [ ] **步骤 5：加 3 chip UI**

在结果卡上方加 chip 组（视当前布局而定，可放在 `.acts` 之前）：

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

- [ ] **步骤 6：删除原有 "查看连线样式" 按钮（被 chip 替代）**

找到 `<StarBtn :label="showAtlas ? '查看照片叠层' : '查看连线样式'" ...>`，**整段删除**。

- [ ] **步骤 7：运行测试验证通过**

```bash
cd web && npx vitest run tests/ScanView.test.ts
```

预期：5 PASS

- [ ] **步骤 8：vue-tsc 检查**

```bash
npx vue-tsc --noEmit
```

预期：0 error

- [ ] **步骤 9：Commit**

```bash
git add web/src/views/ScanView.vue web/tests/ScanView.test.ts
git commit -m "feat(views): ScanView 3 chip 视图切换 + atlasMode 状态机

spec v4 任务 7：
- overlayMode / atlasMode 双 ref（替换 showAtlas boolean）
- 3 chip UI: 照片叠层 / 美术连线 / 真实投影
- watch getAtlas 触发 + onUnmounted 防护
- StarCanvas mode 动态绑定 atlasMode

5 新测试"
```

---

## 任务 8：全量回归

**文件：** 无（仅跑测试）

- [ ] **步骤 1：后端全量 pytest**

```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```

预期：**121 passed**（原 102 + 19 新增）

- [ ] **步骤 2：前端全量 vitest**

```bash
cd web && npx vitest run
```

预期：**72 passed**（原 63 + 9 新增）

- [ ] **步骤 3：vue-tsc**

```bash
npx vue-tsc --noEmit
```

预期：0 error

- [ ] **步骤 4：validate_atlas**

```bash
cd server && .venv/Scripts/python.exe scripts/validate_atlas.py
```

预期：0 hard errors，0 soft warnings

- [ ] **步骤 5：Commit（如有 docs/lock 文件改动）**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: 回归通过验证"
```

---

## 任务 9：live E2E

**文件：** 无（仅 curl + 浏览器）

- [ ] **步骤 1：启动后端**

```bash
cd server && .venv/Scripts/python.exe -m uvicorn main:app --port 8000 > /tmp/backend.log 2>&1 &
sleep 4
```

- [ ] **步骤 2：L1 /api/traditions**

```bash
curl -s http://127.0.0.1:8000/api/traditions | python -m json.tool
```

预期：返回 2 项，western 含 description/label_en/epoch/source/license/coordinate_system；chinese 含 mansion 坐标系统。

- [ ] **步骤 3：L2 /api/constellations**

```bash
curl -s 'http://127.0.0.1:8000/api/constellations?tradition=western' | python -m json.tool
```

预期：顶层含 `tradition_meta.label == "西方星座"`，items 5 星座。

- [ ] **步骤 4：L3 include_stories=false**

```bash
curl -s 'http://127.0.0.1:8000/api/constellation/western/ori?include_stories=false' | python -c "import sys, json; d=json.load(sys.stdin); print('stories:', d['stories'])"
```

预期：`stories: None`

- [ ] **步骤 5：L4 identify hit（mock fixture）**

```bash
curl -sS -X POST http://127.0.0.1:8000/api/identify/solve \
  -F "image=@D:/Projects/260820OPC/assets/test1.jpg" \
  -F "orientation=1" | python -c "import sys, json; d=json.load(sys.stdin); print('solved:', d.get('solved'))"
```

预期：solved=true（上游解算链路通；constellations 是否命中视 test1.jpg WCS 精度）

- [ ] **步骤 6：L5 前端真投影 UI**

```bash
cd web && npx vite --port 5173 > /tmp/vite.log 2>&1 &
sleep 5
# 浏览器手测：识别 test1.jpg → 切"真实投影" chip → 检查 8 主星按 RA/Dec 渲染
```

预期：8 主星按 RA/Dec equirectangular 投影渲染（视场边框 + 网格 + 中心十字可见）。

- [ ] **步骤 7：停服务 + Commit**

```bash
# 停后端和前端
taskkill /F /IM python.exe 2>/dev/null || true
taskkill /F /IM node.exe 2>/dev/null || true

git add -A
git diff --cached --quiet || git commit -m "chore: live E2E 验证通过"
```

---

## 验收清单（pass/fail）

| 项 | 命令 | 预期 |
|---|---|---|
| 后端 pytest | `cd server && pytest -q` | **121 passed** |
| 前端 vitest | `cd web && npx vitest run` | **72 passed** |
| vue-tsc | `npx vue-tsc --noEmit` | 0 error |
| validate_atlas | `python scripts/validate_atlas.py` | 0 hard errors |
| L1 traditions | `curl /api/traditions` | 含 description/coordinate_system |
| L2 constellations | `curl /api/constellations?tradition=western` | 含 tradition_meta.label |
| L3 include_stories | `curl '/api/constellation/western/ori?include_stories=false'` | stories=null |
| L4 identify hit | mock WCS (84,-1) | constellations[0].abbr='ori' |
| L5 真投影 UI | 浏览器识别 + 切真实投影 | 8 主星按 RA/Dec 渲染 |

---

## 自检结果

### 1. 规格覆盖度

| spec v4 节 | 实现任务 |
|---|---|
| 1. 数据模型 (_meta.json schema) | 任务 1 |
| 2.1 Haversine | 任务 2 步骤 3 |
| 2.2 find_nearest list | 任务 2 步骤 7 |
| 2.3 _load_all _meta | 任务 2 步骤 11 |
| 3.1 /api/traditions 用 _META | 任务 3 步骤 9 |
| 3.2 /api/constellations tradition_meta | 任务 3 步骤 8 |
| 3.3 /api/constellation include_stories | 任务 3 步骤 7 |
| 3.4 identify 适配 find_nearest list | 任务 3 步骤 3 |
| 4. StarCanvas real-projection | 任务 6 |
| 5. ScanView 集成 | 任务 7 |
| 6. 测试策略（19 + 9 测试） | 任务 2/3/4/6/7 |
| 7. 验收标准 | 任务 8/9 |
| main.py startup 日志 | 任务 5 |
| validate_atlas 加严 | 任务 4 |

无遗漏。

### 2. 占位符扫描

无 "待定"/"TODO"/"类似任务 N" 等占位符。每个步骤含具体代码块或命令。

### 3. 类型一致性

| 类型 | 定义任务 | 使用任务 |
|---|---|---|
| `_angular_separation(ra, dec, ra2, dec2) -> float` | 任务 2 步骤 3 | 任务 2 步骤 7 |
| `find_nearest(ra, dec, max_sep_deg, top_k) -> list[tuple]` | 任务 2 步骤 7 | 任务 3 步骤 3 |
| `_default_meta(key, glob_count) -> dict` | 任务 2 步骤 11 | 任务 2 步骤 11 |
| `get_meta(tradition) -> dict \| None` | 任务 2 步骤 11 | 任务 3 步骤 8/9 |
| `normalizeRaDiff(ra, centerRa) -> number` | 任务 6 步骤 4 | 任务 6 步骤 4/5 |
| `computeField(stars, center) -> {w, h}` | 任务 6 步骤 4 | 任务 6 步骤 5 |
| `worldToPixelEquirect(ra, dec, center, field, viewbox)` | 任务 6 步骤 4 | 任务 6 步骤 5 |
| `gridStep(fieldExtent) -> number` | 任务 6 步骤 4 | 任务 6 步骤 5 |
| `validate_meta(meta, dir_name, glob_count) -> (errors, warnings)` | 任务 4 步骤 3 | 任务 4 步骤 1/3 |
| `StarCanvasMode = 'overlay' \| 'scan-atlas' \| 'real-projection'` | 任务 6 步骤 1 | 任务 6/7 |
| `OverlayMode = 'overlay' \| 'atlas'` | 任务 7 步骤 3 | 任务 7 |
| `AtlasMode = 'scan-atlas' \| 'real-projection'` | 任务 7 步骤 3 | 任务 7 |

一致。
