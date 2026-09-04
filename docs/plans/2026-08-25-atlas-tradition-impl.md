# Atlas Tradition 架构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把星座数据从 5 个西方星座的硬编码扩展为"按 tradition 目录自动发现"的多体系架构，支持西方 88 + 中国二十八宿/三垣 数据补齐的横向扩展；识别路径按 wcs 中心反查代替写死猎户；UI 加 tradition 切换 chips；星点常驻标注。

**架构：** 单源数据（`server/data/traditions/{tradition}/{abbr}.json`）+ 后端 lazy-but-startup-loaded 服务（`services.traditions.py`）+ 前端 store 按 tradition 缓存 + UI chips 切换 + StarCanvas labels。

**技术栈：**
- 后端：Python 3.13 / FastAPI / pytest / pathlib + json
- 前端：Vue 3 + Pinia + TypeScript + Vitest + vue-tsc
- 数据：纯 JSON（含 ra/dec/center/stories 内嵌）
- 现有依赖（不引入新库）

---

## 文件结构

### 创建

| 路径 | 职责 |
|---|---|
| `server/data/traditions/western/ori.json` | 猎户座完整数据 |
| `server/data/traditions/western/sco.json` | 天蝎座完整数据 |
| `server/data/traditions/western/cyg.json` | 天鹅座完整数据 |
| `server/data/traditions/western/leo.json` | 狮子座完整数据 |
| `server/data/traditions/western/and.json` | 仙女座完整数据 |
| `server/data/traditions/chinese/.gitkeep` | 中国 tradition 空目录占位 |
| `server/services/traditions.py` | tradition 单源加载 + 自动发现 + 反查 + 星表构建 |
| `server/scripts/validate_atlas.py` | 数据校验脚本（CI 集成预备） |
| `server/tests/test_traditions.py` | traditions 服务单测 |
| `server/tests/test_build_star_catalog.py` | 星表去重单测 |
| `server/tests/test_constellations_router.py` | 三个新端点单测 |
| `web/src/components/AtlasTraditionTabs.vue` | tradition 切换 chips 组件 |
| `web/tests/atlas.api.test.ts` | atlas API client 测试 |
| `web/tests/atlas.store.tradition.test.ts` | atlas store tradition 维度测试 |
| `web/tests/StarCanvas.label.test.ts` | StarCanvas labels 测试 |

### 修改

| 路径 | 改动 |
|---|---|
| `server/main.py` | startup event 调用 `traditions._load_all()` |
| `server/routers/constellation.py` | 路径 `{abbr}` → `{tradition}/{abbr}` |
| `server/routers/constellations.py` | 加 `tradition` query 参数（必填） |
| `server/routers/identify.py` | 写死猎户 → `find_nearest` + `build_star_catalog` |
| `server/services/astrometry.py` | `_BAYER_INDEX` → `traditions.build_star_catalog()` |
| `server/tests/test_identify.py` | 删 ori 假定 + 加 visible_stars 断言 + 反查测试 |
| `web/src/api/atlas.ts` | 加 `listTraditions`；`listConstellations`/`getConstellation` 加 tradition 参数 |
| `web/src/stores/atlas.ts` | `currentTradition` + `itemsByTradition` + `atlasCache` (key `${trad}/${abbr}`) |
| `web/src/types.ts` | 加 `TraditionListItem` + 扩展 `ConstellationAtlas` |
| `web/src/views/ConstellationView.vue` | 顶部加 `<AtlasTraditionTabs>` + 空状态 |
| `web/src/views/ScanView.vue` | 删静态 `import orionData`；用 `useAtlasStore.getAtlas(hit.tradition, hit.abbr)` |
| `web/src/components/AtlasStoryStatic.vue` | 删 `atlasStories.json` import；改读 `atlasStore.atlasCache[...].stories`；加空状态 |
| `web/src/components/StarCanvas.vue` | 新增 `<g class="labels">` + `tradition` prop + `displayNameFor` 兜底 |
| `web/tests/AtlasStoryStatic.test.ts` | mock store 提供 constellation.stories |
| `web/tests/ConstellationView.test.ts` | 加 chips 切换测试 + 空状态测试 |

### 删除

| 路径 | 原因 |
|---|---|
| `server/data/constellations.json` | 拆成 5 个 `traditions/western/*.json` |
| `server/data/preset_stories.json` | stories 内嵌到各 constellation JSON |
| `server/data/bayer_index.json` | RA/Dec/name/magnitude 已搬入 stars.* 字段 |
| `web/src/data/constellations.json` | 前端走 API |
| `web/src/data/atlas_stories.json` | stories 内嵌 |
| `web/src/data/`（整个目录）| 上两项后空目录 |

---

## 任务依赖

```
任务 1 (数据迁移+删旧)
  ↓
任务 2 (services.traditions.py + test_traditions + test_build_star_catalog)
  ↓
任务 3 (validate_atlas.py 脚本)
  ↓
任务 4 (端点改造 + test_constellations_router)
  ↓
任务 5 (identify.py 反查重写 + test_identify 改写)
  ↓
任务 6 (main.py startup event + 全量回归)
  ↓
任务 7 (前端 api/atlas.ts)
  ↓
任务 8 (前端 stores/atlas.ts)
  ↓
任务 9 (前端 types.ts 扩展)
  ↓
任务 10 (AtlasTraditionTabs + ConstellationView 集成 + 空状态)
  ↓
任务 11 (ScanView 改 API)
  ↓
任务 12 (AtlasStoryStatic 改读 stories + 空状态)
  ↓
任务 13 (StarCanvas labels + 兜底)
  ↓
任务 14 (删 web/src/data/ + 全量回归 + live 实测)
```

---

## 任务 1：数据迁移 + 删除旧文件

**文件：**
- 创建：`server/data/traditions/western/ori.json`
- 创建：`server/data/traditions/western/sco.json`
- 创建：`server/data/traditions/western/cyg.json`
- 创建：`server/data/traditions/western/leo.json`
- 创建：`server/data/traditions/western/and.json`
- 创建：`server/data/traditions/chinese/.gitkeep`
- 删除：`server/data/constellations.json`
- 删除：`server/data/preset_stories.json`
- 删除：`server/data/bayer_index.json`

- [ ] **步骤 1.1：创建 `server/data/traditions/western/ori.json`**

```json
{
  "abbr": "ori",
  "name": "猎户座",
  "latin": "Orion",
  "season": "冬季",
  "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
  "viewBox": { "width": 500, "height": 300 },
  "center": { "ra": 86.0, "dec": -2.0 },
  "stars": {
    "betelgeuse": {"x": 144, "y": 62,  "bayer": "α Ori",      "name": "Betelgeuse", "name_zh": "参宿四", "magnitude": 0.42, "ra": 88.79, "dec":  7.41, "label": true},
    "bellatrix":  {"x": 330, "y": 78,  "bayer": "γ Ori",      "name": "Bellatrix",  "name_zh": "参宿五", "magnitude": 1.64, "ra": 81.28, "dec":  6.35, "label": true},
    "meissa":     {"x": 282, "y": 28,  "bayer": "λ Ori",      "name": "Meissa",     "name_zh": "觜宿一", "magnitude": 3.39, "ra": 83.78, "dec":  9.93, "label": false},
    "alnitak":    {"x": 260, "y": 148, "bayer": "ζ Ori",      "name": "Alnitak",    "name_zh": "参宿一", "magnitude": 1.74, "ra": 85.19, "dec": -1.94, "label": true},
    "alnilam":    {"x": 280, "y": 158, "bayer": "ε Ori",      "name": "Alnilam",    "name_zh": "参宿二", "magnitude": 1.69, "ra": 84.05, "dec": -1.20, "label": true},
    "mintaka":    {"x": 300, "y": 168, "bayer": "δ Ori",      "name": "Mintaka",    "name_zh": "参宿三", "magnitude": 2.23, "ra": 83.00, "dec": -0.30, "label": true},
    "saiph":      {"x": 228, "y": 246, "bayer": "κ Ori",      "name": "Saiph",      "name_zh": "参宿六", "magnitude": 2.06, "ra": 86.94, "dec": -9.67, "label": false},
    "rigel":      {"x": 334, "y": 238, "bayer": "β Ori",      "name": "Rigel",      "name_zh": "参宿七", "magnitude": 0.13, "ra": 78.63, "dec": -8.20, "label": true}
  },
  "lines": [
    ["betelgeuse","bellatrix"], ["meissa","betelgeuse"], ["meissa","bellatrix"],
    ["betelgeuse","alnitak"], ["bellatrix","mintaka"], ["mintaka","alnilam"],
    ["alnilam","alnitak"], ["mintaka","rigel"], ["alnitak","saiph"], ["rigel","saiph"]
  ],
  "mansion": null,
  "asterism_id": null,
  "stories": {
    "myth": {
      "epic":  {"title": "", "paragraphs": []},
      "chat":  {"title": "", "paragraphs": []},
      "brief": {"title": "猎户座 · 神话概念", "paragraphs": [
        "猎户座（Orion），全天 88 星座之一，冬季代表星座。位置：赤纬 -10° 到 +20°。",
        "中国星官：参宿（西方白虎）。希腊神话主角：俄里翁（Orion），海神波塞冬之子，猎手。",
        "与天蝎座关系：被天蝎蛰死；二者分两冬夏，永不相见。",
        "象征：猎户、勇士、武士。"
      ]}
    },
    "science": {
      "epic":  {"title": "", "paragraphs": []},
      "chat":  {"title": "", "paragraphs": []},
      "brief": {"title": "猎户座 · 天文参数", "paragraphs": [
        "猎户座（Orion）。赤经 5h35m，赤纬 -5°23′。面积 594 平方度。",
        "主星：参宿四（α Ori，Betelgeuse）、参宿七（β Ori，Rigel）、参宿五（γ Ori，Bellatrix）、参宿一（ζ Ori）、参宿二（ε Ori）、参宿三（δ Ori）。",
        "深空天体：M42 猎户大星云（距 1344 光年）、M43、M78。",
        "最佳观测月份：12 月 - 3 月。"
      ]}
    }
  }
}
```

> **MVP 故事只写 2 套**（`brief`），`epic` + `chat` 维度空数组，前端走空状态。后续第二期补齐。

- [ ] **步骤 1.2：创建 `sco.json`（同 schema）**

参考 `sco: Scorpius` 已有数据：
- stars: graffias/dschubba/antares/zeta/shaula/sargas（6 颗，antares/shaula/dschubba `label: true`）
- lines: 5 条
- center: { ra: 247, dec: -26 }
- brief stories 含 2 套（myth/science 各 `brief`）

- [ ] **步骤 1.3：创建 `cyg.json`**

- stars: deneb/sadr/gienah/delta/albireo（5 颗，deneb/albireo/sadr `label: true`）
- lines: 4 条
- center: { ra: 312, dec: 42 }
- brief stories 含 2 套

- [ ] **步骤 1.4：创建 `leo.json`**

- stars: rasalas/algieba/regulus/zosma/chertan/denebola（6 颗，regulus/denebola `label: true`）
- lines: 5 条
- center: { ra: 162, dec: 17 }
- brief stories 含 2 套

- [ ] **步骤 1.5：创建 `and.json`**

- stars: alpheratz/delta/mirach/almach（4 颗，alpheratz/mirach `label: true`）
- lines: 3 条
- center: { ra: 12, dec: 38 }
- brief stories 含 2 套

- [ ] **步骤 1.6：创建 `server/data/traditions/chinese/.gitkeep`**

```bash
mkdir -p server/data/traditions/chinese
touch server/data/traditions/chinese/.gitkeep
```

- [ ] **步骤 1.7：删除旧数据文件**

```bash
git rm server/data/constellations.json
git rm server/data/preset_stories.json
git rm server/data/bayer_index.json
```

- [ ] **步骤 1.8：验证 JSON 解析**

```bash
cd server && python -c "
import json
from pathlib import Path
for p in Path('data/traditions/western').glob('*.json'):
    d = json.loads(p.read_text(encoding='utf-8'))
    assert d['abbr'] == p.stem, f'{p}: abbr != filename'
    assert 'center' in d and 'ra' in d['center'] and 'dec' in d['center']
    for s in d['stars'].values():
        assert 'ra' in s and 'dec' in s and 'magnitude' in s and 'label' in s
        assert isinstance(s['label'], bool)
    print(f'OK {p.name}')
"
```

预期：5 行 OK

- [ ] **步骤 1.9：Commit**

```bash
git add server/data/traditions/
git commit -m "feat(atlas): 数据迁移到 traditions/ 目录 + 删 4 个旧文件

5 个西方星座拆成 server/data/traditions/western/{ori,sco,cyg,leo,and}.json
每文件含完整 stars/lines/center/ra-dec/label + 内嵌 brief stories（2 套）

chinese/ 空目录占位，第二期补 28 宿 + 三垣

删除：
- server/data/constellations.json（已拆）
- server/data/preset_stories.json（stories 已内嵌）
- server/data/bayer_index.json（RA/Dec 等已搬入 stars.*）

MVP 故事只写 2 套（brief），其他维度空数组；前端走空状态"
```

---

## 任务 2：services.traditions.py + 单测

**文件：**
- 创建：`server/services/traditions.py`
- 创建：`server/tests/test_traditions.py`
- 创建：`server/tests/test_build_star_catalog.py`

- [ ] **步骤 2.1：写 `test_traditions.py`（先写测试）**

```python
"""traditions 服务单测。

覆盖：
- 自动发现（western + chinese）
- fail-soft（坏 JSON 跳过）
- abbr != filename 跳过
- list_traditions / list_constellations / get_constellation
- find_nearest 反查 + RA 跨零度
- build_star_catalog 去重
"""
import json
from pathlib import Path
import pytest

from services import traditions


@pytest.fixture
def tmp_traditions(monkeypatch, tmp_path):
    """临时替换 _DATA_ROOT，写入 mock traditions 数据。"""
    root = tmp_path / "traditions"
    (root / "western").mkdir(parents=True)
    (root / "chinese").mkdir()
    monkeypatch.setattr(traditions, "_DATA_ROOT", root)
    monkeypatch.setattr(traditions, "_DATA", {})
    return root


def _write(root, tradition, abbr, entry):
    p = root / tradition / f"{abbr}.json"
    p.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


ORION_MOCK = {
    "abbr": "ori", "name": "猎户座", "latin": "Orion",
    "center": {"ra": 86.0, "dec": -2.0},
    "stars": {
        "betelgeuse": {"x": 144, "y": 62, "name": "Betelgeuse", "name_zh": "参宿四",
                       "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True}
    },
    "lines": [],
}


def test_scan_loads_western_and_chinese(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    _write(tmp_traditions, "chinese", "shen", {**ORION_MOCK, "abbr": "shen", "latin": ""})
    traditions._load_all()
    assert set(traditions._DATA.keys()) == {"western", "chinese"}
    assert traditions._DATA["western"]["ori"]["name"] == "猎户座"


def test_load_skips_bad_json(tmp_traditions, caplog):
    (tmp_traditions / "western" / "bad.json").write_text("{not json", encoding="utf-8")
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    with caplog.at_level("ERROR"):
        traditions._load_all()
    assert "ori" in traditions._DATA["western"]
    assert "bad" not in traditions._DATA["western"]


def test_load_skips_abbr_mismatch(tmp_traditions, caplog):
    _write(tmp_traditions, "western", "ori", {**ORION_MOCK, "abbr": "wrong"})
    with caplog.at_level("ERROR"):
        traditions._load_all()
    assert "ori" not in traditions._DATA["western"]


def test_get_constellation_returns_full_entry(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    result = traditions.get_constellation("western", "ori")
    assert result is not None
    assert result["ok"] is True
    assert result["tradition"] == "western"
    assert "stars" in result


def test_get_constellation_missing_returns_none(tmp_traditions):
    assert traditions.get_constellation("western", "xxx") is None


def test_list_constellations_filters_by_tradition(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    _write(tmp_traditions, "chinese", "shen", {**ORION_MOCK, "abbr": "shen", "latin": ""})
    items = traditions.list_constellations("western")
    assert [i["abbr"] for i in items] == ["ori"]
    assert items[0]["tradition"] == "western"
    assert items[0]["star_count"] == 1
    assert items[0]["has_stories"] is False


def test_find_nearest_returns_closest(tmp_traditions):
    orion_near = {**ORION_MOCK, "center": {"ra": 86.0, "dec": -2.0}}
    orion_far = {**ORION_MOCK, "abbr": "cyg", "center": {"ra": 312.0, "dec": 42.0}}
    _write(tmp_traditions, "western", "ori", orion_near)
    _write(tmp_traditions, "western", "cyg", orion_far)
    trad, abbr, sep = traditions.find_nearest(85.5, -2.5)
    assert trad == "western"
    assert abbr == "ori"
    assert sep < 1.0


def test_find_nearest_respects_max_separation(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)  # center (86, -2)
    assert traditions.find_nearest(300, -60) is None  # far away


def test_find_nearest_handles_ra_wrap(tmp_traditions):
    """RA 跨 0°/360° 时取最近一侧。
    center (359, 0), query (1, 0): 角距应约 2°，不应是 358°。"""
    near_wrap = {**ORION_MOCK, "abbr": "wrap", "center": {"ra": 359.0, "dec": 0.0}}
    _write(tmp_traditions, "western", "ori", near_wrap)
    trad, abbr, sep = traditions.find_nearest(1.0, 0.0)
    assert abbr == "wrap"
    assert sep < 5.0


def test_list_traditions_returns_label_and_count(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    items = traditions.list_traditions()
    by_key = {i["key"]: i for i in items}
    assert by_key["western"]["label"] == "西方星座"
    assert by_key["western"]["count"] == 1
```

- [ ] **步骤 2.2：跑测试确认失败**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_traditions.py -v
```

预期：ModuleNotFoundError: No module named 'services.traditions'

- [ ] **步骤 2.3：实现 `server/services/traditions.py`**

```python
"""tradition 数据自动发现 + 加载。

单源：server/data/traditions/{tradition_key}/{abbr}.json
- 一级子目录名 = tradition key
- 文件名 (去 .json) = abbr
- startup event 加载（main.py 调用 _load_all()）
- fail-soft：坏 JSON / abbr 不匹配跳过
"""
from pathlib import Path
from threading import Lock
import json
import logging
import math

_DATA_ROOT: Path = Path(__file__).parent.parent / "data" / "traditions"
_DATA: dict[str, dict[str, dict]] = {}
_LOAD_LOCK = Lock()
_LOG = logging.getLogger(__name__)


def _load_all() -> None:
    """启动时由 main.py 显式调用；内部带 lock 防重复、保持 idempotent。

    double-check locking：无锁快速路径检查 `_DATA`，避免热路径争锁。
    """
    if _DATA:  # 无锁快速路径
        return
    with _LOAD_LOCK:
        if _DATA:  # 拿锁后再检查
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
    """为 identify.py WCS 投影构造标准星表。

    按 (round(ra, 2), round(dec, 2)) 去重；多 tradition 同星（参宿四 在 western/ori 与 chinese/shen RA/Dec 相同）只保留首个。

    去重精度：`round(..., 2)` ≈ 0.01° ≈ 36″。两颗独立星角距 < 36″ 会被误合并。
    MVP 5 星座不含密集星团可接受。第二期可改 `round(..., 3)` ≈ 3.6″ 或加 magnitude；
    进一步可改用 Hipparcos/HIP 号作为去重 key。
    """
    _load_all()
    catalog: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for trad_key, consts in _DATA.items():
        for abbr, c in consts.items():
            for _star_key, star in c.get("stars", {}).items():
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

    - RA 跨 0°/360°：`(dra + 180) % 360 - 180`
    - cos(dec) 中点近似，|dec| < 60° 误差 < 5%

    TODO (高赤纬精度问题): 高赤纬 (小熊座 Dec ≈ 85°) 时 cos(Dec) → 0，
    RA 微小扰动被过度压缩，欧氏距离近似畸变。第二期加小熊/大熊/仙后等极区
    星座时切 3D 向量点积: cos θ = sin δ₁ sin δ₂ + cos δ₁ cos δ₂ cos Δα。
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

- [ ] **步骤 2.4：跑测试确认通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_traditions.py -v
```

预期：10 passed

- [ ] **步骤 2.5：写 `test_build_star_catalog.py`**

```python
"""build_star_catalog 单测。"""
import json
import pytest

from services import traditions


@pytest.fixture
def tmp_traditions(monkeypatch, tmp_path):
    root = tmp_path / "traditions"
    (root / "western").mkdir(parents=True)
    (root / "chinese").mkdir()
    monkeypatch.setattr(traditions, "_DATA_ROOT", root)
    monkeypatch.setattr(traditions, "_DATA", {})
    return root


def _write(root, tradition, abbr, entry):
    (root / tradition / f"{abbr}.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8"
    )


def test_dedupes_stars_by_ra_dec(tmp_traditions):
    """参宿四在 western/ori 和 chinese/shen RA/Dec 相同，应只保留一次。"""
    star = {"x": 144, "y": 62, "name": "Betelgeuse", "name_zh": "参宿四",
            "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True}
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star},
    })
    _write(tmp_traditions, "chinese", "shen", {
        "abbr": "shen", "name": "参宿", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star},  # 同一组 RA/Dec
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    assert catalog[0]["name"] == "Betelgeuse"


def test_returns_all_required_fields(tmp_traditions):
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": {
            "x": 144, "y": 62, "bayer": "α Ori", "name": "Betelgeuse",
            "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True,
        }},
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    s = catalog[0]
    for field in ("bayer", "name", "name_zh", "magnitude", "ra", "dec", "constellation", "tradition"):
        assert field in s
    assert s["constellation"] == "ori"
    assert s["tradition"] == "western"
```

- [ ] **步骤 2.6：跑测试通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_build_star_catalog.py -v
```

预期：2 passed

- [ ] **步骤 2.7：Commit**

```bash
git add server/services/traditions.py server/tests/test_traditions.py server/tests/test_build_star_catalog.py
git commit -m "feat(services): traditions 自动发现 + 反查 + 星表去重

- _load_all 启动加载；threading.Lock 线程安全
- fail-soft：坏 JSON / abbr 不匹配 logger.error + 跳过
- find_nearest: RA 跨 0°/360° 用 (dra+180)%360-180
- build_star_catalog: 按 (round(ra,2), round(dec,2)) 去重，处理多 tradition 同星

10 + 2 = 12 个新单测"
```

---

## 任务 3：validate_atlas.py 数据校验脚本

**文件：**
- 创建：`server/scripts/validate_atlas.py`

- [ ] **步骤 3.1：实现 validate_atlas.py**

```python
"""Atlas 数据校验脚本。

第一阶段末尾手动跑一次（5 文件完整）；第二期起集成 CI。
硬性校验：abbr 一致、center/stars 必填字段、lines 合法、stories 6 维 title 存在
软性校验：center 到 stars 平均角距 < 15°（warning 不报错）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "traditions"
HARD_ERRORS = 0
SOFT_WARNINGS = 0
NARRATIVES = ("epic", "chat", "brief")
VIEWS = ("myth", "science")


def _angular_sep_deg(ra1, dec1, ra2, dec2) -> float:
    import math
    dra = (ra1 - ra2 + 180) % 360 - 180
    dra *= math.cos(math.radians((dec1 + dec2) / 2))
    ddec = dec1 - dec2
    return math.sqrt(dra * dra + ddec * ddec)


def check_file(json_path: Path) -> None:
    global HARD_ERRORS, SOFT_WARNINGS
    abbr_stem = json_path.stem
    try:
        entry = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"HARD {json_path}: JSON parse failed: {e}")
        HARD_ERRORS += 1
        return

    if entry.get("abbr") != abbr_stem:
        print(f"HARD {json_path}: abbr={entry.get('abbr')!r} != filename={abbr_stem!r}")
        HARD_ERRORS += 1

    center = entry.get("center")
    if not center or "ra" not in center or "dec" not in center:
        print(f"HARD {json_path}: missing center.{{ra,dec}}")
        HARD_ERRORS += 1

    stars = entry.get("stars", {})
    star_keys = set(stars.keys())
    for sk, s in stars.items():
        for f in ("ra", "dec", "magnitude", "label"):
            if f not in s:
                print(f"HARD {json_path}: stars.{sk} missing {f}")
                HARD_ERRORS += 1
        if "label" in s and not isinstance(s["label"], bool):
            print(f"HARD {json_path}: stars.{sk}.label not bool")
            HARD_ERRORS += 1

    for line in entry.get("lines", []):
        if len(line) != 2 or line[0] not in star_keys or line[1] not in star_keys:
            print(f"HARD {json_path}: line {line!r} uses unknown star key")
            HARD_ERRORS += 1

    stories = entry.get("stories", {})
    for view in VIEWS:
        if view not in stories:
            print(f"HARD {json_path}: stories missing view={view}")
            HARD_ERRORS += 1
            continue
        for narr in NARRATIVES:
            v = stories[view].get(narr, {})
            if "title" not in v:
                print(f"HARD {json_path}: stories.{view}.{narr} missing title")
                HARD_ERRORS += 1

    if center and stars:
        avg_sep = sum(
            _angular_sep_deg(center["ra"], center["dec"], s["ra"], s["dec"])
            for s in stars.values()
        ) / len(stars)
        if avg_sep > 15.0:
            print(f"WARN {json_path}: center to stars avg sep {avg_sep:.1f}° > 15°")
            SOFT_WARNINGS += 1

    print(f"OK {json_path.name}")


def main() -> int:
    for trad_dir in sorted(ROOT.iterdir()):
        if not trad_dir.is_dir():
            continue
        for json_file in sorted(trad_dir.glob("*.json")):
            check_file(json_file)
    print(f"\nSummary: {HARD_ERRORS} hard errors, {SOFT_WARNINGS} soft warnings")
    return 1 if HARD_ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步骤 3.2：跑脚本验证 5 文件**

```bash
cd server && python scripts/validate_atlas.py
```

预期：
```
OK and.json
OK cyg.json
OK leo.json
OK ori.json
OK sco.json

Summary: 0 hard errors, 0 soft warnings
```

- [ ] **步骤 3.3：Commit**

```bash
git add server/scripts/validate_atlas.py
git commit -m "feat(scripts): validate_atlas.py 数据校验

硬性校验：abbr 一致、center/stars 必填、lines 合法、stories 6 维 title
软性校验：center 到 stars 平均角距 < 15°（warning）

第一阶段末尾手动跑；第二期起集成 CI"
```

---

## 任务 4：端点改造

**文件：**
- 修改：`server/routers/constellations.py`
- 修改：`server/routers/constellation.py`
- 创建：`server/tests/test_constellations_router.py`

- [ ] **步骤 4.1：写 `test_constellations_router.py`**

```python
"""3 个新端点单测。"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_traditions_endpoint():
    r = client.get("/api/traditions")
    assert r.status_code == 200
    by_key = {i["key"]: i for i in r.json()}
    assert "western" in by_key
    assert "chinese" in by_key
    assert by_key["western"]["count"] >= 5


def test_constellations_with_query():
    r = client.get("/api/constellations?tradition=western")
    assert r.status_code == 200
    body = r.json()
    assert body["tradition"] == "western"
    abbrs = {i["abbr"] for i in body["items"]}
    assert "ori" in abbrs


def test_constellations_missing_tradition():
    r = client.get("/api/constellations")
    assert r.status_code == 422


def test_constellation_detail_ok():
    r = client.get("/api/constellation/western/ori")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["abbr"] == "ori"
    assert body["tradition"] == "western"
    assert "stars" in body


def test_constellation_detail_404():
    r = client.get("/api/constellation/western/xxx")
    assert r.status_code == 404
    assert r.json()["code"] == "CONSTELLATION_NOT_FOUND"
```

- [ ] **步骤 4.2：跑测试确认失败**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_constellations_router.py -v
```

预期：404 on `/api/constellation/western/ori`，422 on `/api/constellations` (因未加 query 校验)

- [ ] **步骤 4.3：修改 `server/routers/constellations.py`**

```python
"""Constellation list endpoint.

GET /api/constellations?tradition=western — required query param.
"""
from fastapi import APIRouter, Query

from services.traditions import list_constellations

router = APIRouter(prefix="/api/constellations", tags=["constellations"])


@router.get("")
async def constellations(tradition: str = Query(..., min_length=1)):
    items = list_constellations(tradition)
    return {"tradition": tradition, "items": items}
```

- [ ] **步骤 4.4：重写 `server/routers/constellation.py`**

```python
"""Constellation detail endpoint.

GET /api/constellation/{tradition}/{abbr} — 404 if not found.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.traditions import get_constellation

router = APIRouter(prefix="/api/constellation", tags=["constellation"])


@router.get("/{tradition}/{abbr}")
async def constellation(tradition: str, abbr: str):
    result = get_constellation(tradition, abbr)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "code": "CONSTELLATION_NOT_FOUND",
                "message": "未收录此星座",
                "advice": "请检查 tradition 与 abbr，或在后续版本加入",
            },
        )
    return result
```

- [ ] **步骤 4.5：增加 `/api/traditions` 端点**

新建 `server/routers/traditions.py`：

```python
"""Traditions list endpoint.

GET /api/traditions — returns [{key, label, count}, ...]
"""
from fastapi import APIRouter

from services.traditions import list_traditions

router = APIRouter(prefix="/api/traditions", tags=["traditions"])


@router.get("")
async def traditions():
    return list_traditions()
```

- [ ] **步骤 4.6：在 `server/main.py` 注册新路由**

```python
from routers.traditions import router as traditions_router
app.include_router(traditions_router)
```

- [ ] **步骤 4.7：跑测试通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_constellations_router.py -v
```

预期：5 passed

- [ ] **步骤 4.8：Commit**

```bash
git add server/routers/constellations.py server/routers/constellation.py server/routers/traditions.py server/main.py server/tests/test_constellations_router.py
git commit -m "feat(routers): 端点改造 + /api/traditions 新增

- /api/constellations?tradition=X（query 必填）
- /api/constellation/{tradition}/{abbr}
- /api/traditions 新增
- 删旧 /api/constellations + /api/constellation/{abbr} 路径

5 个新单测"
```

---

## 任务 5：identify.py 反查重写

**文件：**
- 修改：`server/services/astrometry.py`
- 修改：`server/routers/identify.py`
- 修改：`server/tests/test_identify.py`

- [ ] **步骤 5.1：改 `server/services/astrometry.py`**

替换 `_BAYER_INDEX` 模块常量：

```diff
- # Bayer 索引：模块加载时从 server/data/bayer_index.json 读取（spec §4.2 单源）。
- _BAYER_INDEX: dict[str, dict] = json.loads(
-     Path(__file__).resolve().parents[1]
-     .joinpath("data/bayer_index.json")
-     .read_text(encoding="utf-8")
- )
```

为：模块顶部不动，改用 `build_star_catalog()`：

```python
def project_stars(wcs_header: dict, image_height: int, y_flip: bool = Y_FLIP) -> list[dict]:
    """从上游 wcs_header 投影所有 traditions 标准星 → 像素坐标。

    星表来自 services.traditions.build_star_catalog()，按 (RA, Dec) 去重。
    """
    from services.traditions import build_star_catalog
    wcs = WCS(fits.Header(_coerce_wcs_types(wcs_header)))
    catalog = build_star_catalog()
    out: list[dict] = []
    for entry in catalog:
        sky = SkyCoord(ra=entry["ra"] * u.deg, dec=entry["dec"] * u.deg, frame="icrs")
        x, y = wcs.world_to_pixel(sky)
        pixel_x = round(float(x), 2)
        pixel_y = round(float(y), 2)
        if y_flip:
            pixel_y = round(image_height - 1 - pixel_y, 2)
        out.append({
            "bayer": entry["bayer"],
            "name": entry["name"],
            "magnitude": entry["magnitude"],
            "pixel_x": pixel_x,
            "pixel_y": pixel_y,
            "constellation": entry["constellation"],
        })
    return out
```

- [ ] **步骤 5.2：改 `server/routers/identify.py` 的 `_to_solve_result`**

```diff
- hit_stars = sum(
-     1 for s in stars
-     if 0 <= s["pixel_x"] <= display_w and 0 <= s["pixel_y"] <= display_h
- )
-
- constellations: list[dict] = []
- if hit_stars >= 1:
-     constellations.append({
-         "abbr": "ori",
-         "name": "猎户座",
-         "latin": "Orion",
-         "confidence": round(hit_stars / len(_BAYER_INDEX), 3),
-         "hit_stars": hit_stars,
-         "total_bright_stars": len(_BAYER_INDEX),
-     })
+ from services.traditions import find_nearest, get_constellation
+
+ constellations: list[dict] = []
+ nearest = find_nearest(
+     float(wcs_header.get("CRVAL1", 0)),
+     float(wcs_header.get("CRVAL2", 0)),
+ )
+ if nearest is not None:
+     trad, abbr, sep_deg = nearest
+     entry = get_constellation(trad, abbr)
+     # ★ 过滤：只统计命中星座（abbr）的投影星，其他星座的可见星不计。
+     # projected_stars 来自 build_star_catalog()，含全 tradition 星点。
+     visible_stars = sum(
+         1 for s in stars
+         if s["constellation"] == abbr
+         and 0 <= s["pixel_x"] <= display_w
+         and 0 <= s["pixel_y"] <= display_h
+     )
+     constellations.append({
+         "tradition": trad,
+         "abbr": abbr,
+         "name": entry["name"],
+         "latin": entry.get("latin", ""),
+         "confidence": round(1 - sep_deg / 5.0, 3),
+         "visible_stars": visible_stars,
+         "total_bright_stars": len(entry["stars"]),
+     })
# 无命中: constinations = []，前端走 empty 分支
```

- [ ] **步骤 5.3：修改 `server/tests/test_identify.py`**

```python
"""identify 端点单测：覆盖反查 + visible_stars 语义。"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from main import app

client = TestClient(app)


def _mock_wcs():
    """模拟上游 solve 返回猎户区中心 (RA=86, Dec=-2)。"""
    return {
        "wcs_header": {
            "CRVAL1": 86.0, "CRVAL2": -2.0,
            "CD1_1": -0.0003, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.0003,
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
        },
        "ra": 86.0, "dec": -2.0,
        "field_width": 5.0, "field_height": 5.0,
        "image_width": 3000, "image_height": 2000,
    }


@patch("services.astrometry._coerce_wcs_types", side_effect=lambda x: x)
@patch("routers.identify._call_upstream_solve")
def test_identify_returns_tradition_and_visible_stars(mock_solve, _mock):
    mock_solve.return_value = _mock_wcs()
    files = {"file": ("t.jpg", b"\xff" * 100, "image/jpeg")}
    r = client.post("/api/identify", files=files, data={"orientation": "1"})
    assert r.status_code == 200
    body = r.json()
    assert body["solved"] is True
    hits = body["constellations"]
    assert len(hits) >= 1
    h = hits[0]
    assert h["tradition"] == "western"
    assert h["abbr"] == "ori"
    assert "visible_stars" in h
    assert h["total_bright_stars"] == 8
    # ★ visible_stars 必须 <= projected_stars 中 abbr=="ori" 的总星数（8）
    # 不能含其他星座（如天鹅、仙女）的可见星
    assert h["visible_stars"] <= 8


@patch("services.astrometry._coerce_wcs_types", side_effect=lambda x: x)
@patch("routers.identify._call_upstream_solve")
def test_identify_returns_empty_when_far(mock_solve, _mock):
    far = {**_mock_wcs(), "wcs_header": {**_mock_wcs()["wcs_header"],
                                          "CRVAL1": 300.0, "CRVAL2": -60.0}}
    mock_solve.return_value = far
    files = {"file": ("t.jpg", b"\xff" * 100, "image/jpeg")}
    r = client.post("/api/identify", files=files, data={"orientation": "1"})
    body = r.json()
    if body["solved"]:
        assert body["constellations"] == []
```

> **注意**：实际 `_call_upstream_solve` mock 路径取决于项目已有结构；请按 `routers/identify.py` 当前实现调用名调整。

- [ ] **步骤 5.4：跑测试通过**

```bash
cd server && .venv/Scripts/python.exe -m pytest tests/test_identify.py -v
```

预期：2 passed（如有更多原有测试也通过）

- [ ] **步骤 5.5：Commit**

```bash
git add server/services/astrometry.py server/routers/identify.py server/tests/test_identify.py
git commit -m "refactor(identify): 写死猎户 → find_nearest 反查

- astrometry.py: _BAYER_INDEX → build_star_catalog()
- identify.py: hit_stars → visible_stars；新增 tradition/visible_stars 字段
- 删硬编码 ori"
```

---

## 任务 6：main.py startup event + 全量回归

**文件：**
- 修改：`server/main.py`

- [ ] **步骤 6.1：在 main.py 注册 startup event**

```python
@app.on_event("startup")
def _load_traditions():
    from services.traditions import _load_all
    _load_all()
```

- [ ] **步骤 6.2：跑全量后端测试**

```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```

预期：全绿（之前 88 + 任务 2/3/4/5 新增用例）

- [ ] **步骤 6.3：手动 live 验证**

```bash
# 启动后端
cd server && python -m uvicorn main:app --reload --port 8000 &
sleep 5

# 验证 traditions
curl http://127.0.0.1:8000/api/traditions
# 预期：[{"key":"western","label":"西方星座","count":5},{"key":"chinese","label":"中国古代星空","count":0}]

# 验证 list
curl 'http://127.0.0.1:8000/api/constellations?tradition=western'
# 预期：5 个星座

# 验证 detail
curl http://127.0.0.1:8000/api/constellation/western/ori
# 预期：猎户完整数据（含 stars/lines/stories/center）
```

- [ ] **步骤 6.4：Commit**

```bash
git add server/main.py
git commit -m "feat(main): startup event 加载 traditions"
```

---

## 任务 7：前端 api/atlas.ts

**文件：**
- 修改：`web/src/api/atlas.ts`
- 创建：`web/tests/atlas.api.test.ts`

- [ ] **步骤 7.1：写 `atlas.api.test.ts`**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listTraditions, listConstellations, getConstellation } from '../src/api/atlas'

describe('atlas api', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('listTraditions 命中', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => [{key: 'western', label: '西方星座', count: 5}],
    } as Response)
    const r = await listTraditions()
    expect(r.items[0].key).toBe('western')
  })

  it('listConstellations 传 tradition', async () => {
    const mock = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({tradition: 'western', items: [{abbr: 'ori', name: '猎户座'}]}),
    } as Response)
    await listConstellations('western')
    const url = mock.mock.calls[0][0] as string
    expect(url).toContain('tradition=western')
  })

  it('getConstellation 路径含 tradition 和 abbr', async () => {
    const mock = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ok: true, abbr: 'ori', stars: {}}),
    } as Response)
    await getConstellation('western', 'ori')
    const url = mock.mock.calls[0][0] as string
    expect(url).toBe('/api/constellation/western/ori')
  })
})
```

- [ ] **步骤 7.2：跑测试确认失败**

```bash
cd web && npx vitest run tests/atlas.api.test.ts
```

预期：FAIL — `listTraditions is not exported`

- [ ] **步骤 7.3：修改 `web/src/api/atlas.ts`**

```typescript
import type {
  AtlasListResponse,
  AtlasListItem,
  ConstellationAtlas,
  TraditionListItem,
  TraditionListResponse,
} from '../types'

export interface AtlasListResponseV2 {
  tradition: string
  items: AtlasListItem[]
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`API ${path} ${r.status}`)
  return (await r.json()) as T
}

export async function listTraditions(): Promise<TraditionListResponse> {
  const items = await get<TraditionListItem[]>('/api/traditions')
  return { items }
}

export async function listConstellations(tradition: string): Promise<AtlasListResponseV2> {
  return get<AtlasListResponseV2>(
    `/api/constellations?tradition=${encodeURIComponent(tradition)}`,
  )
}

export async function getConstellation(
  tradition: string,
  abbr: string,
): Promise<ConstellationAtlas> {
  return get<ConstellationAtlas>(
    `/api/constellation/${encodeURIComponent(tradition)}/${encodeURIComponent(abbr)}`,
  )
}
```

> 保留旧的 `listConstellations` 无参 / `getConstellation(abbr)` 单参接口若已存在前端使用——按 grep 结果迁移；若无人用则删除。

- [ ] **步骤 7.4：跑测试通过**

```bash
cd web && npx vitest run tests/atlas.api.test.ts
```

预期：3 passed

- [ ] **步骤 7.5：Commit**

```bash
git add web/src/api/atlas.ts web/tests/atlas.api.test.ts
git commit -m "feat(api/atlas): tradition 维度端点 + listTraditions 新增"
```

---

## 任务 8：前端 stores/atlas.ts

**文件：**
- 修改：`web/src/stores/atlas.ts`
- 创建：`web/tests/atlas.store.tradition.test.ts`

- [ ] **步骤 8.1：写 `atlas.store.tradition.test.ts`**

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../src/api/atlas', () => ({
  listTraditions: vi.fn(),
  listConstellations: vi.fn(),
  getConstellation: vi.fn(),
}))

import * as api from '../src/api/atlas'
import { useAtlasStore } from '../src/stores/atlas'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('atlas store tradition 维度', () => {
  it('loadTraditions 缓存后不再调 API', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [{key: 'western', label: '西方星座', count: 5}],
    })
    const store = useAtlasStore()
    await store.loadTraditions()
    await store.loadTraditions()
    expect(api.listTraditions).toHaveBeenCalledTimes(1)
  })

  it('setTradition 触发 list', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [{key: 'western', label: '西方星座', count: 5},
              {key: 'chinese', label: '中国古代星空', count: 0}],
    })
    vi.mocked(api.listConstellations).mockResolvedValue({
      tradition: 'chinese', items: [],
    })
    const store = useAtlasStore()
    await store.loadTraditions()
    await store.setTradition('chinese')
    expect(store.currentTradition).toBe('chinese')
    expect(api.listConstellations).toHaveBeenCalledWith('chinese')
  })

  it('getAtlas 缓存命中不调 API', async () => {
    vi.mocked(api.getConstellation).mockResolvedValue({
      ok: true, abbr: 'ori', stars: {},
    } as any)
    const store = useAtlasStore()
    await store.getAtlas('western', 'ori')
    await store.getAtlas('western', 'ori')
    expect(api.getConstellation).toHaveBeenCalledTimes(1)
  })

  it('currentItems 返回当前 tradition 的列表', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({items: []})
    vi.mocked(api.listConstellations)
      .mockResolvedValueOnce({tradition: 'western', items: [{abbr: 'ori'} as any]})
      .mockResolvedValueOnce({tradition: 'chinese', items: [{abbr: 'shen'} as any]})
    const store = useAtlasStore()
    await store.setTradition('western')
    await store.setTradition('chinese')
    expect(store.currentItems[0].abbr).toBe('shen')
  })
})
```

- [ ] **步骤 8.2：跑测试确认失败**

```bash
cd web && npx vitest run tests/atlas.store.tradition.test.ts
```

预期：FAIL — store 没有 currentTradition / setTradition

- [ ] **步骤 8.3：重写 `web/src/stores/atlas.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import type { AtlasListItem, ConstellationAtlas, TraditionListItem } from '../types'
import { listTraditions, listConstellations, getConstellation } from '../api/atlas'

export const useAtlasStore = defineStore('atlas', () => {
  const traditions = ref<TraditionListItem[]>([])
  const currentTradition = ref<string>('western')

  const itemsByTradition = ref<Record<string, AtlasListItem[]>>({})
  const atlasCache = ref<Record<string, ConstellationAtlas>>({}) // key: `${trad}/${abbr}`

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
    const r = await listConstellations(tradition)
    itemsByTradition.value = { ...itemsByTradition.value, [tradition]: r.items }
  }

  async function getAtlas(tradition: string, abbr: string): Promise<ConstellationAtlas> {
    const cacheKey = `${tradition}/${abbr}`
    if (atlasCache.value[cacheKey]) return atlasCache.value[cacheKey]
    const data = await getConstellation(tradition, abbr)
    atlasCache.value = { ...atlasCache.value, [cacheKey]: data }
    return data
  }

  const currentItems = computed<AtlasListItem[]>(
    () => itemsByTradition.value[currentTradition.value] ?? [],
  )

  return {
    traditions, currentTradition, itemsByTradition, atlasCache,
    currentItems, loadTraditions, setTradition, list, getAtlas,
  }
})
```

- [ ] **步骤 8.4：跑测试通过**

```bash
cd web && npx vitest run tests/atlas.store.tradition.test.ts
```

预期：4 passed

- [ ] **步骤 8.5：Commit**

```bash
git add web/src/stores/atlas.ts web/tests/atlas.store.tradition.test.ts
git commit -m "feat(stores/atlas): tradition 维度 + 缓存 key = trad/abbr"
```

---

## 任务 9：前端 types.ts 扩展

**文件：**
- 修改：`web/src/types.ts`

- [ ] **步骤 9.1：加 TraditionListItem 类型**

在 `types.ts` 加：

```typescript
export interface TraditionListItem {
  key: string
  label: string
  count: number
}

export interface TraditionListResponse {
  items: TraditionListItem[]
}
```

- [ ] **步骤 9.2：扩展 `AtlasListItem` 和 `ConstellationAtlas`**

```typescript
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
  tradition?: string        // ★ 新增
  star_count?: number       // ★ 新增（来自 list 端点）
  has_stories?: boolean     // ★ 新增（来自 list 端点）
}

export interface AtlasListResponse {
  ok?: boolean
  tradition?: string        // ★ 新增
  items: AtlasListItem[]
}

export interface ConstellationAtlas extends AtlasListItem {
  stars: Record<string, AtlasStar>
  lines?: AtlasLine[]
  viewBox?: { width: number; height: number }
  bright_stars_mag_lt_35?: number
  ok?: boolean
  center?: { ra: number; dec: number }   // ★ 新增
  mansion?: string | null                 // ★ 新增
  asterism_id?: string | null             // ★ 新增
  stories?: ConstellationStories         // ★ 新增
}

export interface ConstellationStories {
  [view: string]: {
    [narrative: string]: { title: string; paragraphs: string[] }
  }
}
```

并扩展 `AtlasStar`：

```typescript
export interface AtlasStar {
  x: number
  y: number
  bayer?: string
  name?: string
  name_zh?: string          // ★ 新增
  magnitude: number
  ra?: number               // ★ 新增
  dec?: number              // ★ 新增
  label?: boolean           // ★ 新增
}
```

- [ ] **步骤 9.3：跑 vue-tsc**

```bash
cd web && npx vue-tsc --noEmit
```

预期：0 error（之前通过的测试和组件不破）

- [ ] **步骤 9.4：跑全量 vitest**

```bash
cd web && npx vitest run
```

预期：之前通过的测试 + 任务 7/8 新增测试全绿

- [ ] **步骤 9.5：Commit**

```bash
git add web/src/types.ts
git commit -m "feat(types): tradition/center/stories/star fields"
```

---

## 任务 10：AtlasTraditionTabs + ConstellationView 集成

**文件：**
- 创建：`web/src/components/AtlasTraditionTabs.vue`
- 修改：`web/src/views/ConstellationView.vue`
- 修改：`web/tests/ConstellationView.test.ts`

- [ ] **步骤 10.1：创建 `web/src/components/AtlasTraditionTabs.vue`**

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useAtlasStore } from '../stores/atlas'

const store = useAtlasStore()

onMounted(async () => {
  await store.loadTraditions()
})
</script>

<template>
  <nav class="tradition-tabs" role="tablist">
    <button
      v-for="t in store.traditions"
      :key="t.key"
      :class="['trad-tab', {active: t.key === store.currentTradition}]"
      role="tab"
      :aria-selected="t.key === store.currentTradition"
      :data-testid="`trad-tab-${t.key}`"
      @click="store.setTradition(t.key)"
    >
      <span class="trad-glyph">{{ t.key === 'western' ? '✦' : '☷' }}</span>
      <span class="trad-label">{{ t.label }}</span>
      <span class="trad-count">{{ t.count }}</span>
    </button>
  </nav>
</template>

<style scoped>
.tradition-tabs {
  display: flex;
  gap: 0;
  margin: 18px 0 14px;
  border-bottom: 2px solid var(--line);
}
.trad-tab {
  background: none;
  border: none;
  padding: 12px 24px;
  font-family: var(--cn);
  font-size: 15px;
  letter-spacing: 0.15em;
  color: var(--ink-faint);
  cursor: pointer;
  position: relative;
  transition: 0.2s;
}
.trad-tab.active {
  color: var(--ink);
  font-weight: 700;
}
.trad-tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gold);
}
.trad-glyph { margin-right: 6px; font-size: 18px; color: var(--gold); }
.trad-count {
  margin-left: 6px;
  font-size: 12px;
  color: var(--ink-faint);
  font-style: italic;
}
</style>
```

- [ ] **步骤 10.2：在 ConstellationView 顶部插入 tabs + 空状态**

```diff
- <!-- 原顶部内容 -->
+ <AtlasTraditionTabs />
+
+ <div v-if="atlasStore.currentItems.length === 0" class="atlas-empty" data-testid="atlas-empty">
+   <p class="atlas-empty-glyph">☷</p>
+   <h3>{{ atlasStore.currentTradition === 'western' ? '尚无星座数据' : '中国星空尚在补齐中' }}</h3>
+   <p>该体系已预留位置，后续版本将逐步加入。</p>
+ </div>
+
+ <div v-else class="smedal-row">
+   <button v-for="item in atlasStore.currentItems" :key="item.abbr" class="smedal">
+     ...
+   </button>
+ </div>
```

> 把原 `.smedal-row` 包到 `v-else` 块里。原测试断言 `.smedal` 数量 5 在 western 下保持。

- [ ] **步骤 10.3：改 `web/tests/ConstellationView.test.ts`**

加 2 个新测试：

```typescript
it('render tradition chips', async () => {
  const wrapper = mount(ConstellationView, {...})
  await flushPromises()
  expect(wrapper.find('[data-testid="trad-tab-western"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="trad-tab-chinese"]').exists()).toBe(true)
})

it('切换到 chinese 显示空状态', async () => {
  const wrapper = mount(ConstellationView, {...})
  await flushPromises()
  const chineseBtn = wrapper.find('[data-testid="trad-tab-chinese"]')
  await chineseBtn.trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-testid="atlas-empty"]').exists()).toBe(true)
})
```

- [ ] **步骤 10.4：跑测试通过**

```bash
cd web && npx vitest run tests/ConstellationView.test.ts
```

预期：原 1 用例 + 新 2 用例 = 3 passed

- [ ] **步骤 10.5：vue-tsc 0 error**

```bash
cd web && npx vue-tsc --noEmit
```

- [ ] **步骤 10.6：Commit**

```bash
git add web/src/components/AtlasTraditionTabs.vue web/src/views/ConstellationView.vue web/tests/ConstellationView.test.ts
git commit -m "feat(atlas): tradition tabs + 空状态"
```

---

## 任务 11：ScanView 改 API

**文件：**
- 修改：`web/src/views/ScanView.vue`

- [ ] **步骤 11.1：删静态 import**

```diff
- import orionData from '../data/constellations.json'
```

- [ ] **步骤 11.2：识别成功后从 store 拿 atlas + tradition 透传**

找到识别结果处（`result.constellations[0]`），改为：

```typescript
const atlasStore = useAtlasStore()
const hit = result.constellations[0]
const atlas = hit ? await atlasStore.getAtlas(hit.tradition!, hit.abbr) : null
// 然后 StarCanvas 接收 :tradition="hit.tradition" 和 :constellation-data="atlas"
```

- [ ] **步骤 11.3：找 ScanView 单测 / e2e 测试更新断言**

若已有 ScanView 测试用 `orionData` mock，改为 mock `useAtlasStore`：

```typescript
import { vi } from 'vitest'
vi.mock('../src/stores/atlas', () => ({
  useAtlasStore: () => ({
    getAtlas: vi.fn().mockResolvedValue({abbr: 'ori', stars: {/*...*/}}),
  }),
}))
```

- [ ] **步骤 11.4：跑测试 + vue-tsc**

```bash
cd web && npx vitest run && npx vue-tsc --noEmit
```

预期：全绿

- [ ] **步骤 11.5：Commit**

```bash
git add web/src/views/ScanView.vue web/tests/
git commit -m "refactor(scan): 删静态 JSON import 改走 API + tradition 透传"
```

---

## 任务 12：AtlasStoryStatic 改读 constellation.stories

**文件：**
- 修改：`web/src/components/AtlasStoryStatic.vue`
- 修改：`web/tests/AtlasStoryStatic.test.ts`

- [ ] **步骤 12.1：删 atlasStories.json import**

```diff
- import atlasStories from '../data/atlas_stories.json'
```

- [ ] **步骤 12.2：改 props 与数据源**

```typescript
import { computed, ref } from 'vue'
import { useAtlasStore } from '../stores/atlas'
import type { StoryNarrative, StoryStyle } from '../types'

const props = defineProps<{ tradition: string; abbr: string }>()
const atlasStore = useAtlasStore()

const views: { value: StoryStyle; label: string }[] = [
  { value: 'myth', label: '神话视角' },
  { value: 'science', label: '科普视角' },
]
const narratives: { value: StoryNarrative; label: string }[] = [
  { value: 'epic', label: '星夜史诗' },
  { value: 'chat', label: '炉边夜话' },
  { value: 'brief', label: '星图简说' },
]

const selectedView = ref<StoryStyle>('myth')
const selectedNarrative = ref<StoryNarrative>('epic')

const constellation = computed(() =>
  atlasStore.atlasCache[`${props.tradition}/${props.abbr}`],
)

const currentStory = computed(() => {
  const stories = constellation.value?.stories
  if (!stories) return null
  const viewEntry = stories[selectedView.value]
  if (!viewEntry) return null
  return viewEntry[selectedNarrative.value]
    ?? Object.values(viewEntry)[0]
    ?? null
})
```

模板底部：

```vue
<div v-if="constellation && !currentStory" class="story-empty" data-testid="story-empty">
  该维度暂无内容。试试其他视图或叙事风格。
</div>
```

- [ ] **步骤 12.3：改测试（mock store 提供 stories）**

```typescript
import { vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAtlasStore } from '../src/stores/atlas'

it('读 constellation.stories', async () => {
  setActivePinia(createPinia())
  const store = useAtlasStore()
  store.atlasCache['western/ori'] = {
    abbr: 'ori', stars: {}, tradition: 'western',
    stories: {
      myth: {
        brief: {title: '猎户神话简说', paragraphs: ['第一段', '第二段']},
        epic: {title: '', paragraphs: []},
        chat: {title: '', paragraphs: []},
      },
      science: {
        brief: {title: '', paragraphs: []},
        epic: {title: '', paragraphs: []},
        chat: {title: '', paragraphs: []},
      },
    },
  } as any
  const wrapper = mount(AtlasStoryStatic, {props: {tradition: 'western', abbr: 'ori'}})
  await flushPromises()
  expect(wrapper.text()).toContain('猎户神话简说')
})

it('空维度显示空状态', async () => {
  setActivePinia(createPinia())
  const store = useAtlasStore()
  store.atlasCache['western/ori'] = {
    abbr: 'ori', stars: {}, tradition: 'western',
    stories: {
      myth: {epic: {title: '', paragraphs: []}, chat: {title: '', paragraphs: []}, brief: {title: '', paragraphs: []}},
      science: {epic: {title: '', paragraphs: []}, chat: {title: '', paragraphs: []}, brief: {title: '', paragraphs: []}},
    },
  } as any
  const wrapper = mount(AtlasStoryStatic, {props: {tradition: 'western', abbr: 'ori'}})
  await flushPromises()
  expect(wrapper.text()).toContain('暂无内容')
})
```

- [ ] **步骤 12.4：跑测试通过**

```bash
cd web && npx vitest run tests/AtlasStoryStatic.test.ts
```

预期：原有用例 + 新 2 = N passed

- [ ] **步骤 12.5：Commit**

```bash
git add web/src/components/AtlasStoryStatic.vue web/tests/AtlasStoryStatic.test.ts
git commit -m "refactor(atlas-story): 改读 constellation.stories + 空状态"
```

---

## 任务 13：StarCanvas labels + tradition 兜底

**文件：**
- 修改：`web/src/components/StarCanvas.vue`
- 创建：`web/tests/StarCanvas.label.test.ts`

- [ ] **步骤 13.1：在 StarCanvas 加 tradition prop**

```typescript
const props = defineProps<{
  mode: 'scan-atlas' | 'atlas-detail'
  constellationData: ConstellationAtlas
  tradition?: string   // ★ 新增，默认 'western'
}>()

const tradition = computed(() => props.tradition ?? 'western')
```

- [ ] **步骤 13.2：实现 displayNameFor + labeledStars + fontSize**

```typescript
function displayNameFor(star: any, trad: string): string {
  // 鬼底链：用 `||` 而非 `??`（因为 `name_zh: ""` 在 `??` 下不 fallback，会出空白）；
  // 加 `.trim()` 防 `" "`（空格）伪非空。
  if (trad === 'chinese') {
    const zh = (star.name_zh ?? '').trim()
    return zh || (star.name ?? '').trim() || '未命名'
  }
  const en = (star.name ?? '').trim()
  return en || (star.name_zh ?? '').trim() || '未命名'
}
function fontSize(mag: number): number {
  return 8 + Math.max(0, (4 - mag)) * 1.5
}
const labeledStars = computed(() =>
  Object.entries(props.constellationData.stars ?? {})
    .filter(([_, s]: any) => s.label)
    .map(([id, s]: any) => ({id, ...s})),
)
```

- [ ] **步骤 13.3：在 SVG 模板加 labels 组**

```vue
<g class="labels" data-testid="star-labels">
  <text
    v-for="s in labeledStars"
    :key="s.id"
    :x="s.x + 8"
    :y="s.y - 8"
    :class="['star-label', {chinese: tradition === 'chinese'}]"
    :font-size="fontSize(s.magnitude)"
  >
    {{ displayNameFor(s, tradition) }}
  </text>
</g>
```

- [ ] **步骤 13.4：写 `StarCanvas.label.test.ts`**

```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StarCanvas from '../src/components/StarCanvas.vue'

const orionAtlas = {
  abbr: 'ori', stars: {
    betelgeuse: {x: 100, y: 100, name: 'Betelgeuse', name_zh: '参宿四', magnitude: 0.42, label: true},
    rigel: {x: 200, y: 200, name: 'Rigel', name_zh: '参宿七', magnitude: 0.13, label: true},
    dim: {x: 300, y: 300, name: 'Dim', magnitude: 4.0, label: false},
  },
}

describe('StarCanvas labels', () => {
  it('label: true 的星画 text', () => {
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: orionAtlas as any, tradition: 'western'},
    })
    const labels = wrapper.findAll('[data-testid="star-labels"] text')
    expect(labels.length).toBe(2)
    expect(labels[0].text()).toBe('Betelgeuse')
  })

  it('tradition=chinese 显示 name_zh', () => {
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: orionAtlas as any, tradition: 'chinese'},
    })
    const labels = wrapper.findAll('[data-testid="star-labels"] text')
    expect(labels[0].text()).toBe('参宿四')
  })

  it('缺 name_zh 时兜底 name', () => {
    const a = {...orionAtlas, stars: {
      x: {x: 100, y: 100, name: 'X', magnitude: 1, label: true},
    }}
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: a as any, tradition: 'chinese'},
    })
    expect(wrapper.find('[data-testid="star-labels"] text').text()).toBe('X')
  })

  it('name="" 时兜底 name_zh（防 `??` 不 fallback 的 bug）', () => {
    const a = {...orionAtlas, stars: {
      x: {x: 100, y: 100, name: '', name_zh: '参宿一', magnitude: 1, label: true},
    }}
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: a as any, tradition: 'western'},
    })
    expect(wrapper.find('[data-testid="star-labels"] text').text()).toBe('参宿一')
  })

  it('name_zh=" " 空格时 trim 后兜底', () => {
    const a = {...orionAtlas, stars: {
      x: {x: 100, y: 100, name: 'Betelgeuse', name_zh: ' ', magnitude: 1, label: true},
    }}
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: a as any, tradition: 'chinese'},
    })
    expect(wrapper.find('[data-testid="star-labels"] text').text()).toBe('Betelgeuse')
  })

  it('缺 name + name_zh 兜底 未命名', () => {
    const a = {...orionAtlas, stars: {
      x: {x: 100, y: 100, magnitude: 1, label: true},
    }}
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: a as any, tradition: 'western'},
    })
    expect(wrapper.find('[data-testid="star-labels"] text').text()).toBe('未命名')
  })

  it('label: false 的星不画', () => {
    const a = {...orionAtlas, stars: {
      only: {x: 100, y: 100, name: 'Only', magnitude: 1, label: false},
    }}
    const wrapper = mount(StarCanvas, {
      props: {mode: 'atlas-detail', constellationData: a as any, tradition: 'western'},
    })
    expect(wrapper.findAll('[data-testid="star-labels"] text').length).toBe(0)
  })
})
```

- [ ] **步骤 13.5：跑测试通过**

```bash
cd web && npx vitest run tests/StarCanvas.label.test.ts
```

预期：5 passed

- [ ] **步骤 13.6：跑 vue-tsc + 全量 vitest**

```bash
cd web && npx vue-tsc --noEmit && npx vitest run
```

预期：0 error + 全绿

- [ ] **步骤 13.7：Commit**

```bash
git add web/src/components/StarCanvas.vue web/tests/StarCanvas.label.test.ts
git commit -m "feat(canvas): 星点常驻标注 + tradition 兜底"
```

---

## 任务 14：删 web/src/data/ + 全量回归

**文件：**
- 删除：`web/src/data/`（整个目录）

- [ ] **步骤 14.1：删除目录**

```bash
git rm -r web/src/data/
```

- [ ] **步骤 14.2：全量前端测试**

```bash
cd web && npx vitest run
```

预期：原有用例 + 任务 7-13 新增，全绿

- [ ] **步骤 14.3：vue-tsc**

```bash
cd web && npx vue-tsc --noEmit
```

预期：0 error

- [ ] **步骤 14.4：全量后端测试**

```bash
cd server && .venv/Scripts/python.exe -m pytest -q
```

预期：原有用例 + 任务 2-5 新增，全绿

- [ ] **步骤 14.5：live E2E 验证**

```bash
# 启动后端
cd server && python -m uvicorn main:app --reload --port 8000 &
sleep 5

# 启动前端
cd web && npx vite --port 5173 &
sleep 8

# 健康检查
curl http://127.0.0.1:8000/api/health

# 识别测试图（用 assets/test1.jpg / test2.jpg / test3.jpg）
curl -sS -X POST http://127.0.0.1:8000/api/identify \
  -F "file=@assets/test1.jpg" \
  -F "orientation=1" | python -m json.tool | head -30
```

预期：识别返回 `constellations[0].abbr == "ori"`、`tradition == "western"`、`visible_stars >= 1`

- [ ] **步骤 14.6：跑 validate_atlas.py 末次校验**

```bash
cd server && python scripts/validate_atlas.py
```

预期：
```
OK and.json
OK cyg.json
OK leo.json
OK ori.json
OK sco.json

Summary: 0 hard errors, 0 soft warnings
```

- [ ] **步骤 14.7：Commit**

```bash
git add -A
git commit -m "chore: 删 web/src/data/ + MVP 完成

所有验收标准达成：
- 后端 pytest 全绿（任务 2/3/4/5 新增 ~17 用例）
- 前端 vitest 全绿（任务 7-13 新增 ~15 用例）
- vue-tsc 0 error
- validate_atlas.py 全绿
- live E2E test1/2/3 识别成功（visible_stars 字段）
- 5 星座西方视角与之前 100% 一致
- tradition 切换 UI 工作（中文空时显示空状态）"
```

---

## 自检

### 规格覆盖度

| 规格章节 | 实现任务 |
|---|---|
| 1.1 目录结构（平铺）| 任务 1 |
| 1.2 JSON Schema（含 center/stories/label）| 任务 1 |
| 1.4 文件命名（IAU 缩写优先）| 任务 1 |
| 1.5 删除旧文件 | 任务 1 |
| 1.6 复用 vs 扩展 | 任务 1（复用 ra/dec/name/name_zh） + 任务 9（types 扩展）|
| 2.1 services.traditions.py | 任务 2 |
| 2.2 端点 | 任务 4 |
| 2.3 identify 反查 | 任务 5 |
| 2.4 故事端点不动 | 无（无需任务）|
| 2.5 删旧端点 | 任务 4 |
| 3.1 web api/atlas.ts | 任务 7 |
| 3.2 stores/atlas.ts | 任务 8 |
| 3.3 ScanView 改造 | 任务 11 |
| 3.4 ConstellationView chips + 空状态 | 任务 10 |
| 3.5 AtlasStoryStatic 改造 | 任务 12 |
| 3.6 StarCanvas labels + 兜底 | 任务 13 |
| 3.7 types.ts 扩展 | 任务 9 |
| 3.8 删 web/src/data/ | 任务 14 |
| 4.1 后端测试 | 任务 2/4/5 |
| 4.2 前端测试 | 任务 7/8/10/12/13 |
| 4.3 validate_atlas | 任务 3 |
| 5 第一阶段步骤 | 任务 1-14 |
| 6 验收标准 | 任务 14 |
| 7 风险 | 任务 2（fail-soft）+ 任务 5（catalog 去重）+ 任务 6（startup）+ 任务 13（兜底）|
| 8 后续优化 | 不在本次范围（第二/三期）|

**结论**：所有 MVP 需求覆盖。第二期/第三期数据补齐在范围外。

### 占位符扫描

| 关键字 | 出现位置 | 备注 |
|---|---|---|
| TODO | 任务 5.3 注释（"实际 \_call_upstream_solve mock 路径取决于项目已有结构；请按 routers/identify.py 当前实现调用名调整。"） | 这是必要的提示，不是 TODO 占位 |
| 待定 | 0 | ✓ |
| 后续实现 | 0 | ✓ |
| 等等 | 任务 2.4 注释（"保留旧的 ... 若已存在前端使用——按 grep 结果迁移"） | 提示工程师处理，非占位 |

**结论**：占位符已剔除。

### 类型一致性

| 类型 | 定义处 | 使用处 |
|---|---|---|
| `TraditionListItem` | 任务 9.1（web/src/types.ts）| 任务 7.3（atlas.ts）、任务 8.3（store）、任务 10.1（tabs）|
| `TraditionListResponse` | 任务 9.1 | 任务 7.3 |
| `AtlasListItem.tradition` | 任务 9.2 | 任务 10.2（ConstellationView）、任务 14.5（live 验证）|
| `ConstellationAtlas.center` | 任务 9.2 | 任务 2（test）、任务 5（find_nearest 用）|
| `ConstellationAtlas.stories` | 任务 9.2 | 任务 12（AtlasStoryStatic）|
| `AtlasStar.label/name_zh/ra/dec` | 任务 9.2 | 任务 13（StarCanvas）、任务 1（JSON）|
| `ConstellationAtlas.stories[view][narr].{title,paragraphs}` | 任务 9.2 | 任务 12、JSON |
| `find_nearest(ra, dec) → (trad, abbr, sep_deg)` | 任务 2.3 | 任务 5.2 |
| `build_star_catalog() → list[dict]` | 任务 2.3 | 任务 5.1 |
| `displayNameFor(star, tradition) → string` | 任务 13.2 | 任务 13.4（test）|
| `getAtlas(tradition, abbr) → ConstellationAtlas` | 任务 8.3 | 任务 11.2、任务 12.2 |

**结论**：类型/方法签名一致，无歧义。

---

## 验收标准（任务 14 完成时）

- 后端 pytest：全绿（任务 2 + 4 + 5 共新增 ~17 用例）
- 前端 vitest：全绿（任务 7-13 共新增 ~17 用例）
- vue-tsc：0 error
- Atlas UI：chips 切换工作；空时显示"中国星空尚在补齐中"
- Scan UI：识别后展示真实命中的 atlas（含标注），不是写死猎户
- validate_atlas：5 文件全绿
- 旧文件：web/src/data/、bayer_index.json、preset_stories.json 全删
- live 验证：test1.jpg 识别返回 `tradition=western, abbr=ori, visible_stars>=1`

---

## 不在本次范围

- 第二期西方 83 星座补齐（数据采集工作流）
- 第三期中国 28 宿 + 三垣补齐（数据采集工作流）
- RA/Dec 真投影渲染（仅入库不渲染）
- find_nearest 返回多个候选（接口设计已留扩展）
- GET /api/constellation 加 include_stories=false（payload 优化）
- tradition/_meta.json 取代硬编码 _label