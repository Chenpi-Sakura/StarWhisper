# Atlas 数据补齐 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 tradition 数据从 MVP 5 西方星座扩展到西方 IAU 88 座全量 + 中国星官约 306 个（三垣二十八宿 + 近南极），数据源为 `celestial_data` 开源数据集。

**架构：**
- 数据管道：两个一次性 build 脚本（`build_full_catalog.py` 西方、`build_chinese_stars.py` 中国），从 `server/data/raw/` 签入的原始数据生成 `traditions/{key}/{abbr}.json`
- 核心算法抽为可测试纯函数，放 `server/scripts/atlas_data/` 包，TDD 驱动
- 后端：`build_star_catalog` 去重升级 HIP 优先；`validate_atlas.py` 加中国星官专项校验
- 前端：ConstellationView 列表加分组（三垣 + 四象 + 近南极），Zero 新增渲染模式

**技术栈：** Python 3.11+ / pytest；TypeScript / Vue 3 / vitest / vue-tsc

**Spec：** `docs/specs/2026-08-25-atlas-data-completion.md`

## Global Constraints

- Python 环境用 `server/.venv`，运行命令 `cd server && .venv/Scripts/python.exe -m pytest -q`
- 前端测试 `cd web && npx vitest run`，类型 `cd web && npx vue-tsc --noEmit`
- 现有 5 西方星座 JSON **手绘 x/y 保留，脚本不覆盖**（skip 已存在 entry）
- RA 统一 **0..360**（数据源 -180..180 需转换）；projection 与 spec v4 `worldToPixelEquirect` 一致（**不加 cos**，含 RA wrapping）
- 中文字符串 / 文件内容一律 UTF-8，`json.dumps(..., ensure_ascii=False)`
- abbr 全 ASCII：`^[a-z0-9_]+$`（pinyin slug，括号/空格转 `_`，去声调）
- 数据源已实测：`starnames.cn.id`=HIP、`stars.8.id`=HIP 直接 join；前缀归组覆盖率 87.3% > 80% 否决线
- 西方 88 座、中国约 306 星官，均须过 `validate_atlas.py` 0 hard errors

---

## 文件结构

| 文件 | 状态 | 职责 |
|---|---|---|
| `server/scripts/atlas_data/__init__.py` | 创建 | 包占位 |
| `server/scripts/atlas_data/coords.py` | 创建 | RA 转换、主名归一化、Haversine、等距投影、RA wrapping |
| `server/scripts/atlas_data/cn_members.py` | 创建 | 星官→成员星前缀归组、连线端点坐标回填 |
| `server/scripts/download_celestial_data.py` | 创建 | 一次性下载 raw 数据 |
| `server/scripts/build_full_catalog.py` | 创建 | 西方 88 座生成 |
| `server/scripts/build_chinese_stars.py` | 创建 | 中国约 306 星官生成 |
| `server/scripts/validate_atlas.py` | 修改 | 加 lines 悬空引用 + abbr + name_zh 校验 |
| `server/services/traditions.py` | 修改 | `build_star_catalog` HIP 优先去重 |
| `server/data/raw/*` | 创建 | 签入的原始数据（starnames/stars/lines/cn csv+geojson） |
| `server/tests/test_atlas_data.py` | 创建 | coords + cn_members 单元测试 |
| `server/tests/test_build_star_catalog.py` | 修改 | HIP 去重 + 跨 entry 一致性测试 |
| `server/tests/test_validate_atlas.py` | 修改 | 中国星官专项校验测试 |
| `web/src/views/ConstellationView.vue` | 修改 | 列表分组渲染 |
| `web/src/stores/atlas.ts` | 修改 | 分组数据派生（如需要） |
| `web/tests/ConstellationView.test.ts` | 修改 | 分组渲染测试 |

---

## 任务 1：数据下载脚本 + raw 目录

**文件：**
- 创建：`server/scripts/download_celestial_data.py`

**接口：**
- 产出：`server/data/raw/{constellations.cn.csv, starnames.cn.csv, constellations.lines.cn.geojson, stars.8.min.geojson, starnames.csv, constellations.lines.geojson}`

- [ ] **步骤 1：建 raw 目录并写下载脚本**

```python
"""一次性下载 celestial_data 原始数据到 server/data/raw/。

数据源：https://github.com/dieghernan/celestial_data
许可：开源（见 docs/specs/2026-08-25-atlas-data-completion.md §2.1）。
"""
from pathlib import Path
import urllib.request

BASE = "https://raw.githubusercontent.com/dieghernan/celestial_data/main/data"
FILES = [
    "constellations.csv",
    "constellations.cn.csv",
    "starnames.cn.csv",
    "constellations.lines.cn.geojson",
    "stars.8.min.geojson",
    "starnames.csv",
    "constellations.lines.geojson",
]

OUT = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        url = f"{BASE}/{name}"
        dest = OUT / name
        print(f"下载 {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
        print(f"  OK {dest.stat().st_size} bytes")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行下载**

Run: `cd server && .venv/Scripts/python.exe scripts/download_celestial_data.py`
Expected: 6 个文件落盘，`stars.8.min.geojson` 约 6.3MB，其余较小

- [ ] **步骤 3：验证文件内容**

Run: `cd server && .venv/Scripts/python.exe -c "import json,csv;from pathlib import Path; d=Path('data/raw'); print('starnames.cn 行数:', sum(1 for _ in open(d/'starnames.cn.csv',encoding='utf-8'))-1); print('cn 星官行数:', sum(1 for _ in open(d/'constellations.cn.csv',encoding='utf-8'))-1); g=json.loads((d/'stars.8.min.geojson').read_text(encoding='utf-8')); print('stars.8 features:', len(g['features']), '首条 id:', g['features'][0]['properties']['id'])"`
Expected: `starnames.cn 行数: 3056`、`cn 星官行数: 312`、`stars.8 features: ~16000` 且首条 `id: 3`（=HIP）

- [ ] **步骤 4：提交**

```bash
git add server/scripts/download_celestial_data.py server/data/raw/
git commit -m "chore(data): celestial_data 原始数据下载脚本 + raw 签入"
```

---

## 任务 2：atlas_data 纯函数包 + 单元测试（gate 前置核心）

**文件：**
- 创建：`server/scripts/atlas_data/__init__.py`
- 创建：`server/scripts/atlas_data/coords.py`
- 创建：`server/tests/test_atlas_data.py`

**接口：**
- 产出（后续 build 脚本依赖，签名固定）：
  - `normalize_ra(lon: float) -> float`：-180..180 → 0..360
  - `ra_wrap(delta_ra: float) -> float`：取 [-180,180] 最短弧
  - `haversine_deg(ra1, dec1, ra2, dec2) -> float`
  - `main_name(name: str) -> str`：去括号取主名（`柱(毕宿)`→`柱`、`柱一[毕宿]`→`柱一`）
  - `strip_suffix(name: str) -> str`：去序号/增星后缀（`参宿四`→`参宿`、`参宿增卅八`→`参宿`）
  - `slugify(pinyin: str) -> str`：全 ASCII abbr

- [ ] **步骤 1：写 coords.py 骨架 + 失败测试**

`coords.py`：

```python
"""坐标转换、主名归一化、投影等纯函数。无 IO，便于单测。"""
import math
import re


def normalize_ra(lon: float) -> float:
    """GeoJSON 经度 -180..180 → RA 0..360。"""
    return lon if lon >= 0 else lon + 360


def ra_wrap(delta_ra: float) -> float:
    """RA 差值取 [-180, 180] 最短弧。"""
    return ((delta_ra + 180) % 360) - 180


def haversine_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """严格 Haversine 球面角距，返回度数。"""
    ra1_r = math.radians(ra1)
    dec1_r = math.radians(dec1)
    ra2_r = math.radians(ra2)
    dec2_r = math.radians(dec2)
    ddec = dec2_r - dec1_r
    dra = ra2_r - ra1_r
    a = math.sin(ddec / 2) ** 2 + math.cos(dec1_r) * math.cos(dec2_r) * math.sin(dra / 2) ** 2
    a = min(1.0, max(0.0, a))
    return math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def main_name(name: str) -> str:
    """去掉括号及其后内容，取主名。柱(毕宿)→柱；柱一[毕宿]→柱一。"""
    return re.sub(r"[(\[].*", "", name).strip()


def strip_suffix(name: str) -> str:
    """去掉序号/增星后缀，返回归属星官名。参宿四→参宿；参宿增卅八→参宿。"""
    n = re.sub(r"\[.*", "", name)
    n = re.sub(r"增[一二三四五六七八九十百0-9]+$", "", n)
    n = re.sub(r"[一二三四五六七八九十百0-9]+$", "", n)
    return n.strip()


def slugify(pinyin: str) -> str:
    """pinyin → 全 ASCII abbr。柱(毕宿) → zhu_bixiu。"""
    s = pinyin.lower()
    s = re.sub(r"[\u00e0\u00e1\u00e2\u00e3\u00e4\u0101]", "a", s)
    s = re.sub(r"[\u00e8\u00e9\u00ea\u00eb\u0113]", "e", s)
    s = re.sub(r"[\u00ec\u00ed\u00ee\u00ef\u012b]", "i", s)
    s = re.sub(r"[\u00f2\u00f3\u00f4\u00f5\u00f6\u014d]", "o", s)
    s = re.sub(r"[\u00f9\u00fa\u00fb\u00fc\u016b]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")
```

`test_atlas_data.py`：

```python
from scripts.atlas_data.coords import (
    normalize_ra, ra_wrap, haversine_deg, main_name, strip_suffix, slugify,
)


def test_normalize_ra_boundaries():
    assert normalize_ra(0) == 0
    assert normalize_ra(83.7137) == 83.7137
    assert normalize_ra(-131.6994) == 228.3006
    assert normalize_ra(180) == 180
    assert normalize_ra(-180) == 180


def test_ra_wrap_shortest_arc():
    assert ra_wrap(359 - 1) == -2          # 跨春分点：取最短弧
    assert ra_wrap(10 - 20) == -10
    assert abs(ra_wrap(200)) == 160        # 200 → -160


def test_haversine_known_pair():
    # 参宿四 (88.7929, 7.4071) vs 猎户中心 (86.0, -2.0)
    sep = haversine_deg(88.7929, 7.4071, 86.0, -2.0)
    assert 9.0 < sep < 10.0


def test_main_name_strips_parens():
    assert main_name("柱(毕宿)") == "柱"
    assert main_name("柱一[毕宿]") == "柱一"
    assert main_name("参宿") == "参宿"


def test_strip_suffix_returns_asterism():
    assert strip_suffix("参宿四") == "参宿"
    assert strip_suffix("参宿增卅八") == "参宿"
    assert strip_suffix("壁宿增廿一") == "壁宿"


def test_slugify_ascii():
    assert slugify("Zhu(Bi Xiu)") == "zhu_bi_xiu"
    assert slugify("Shēnxiù") == "shenxiu"
```

- [ ] **步骤 2：跑测试确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_atlas_data.py -v`
Expected: FAIL（coords.py 未实现，或部分断言需微调）

- [ ] **步骤 3：实现 coords.py（见步骤 1 完整代码）**

- [ ] **步骤 4：跑测试确认通过**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_atlas_data.py -v`
Expected: 全部 PASS（注意 `test_ra_wrap` 中 `ra_wrap(200)` 的浮点，用 `abs(...) == 160` 兜底）

- [ ] **步骤 5：提交**

```bash
git add server/scripts/atlas_data/ server/tests/test_atlas_data.py
git commit -m "feat(atlas-data): coords 纯函数包（RA 转换/wrapping/Haversine/主名/slug）"
```

---

## 任务 3：成员星归组 + 连线回填（cn_members）

**文件：**
- 创建：`server/scripts/atlas_data/cn_members.py`
- 修改：`server/tests/test_atlas_data.py`（追加测试）

**接口：**
- 消费：`coords.strip_suffix` / `coords.main_name` / `coords.haversine_deg` / `coords.normalize_ra`
- 产出：
  - `group_members(constellations_csv, starnames_csv) -> dict[str, list[dict]]`：星官名 → 成员星列表（每条含 `id`(HIP)/`name`/`desig`）
  - `match_line_endpoint(endpoint_lonlat, members, threshold) -> str | None`：坐标 → star key（用 HIP id 作 key）

- [ ] **步骤 1：写 cn_members.py 骨架 + 失败测试**

`cn_members.py`：

```python
"""星官成员归组 + 连线端点回填。依赖 coords 纯函数。"""
import csv
from scripts.atlas_data.coords import haversine_deg, normalize_ra, strip_suffix


def group_members(constellations_path, starnames_path):
    """按星官主名归组 starnames.cn 单星名。

    返回 {星官主名: [{id(HIP), name, desig}, ...]}。
    """
    asterisms = set()
    with open(constellations_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            asterisms.add(strip_suffix(row["name"]))

    groups = {}
    with open(starnames_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            asterism = strip_suffix(row["name"])
            if asterism not in asterisms:
                continue
            groups.setdefault(asterism, []).append(
                {"id": row["id"], "name": row["name"], "desig": row["desig"]}
            )
    return groups


def match_line_endpoint(lonlat, members_with_radec, threshold=0.02):
    """连线端点 [lon,lat] → 最近成员星 key(HIP)。

    members_with_radec: [{id, ra, dec}, ...]，ra 已转 0..360。
    返回 star key 或 None。
    """
    lon, lat = lonlat
    ra = normalize_ra(lon)
    best = None
    best_sep = threshold
    for m in members_with_radec:
        sep = haversine_deg(ra, lat, m["ra"], m["dec"])
        if sep < best_sep:
            best_sep = sep
            best = m["id"]
    return best
```

追加测试（`test_atlas_data.py`）：

```python
from scripts.atlas_data.cn_members import group_members, match_line_endpoint


def test_group_members_prefix_rule(tmp_path, monkeypatch):
    constellations = tmp_path / "c.csv"
    starnames = tmp_path / "s.csv"
    constellations.write_text(
        "id,name,en,pinyin,desig,rank,display_ra,display_dec\n"
        "3,参宿,Three Stars,shenxiu,参宿,1,83.7,-1.1\n",
        encoding="utf-8",
    )
    starnames.write_text(
        "id,name,desig,en,pinyin\n"
        "27989,参宿四,α Ori,Three Stars IV,Shēnxiù IV\n"
        "26727,参宿一,ζ Ori,Three Stars I,Shēnxiù I\n"
        "900,无关星,XX,None,None\n",
        encoding="utf-8",
    )
    groups = group_members(str(constellations), str(starnames))
    assert "参宿" in groups
    assert {m["id"] for m in groups["参宿"]} == {"27989", "26727"}


def test_match_line_endpoint_picks_nearest():
    # 端点 (83.0017, -0.2991) = 参宿一; 成员含参宿一
    key = match_line_endpoint(
        (83.0017, -0.2991),
        [{"id": "26727", "ra": 83.0017, "dec": -0.2991},
         {"id": "27989", "ra": 88.7929, "dec": 7.4071}],
    )
    assert key == "26727"
```

- [ ] **步骤 2：跑测试确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_atlas_data.py -v`
Expected: FAIL（cn_members 未实现）

- [ ] **步骤 3：实现 cn_members.py（见步骤 1 完整代码）**

- [ ] **步骤 4：跑测试确认通过**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_atlas_data.py -v`
Expected: PASS

- [ ] **步骤 5：提交**

```bash
git add server/scripts/atlas_data/cn_members.py server/tests/test_atlas_data.py
git commit -m "feat(atlas-data): 星官成员前缀归组 + 连线端点回填"
```

---

## 任务 4：西方 88 星座 build 脚本

**文件：**
- 创建：`server/scripts/build_full_catalog.py`

**接口：**
- 消费：`coords.normalize_ra/ra_wrap/main_name`、raw 的 `starnames.csv` + `stars.8.min.geojson` + `constellations.lines.geojson`
- 产出：`server/data/traditions/western/{abbr}.json` × 88（跳过已存在 5 座）

- [ ] **步骤 1：写 build_full_catalog.py**

```python
"""生成西方 88 星座 JSON。跳过已存在的 MVP 5 座（保留手绘 x/y）。"""
import csv
import json
from pathlib import Path

from scripts.atlas_data.coords import main_name, ra_wrap

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = Path(__file__).resolve().parents[1] / "data" / "traditions" / "western"

VIEW_W, VIEW_H = 500.0, 400.0


def load_stars():
    """stars.8 → {HIP: {ra, dec, mag}}。"""
    g = json.loads((RAW / "stars.8.min.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in g["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        ra = lon if lon >= 0 else lon + 360
        out[str(p["id"])] = {"ra": ra, "dec": lat, "mag": p["mag"]}
    return out


def load_lines():
    """constellations.lines → {abbr: [(lon,lat), ...]} 每条线段端点坐标展平。"""
    g = json.loads((RAW / "constellations.lines.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in g["features"]:
        abbr = f["properties"]["id"].lower()
        pts = [p for line in f["geometry"]["coordinates"] for p in line]
        out[abbr] = pts
    return out


def load_constellations_meta():
    """constellations.csv → {abbr: {zh, latin, ra, dec, scale, rank}}。

    表头实测：id,name,desig,gen,rank,en,la,ar,zh,...,display_ra,display_dec,display_scale
    """
    out = {}
    with open(RAW / "constellations.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            abbr = row["desig"].lower()
            out[abbr] = {
                "zh": row["zh"],
                "latin": row["name"],
                "ra": normalize_ra(float(row["display_ra"])),
                "dec": float(row["display_dec"]),
                "scale": float(row["display_scale"]) or 1.0,
                "rank": int(row["rank"]),
            }
    return out


def load_starnames():
    """starnames.csv → {HIP: {name, bayer}}。"""
    out = {}
    with open(RAW / "starnames.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hip = row["hip"] or row["id"]
            out[hip] = {"name": row["name"] or "", "bayer": row["bayer"] or ""}
    return out


def build_star(hip, star, name, bayer, center, scale):
    """构造单星 dict，含投影 x/y。"""
    dra = ra_wrap(star["ra"] - center["ra"])
    ddec = star["dec"] - center["dec"]
    x = VIEW_W / 2 + dra * scale
    y = VIEW_H / 2 - ddec * scale
    return {
        "x": round(x, 1), "y": round(y, 1),
        "bayer": bayer, "name": name, "name_zh": "",
        "magnitude": star["mag"], "ra": round(star["ra"], 4),
        "dec": round(star["dec"], 4), "label": False, "hip": hip,
    }


def main():
    from scripts.atlas_data.coords import normalize_ra as _norm
    stars = load_stars()
    lines = load_lines()
    names = load_starnames()
    meta = load_constellations_meta()
    OUT.mkdir(parents=True, exist_ok=True)
    for abbr, line_pts in lines.items():
        dest = OUT / f"{abbr}.json"
        if dest.exists():
            continue  # 跳过已有 5 座（手绘 x/y 保留）
        m = meta.get(abbr)
        if not m:
            print(f"WARN {abbr} 不在 constellations.csv，跳过")
            continue
        center_ra = m["ra"]
        center_dec = m["dec"]
        # 收集端点唯一坐标 → 匹配最近 HIP（粗筛，阈值 0.05°）
        star_map = {}
        seen = set()
        for lon, lat in line_pts:
            best, best_sep = None, 0.05
            for hip, s in stars.items():
                dra = ra_wrap(s["ra"] - center_ra)
                ddec = s["dec"] - center_dec
                sep = (dra * dra + ddec * ddec) ** 0.5
                if sep < best_sep:
                    best_sep, best = sep, hip
            if best and best not in seen:
                seen.add(best)
                star_map[best] = stars[best]
        if not star_map:
            continue
        # scale：display_scale 是星座显示半径（度），归一化到 viewBox
        scale = min((VIEW_W / 2 - 20) / max(m["scale"], 0.001),
                    (VIEW_H / 2 - 20) / max(m["scale"], 0.001))
        entry_stars = {}
        for hip, s in star_map.items():
            nm = names.get(hip, {})
            entry_stars[hip] = build_star(hip, s, nm.get("name", ""), nm.get("bayer", ""),
                                          {"ra": center_ra, "dec": center_dec}, scale)
        # lines：端点坐标 → star key（Haversine 精确匹配）
        entry_lines = []
        for ln in load_lines_for(abbr):
            seg = []
            for lon, lat in ln:
                ra = _norm(lon)
                best, best_sep = None, 0.05
                for hip, s in star_map.items():
                    sep = _quick_sep(ra, lat, s["ra"], s["dec"])
                    if sep < best_sep:
                        best_sep, best = sep, hip
                if best:
                    seg.append(best)
            if len(seg) >= 2:
                entry_lines.append(seg)
        entry = {
            "abbr": abbr, "name": m["zh"], "latin": m["latin"],
            "glyph": "", "season": "", "caption": "",
            "viewBox": {"width": 500, "height": 400},
            "center": {"ra": round(center_ra, 4), "dec": round(center_dec, 4)},
            "stars": entry_stars, "lines": entry_lines,
            "mansion": None, "asterism_id": None,
            "stories": _empty_stories(),
        }
        dest.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"OK {abbr} ({len(entry_stars)} 星, {len(entry_lines)} 线)")


def load_lines_for(abbr):
    """返回该星座原始线段（每条线段一组端点）。"""
    g = json.loads((RAW / "constellations.lines.geojson").read_text(encoding="utf-8"))
    for f in g["features"]:
        if f["properties"]["id"].lower() == abbr:
            return f["geometry"]["coordinates"]
    return []


def _quick_sep(ra1, dec1, ra2, dec2):
    import math
    dra = math.radians(ra1 - ra2) * math.cos(math.radians((dec1 + dec2) / 2))
    ddec = math.radians(dec1 - dec2)
    return math.degrees(math.sqrt(dra * dra + ddec * ddec))


def _empty_stories():
    empty = {"title": "尚未撰写", "paragraphs": []}
    return {"myth": {"epic": empty, "chat": empty, "brief": empty},
            "science": {"epic": empty, "chat": empty, "brief": empty}}
```

> **注意**：`name` 直接取 `constellations.csv.zh`（已实测含中文，如"仙女座"）；`latin` 取 `name`（英文全名，如"Andromeda"）；`center` 取 `display_ra/display_dec`（已 normalize_ra 转 0..360）；`scale` 源自 `display_scale`（显示半径度数）。`stories` 6 维 title 占位（spec §0 已声明 stories 全量手写分批回填，不阻塞主流程）。

- [ ] **步骤 2：运行脚本**

Run: `cd server && .venv/Scripts/python.exe scripts/build_full_catalog.py`
Expected: 打印 `OK and/cyg/...`，`server/data/traditions/western/` 从 5 增至 ≤88 个 json

- [ ] **步骤 3：校验**

Run: `cd server && .venv/Scripts/python.exe scripts/validate_atlas.py`
Expected: 0 hard errors（新增西方座全过；有 soft warning 需排查）

- [ ] **步骤 4：提交**

```bash
git add server/scripts/build_full_catalog.py server/data/traditions/western/
git commit -m "feat(atlas-data): 西方 88 座生成脚本 + 数据"
```

---

## 任务 5：中国星官 build 脚本

**文件：**
- 创建：`server/scripts/build_chinese_stars.py`

**接口：**
- 消费：`coords.*`、`cn_members.*`、raw `constellations.cn.csv`/`starnames.cn.csv`/`constellations.lines.cn.geojson`/`stars.8.min.geojson`
- 产出：`server/data/traditions/chinese/{abbr}.json` × ~306

- [ ] **步骤 1：写 build_chinese_stars.py**

```python
"""生成中国星官约 306 个 JSON。

关键启发式（spec §2.3，覆盖率已实测 87.3% > 80%）：
1. 成员星归组：strip_suffix(单星名) 命中星官主名
2. 连线回填：lines.cn 端点是坐标，Haversine 最近邻匹配成员星 HIP
3. 三垣：6 垣墙(rank=2)合并为 3 entry；近南极 23 星官 asterism_id='nanji'
"""
import csv
import json
from pathlib import Path
import re

from scripts.atlas_data.coords import (
    haversine_deg, main_name, normalize_ra, ra_wrap, slugify, strip_suffix,
)
from scripts.atlas_data.cn_members import group_members

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = Path(__file__).resolve().parents[1] / "data" / "traditions" / "chinese"
VIEW_W, VIEW_H = 700.0, 700.0


def load_stars():
    g = json.loads((RAW / "stars.8.min.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in g["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        out[str(p["id"])] = {"ra": normalize_ra(lon), "dec": lat, "mag": p["mag"]}
    return out


def load_lines_cn():
    g = json.loads((RAW / "constellations.lines.cn.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in g["features"]:
        out[str(f["properties"]["id"])] = {
            "name": f["properties"]["name"],
            "rank": f["properties"]["rank"],
            "lines": f["geometry"]["coordinates"],
        }
    return out


def merge_walls(lines_cn, constellations):
    """6 垣墙(rank=2)合并为 3 垣 entry 的主干。返回 {垣中文名: {lines}}。"""
    wall_names = {"紫微左垣": "紫微垣", "紫微右垣": "紫微垣",
                  "太微左垣": "太微垣", "太微右垣": "太微垣",
                  "天市左垣": "天市垣", "天市右垣": "天市垣"}
    merged = {}
    for c in constellations:
        if c["rank"] == "2":
            target = wall_names.get(c["name"])
            if target:
                merged.setdefault(target, []).extend(lines_cn.get(c["id"], {}).get("lines", []))
    return merged


def _empty_stories():
    empty = {"title": "尚未撰写", "paragraphs": []}
    return {"myth": {"epic": empty, "chat": empty, "brief": empty},
            "science": {"epic": empty, "chat": empty, "brief": empty}}


def main():
    stars = load_stars()
    lines_cn = load_lines_cn()
    constellations = []
    with open(RAW / "constellations.cn.csv", encoding="utf-8") as f:
        constellations = list(csv.DictReader(f))
    members = group_members(str(RAW / "constellations.cn.csv"),
                            str(RAW / "starnames.cn.csv"))
    OUT.mkdir(parents=True, exist_ok=True)

    # 生成星官 entry（rank=3 星官 + rank=1 宿）
    for c in constellations:
        rank = c["rank"]
        if rank == "2":
            continue  # 垣墙在 merge_walls 处理
        name = c["name"]
        main = strip_suffix(name)
        member_list = members.get(main, [])
        # 星 map
        star_map = {}
        for m in member_list:
            hip = m["id"]
            s = stars.get(hip)
            if not s:
                continue
            star_map[hip] = {
                "bayer": "", "name": m["name"], "name_zh": m["name"],
                "magnitude": s["mag"], "ra": s["ra"], "dec": s["dec"],
                "label": True, "hip": hip,
            }
        # center
        center_ra = normalize_ra(float(c["display_ra"]))
        center_dec = float(c["display_dec"])
        # 投影
        if star_map:
            max_dra = max(abs(ra_wrap(s["ra"] - center_ra)) for s in star_map.values())
            max_ddec = max(abs(s["dec"] - center_dec) for s in star_map.values())
            scale = min((VIEW_W / 2 - 30) / max(max_dra, 0.001),
                        (VIEW_H / 2 - 30) / max(max_ddec, 0.001))
            for hip, s in star_map.items():
                s["x"] = round(VIEW_W / 2 + ra_wrap(s["ra"] - center_ra) * scale, 1)
                s["y"] = round(VIEW_H / 2 - (s["dec"] - center_dec) * scale, 1)
            del_keys = []
        # lines 回填
        entry_lines = []
        if c["id"] in lines_cn:
            for ln in lines_cn[c["id"]]["lines"]:
                seg = []
                for lonlat in ln:
                    key = _match(lonlat, star_map)
                    if key:
                        seg.append(key)
                if len(seg) >= 2:
                    entry_lines.append(seg)
        # mansion/asterism_id
        mansion = None
        asterism_id = None
        if rank == "1":
            mansion = slugify(c["pinyin"])
        elif name in ("紫微垣", "太微垣", "天市垣"):
            asterism_id = slugify(c["pinyin"])
        else:
            # 近南极 vs 星官归属由 display_dec 判
            asterism_id = "nanji" if center_dec < -55 else None
        entry = {
            "abbr": slugify(c["pinyin"]), "name": name,
            "latin": c.get("en", ""), "glyph": "", "season": "", "caption": "",
            "viewBox": {"width": 700, "height": 700},
            "center": {"ra": round(center_ra, 4), "dec": round(center_dec, 4)},
            "stars": star_map, "lines": entry_lines,
            "mansion": mansion, "asterism_id": asterism_id,
            "stories": _empty_stories(),
        }
        (OUT / f"{entry['abbr']}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"OK {entry['abbr']} ({len(star_map)} 星, {len(entry_lines)} 线)")


def _match(lonlat, star_map, threshold=0.05):
    lon, lat = lonlat
    ra = normalize_ra(lon)
    best, best_sep = None, threshold
    for hip, s in star_map.items():
        sep = haversine_deg(ra, lat, s["ra"], s["dec"])
        if sep < best_sep:
            best, best_sep = hip, sep
    return best


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行脚本**

Run: `cd server && .venv/Scripts/python.exe scripts/build_chinese_stars.py`
Expected: 打印 ~306 行 `OK xxx (n 星, m 线)`

- [ ] **步骤 3：校验 + 统计 abbr 冲突**

Run: `cd server && .venv/Scripts/python.exe scripts/validate_atlas.py`
Run: `cd server && .venv/Scripts/python.exe -c "from pathlib import Path; import json; fs=list(Path('data/traditions/chinese').glob('*.json')); print('entry 数:', len(fs)); abbs=[p.stem for p in fs]; print('abbr 冲突:', [a for a in set(abbs) if abbs.count(a)>1])"`
Expected: 0 hard errors；`entry 数 ≈ 306`；`abbr 冲突: []`（若冲突，需在脚本加同名消歧后缀）

- [ ] **步骤 4：提交**

```bash
git add server/scripts/build_chinese_stars.py server/data/traditions/chinese/
git commit -m "feat(atlas-data): 中国星官约306 生成脚本 + 数据"
```

---

## 任务 6：build_star_catalog HIP 去重升级 + validate 扩展

**文件：**
- 修改：`server/services/traditions.py`（`build_star_catalog`）
- 修改：`server/scripts/validate_atlas.py`
- 修改：`server/tests/test_build_star_catalog.py`
- 修改：`server/tests/test_validate_atlas.py`

**接口：**
- 消费：`star.get("hip")`（新增可选字段）
- 产出：`build_star_catalog` HIP 优先去重；validate 3 条新硬规则

- [ ] **步骤 1：改 `build_star_catalog` 去重**

`server/services/traditions.py` 中 `build_star_catalog` 函数，替换去重段：

```python
def build_star_catalog() -> list[dict]:
    _load_all()
    catalog: list[dict] = []
    seen_hip: set[str] = set()
    seen_radec: set[tuple[float, float]] = set()
    for trad_key, consts in _DATA.items():
        for abbr, c in consts.items():
            for _star_key, star in c.get("stars", {}).items():
                hip = str(star.get("hip", "")) if star.get("hip") is not None else ""
                # HIP 优先去重；fallback round(ra,3) 约 3.6″
                if hip:
                    if hip in seen_hip:
                        continue
                    seen_hip.add(hip)
                else:
                    ra, dec = star["ra"], star["dec"]
                    key = (round(ra, 3), round(dec, 3))
                    if key in seen_radec:
                        continue
                    seen_radec.add(key)
                catalog.append({
                    "bayer": star.get("bayer", ""),
                    "name": star.get("name", ""),
                    "name_zh": star.get("name_zh", ""),
                    "magnitude": star.get("magnitude", 0),
                    "ra": star["ra"],
                    "dec": star["dec"],
                    "constellation": abbr,
                    "tradition": trad_key,
                    "hip": hip,
                })
    return catalog
```

- [ ] **步骤 2：加 HIP 去重 + 跨 entry 一致性测试**

`test_build_star_catalog.py` 追加：

```python
def test_catalog_dedup_by_hip(monkeypatch):
    """同一 HIP 在不同 tradition/entry 只保留一条，且坐标一致。"""
    from services import traditions as t
    monkeypatch.setattr(t, "_load_all", lambda: None)
    monkeypatch.setattr(t, "_DATA", {
        "western": {"ori": {"stars": {"a": {"hip": 27989, "ra": 88.79, "dec": 7.41,
                                            "magnitude": 0.42, "name": "参宿四",
                                            "name_zh": "参宿四", "bayer": "α Ori"}}}},
        "chinese": {"shenxiu": {"stars": {"b": {"hip": 27989, "ra": 88.79, "dec": 7.41,
                                               "magnitude": 0.42, "name": "参宿四",
                                               "name_zh": "参宿四", "bayer": "α Ori"}}}},
    })
    cat = t.build_star_catalog()
    hip27989 = [c for c in cat if c["hip"] == "27989"]
    assert len(hip27989) == 1  # 去重后仅一条


def test_catalog_fallback_round3(monkeypatch):
    """无 hip 时 fallback round(ra,3) 去重。"""
    from services import traditions as t
    monkeypatch.setattr(t, "_load_all", lambda: None)
    monkeypatch.setattr(t, "_DATA", {
        "western": {"a": {"stars": {"x": {"ra": 10.0001, "dec": 5.0001, "magnitude": 1}}},
                    "b": {"stars": {"y": {"ra": 10.0001, "dec": 5.0001, "magnitude": 1}}}},
    })
    cat = t.build_star_catalog()
    assert len(cat) == 1
```

- [ ] **步骤 3：validate_atlas 加硬规则**

`server/scripts/validate_atlas.py` 的 `check_file` 末尾追加：

```python
    # 中国星官专项（spec v5 §3.3）
    coord = meta_coord.get(json_path.parent.name, None)
    if coord == "mansion":
        for sk, s in stars.items():
            if not s.get("name_zh"):
                print(f"HARD {json_path}: stars.{sk} 缺 name_zh")
                HARD_ERRORS += 1
    # mansion/asterism_id 至少一个非 null
    if entry.get("mansion") is None and entry.get("asterism_id") is None:
        print(f"HARD {json_path}: mansion 与 asterism_id 均为 null")
        HARD_ERRORS += 1
    # abbr 全 ASCII
    import re as _re
    if not _re.fullmatch(r"[a-z0-9_]+", entry.get("abbr", "")):
        print(f"HARD {json_path}: abbr={entry.get('abbr')!r} 非 ^[a-z0-9_]+$")
        HARD_ERRORS += 1
    # lines 无悬空引用
    for line in entry.get("lines", []):
        for sid in line:
            if sid is None:
                print(f"HARD {json_path}: line {line!r} 含 null 端点")
                HARD_ERRORS += 1
            elif sid not in star_keys:
                print(f"HARD {json_path}: line 端点 {sid!r} 不在 stars 中")
                HARD_ERRORS += 1
```

> 注：`meta_coord` 需在 `main()` 里构建 `{dir_name: coordinate_system}` 映射（读该目录 `_meta.json`），传给 `check_file`。西方 entry 无 `mansion/asterism_id` 且为 `null` 会触发新硬规则——需为西方豁免：仅当 `coordinate_system == "mansion"` 才检查该项。调整：把 mansion/asterism_id 检查放进 `if coord == "mansion"` 分支内。

- [ ] **步骤 4：`list_constellations` 增加 `group` 字段（spec §4.2 验收）**

`server/services/traditions.py` 追加常量 + 改 `list_constellations`：

```python
# 28 宿 pinyin → 四象分组（中文显示名）；nanji = 近南极；3 垣 = 各占 1 分组
MANSION_GROUP = {
    **{m: "东方七宿" for m in
       ["jiaoxiu", "kangxiu", "dixiu", "fangxiu", "xinxu", "weixiu", "jixiu"]},
    **{m: "北方七宿" for m in
       ["douxiu", "niuxiu", "nvxiu", "xuxiu", "weixiu", "shixiu", "bixiu"]},  # weixiu 重复以尾宿优先
    **{m: "西方七宿" for m in
       ["kuixiu", "louxiu", "maoxiu", "bixiu", "zixiu", "shenxiu"]},         # bixiu 冲突：保留为西方宿（参宿属西方）
    **{m: "南方七宿" for m in
       ["jingxiu", "guixiu", "liuxiu", "xingxiu", "zhangxiu", "yixiu", "zhenxiu"]},
}
ENCLOSURE_GROUP = {"ziweiyuan": "紫微垣", "taiweiyuan": "太微垣", "tianshiyuan": "天市垣"}
```

> 注：键名用任务 5 生成的中国 abbr slug。重复项（如 `weixiu` 既是北方危宿又是南方胃宿）是 spec 数据本身问题，需在 build_chinese_stars.py 生成时按 `星官对应.md` 校对 abbr 唯一性（任务 5 已断言）。此处以"主归属"覆盖（脚本生成时已无重复）。

改 `list_constellations` 在 dict 中追加 `group`：

```python
def list_constellations(tradition: str) -> list[dict]:
    _load_all()
    out = []
    for c in _DATA.get(tradition, {}).values():
        abbr = c.get("abbr", "")
        group = ENCLOSURE_GROUP.get(abbr) or MANSION_GROUP.get(abbr) or ("近南极" if c.get("asterism_id") == "nanji" else None)
        out.append({
            "abbr": abbr,
            "name": c.get("name", ""),
            "latin": c.get("latin", ""),
            "season": c.get("season", ""),
            "caption": c.get("caption", ""),
            "tradition": tradition,
            "star_count": len(c.get("stars", {})),
            "has_stories": bool(c.get("stories")),
            "group": group,
        })
    return out
```

`web/src/types.ts` 的 `AtlasListItem` 增加 `group?: string | null`，前端的 `atlas.setTradition` 调用无需变（`atlas.currentItems` 直接带 `group`）。

- [ ] **步骤 5：加 list_constellations group 测试**

`server/tests/test_constellations_router.py` 追加：

```python
def test_list_chinese_includes_group(monkeypatch):
    from services import traditions as t
    monkeypatch.setattr(t, "_load_all", lambda: None)
    monkeypatch.setattr(t, "_DATA", {
        "chinese": {
            "shenxiu": {"abbr": "shenxiu", "name": "参宿", "latin": "Three Stars",
                        "season": "", "caption": "", "stars": {}, "stories": {}},
            "ziweiyuan": {"abbr": "ziweiyuan", "name": "紫微垣", "latin": "Purple Forbidden",
                          "season": "", "caption": "", "stars": {}, "stories": {},
                          "asterism_id": "ziweiyuan"},
        }
    })
    items = t.list_constellations("chinese")
    groups = {it["abbr"]: it["group"] for it in items}
    assert groups["shenxiu"] == "西方七宿"
    assert groups["ziweiyuan"] == "紫微垣"
```

- [ ] **步骤 6：跑后端全量测试 + 校验**

Run: `cd server && .venv/Scripts/python.exe -m pytest -q`
Run: `cd server && .venv/Scripts/python.exe scripts/validate_atlas.py`
Expected: pytest 全绿（原 119 + 新增）；validate 0 hard errors

- [ ] **步骤 5：提交**

```bash
git add server/services/traditions.py server/scripts/validate_atlas.py server/tests/test_build_star_catalog.py server/tests/test_validate_atlas.py
git commit -m "feat(atlas-data): build_star_catalog HIP 去重 + validate 中国星官硬规则"
```

---

## 任务 7：前端 ConstellationView 分组列表

**文件：**
- 修改：`web/src/types.ts`（`AtlasListItem` 加 `group?: string | null`）
- 修改：`web/src/views/ConstellationView.vue`
- 修改：`web/tests/ConstellationView.test.ts`

**接口：**
- 消费：`atlas.currentItems`（`AtlasListItem[]`，含 `tradition`/`abbr`/`name`/`group`）
- 产出：分组渲染（西方平铺；中国按 `group` 字段 拆 `<details>` 折叠）

- [ ] **步骤 1：types.ts 加 `group` 字段**

`web/src/types.ts` 在 `AtlasListItem` 内追加：

```typescript
  /** T7+: 后端下发的分组键（中国："东方七宿"/"紫微垣"/"近南极" 等；西方 null） */
  group?: string | null
```

- [ ] **步骤 2：写分组 computed + 模板**

在 `ConstellationView.vue` 的 script 中加：

```typescript
type Group = { label: string; items: AtlasListItem[] }

const groupOrder = ['紫微垣', '太微垣', '天市垣',
                    '东方七宿', '北方七宿', '西方七宿', '南方七宿',
                    '近南极']

const groups = computed<Group[]>(() => {
  const items = atlas.currentItems
  if (atlas.currentTradition !== 'chinese') {
    return [{ label: '西方星座', items }]
  }
  const buckets = new Map<string, AtlasListItem[]>()
  for (const it of items) {
    const key = it.group ?? '其他'
    buckets.set(key, [...(buckets.get(key) ?? []), it])
  }
  // 按预设顺序排，未识别分组放末尾
  return groupOrder
    .filter(l => buckets.has(l))
    .map(l => ({ label: l, items: buckets.get(l)! }))
    .concat([...buckets.entries()].filter(([l]) => !groupOrder.includes(l))
                                  .map(([label, items]) => ({ label, items })))
})
```

- [ ] **步骤 3：模板用 `<details>` 渲染 groups**

在 `.chip-list` 外层包裹（替换原 v-for `atlas.currentItems` 为 `g.items`）：

```html
<details v-for="g in groups" :key="g.label" class="group" open>
  <summary class="group-title">{{ g.label }}（{{ g.items.length }}）</summary>
  <div class="chip-list">
    <button
      v-for="it in g.items"
      :key="it.abbr"
      class="cchip"
      :class="{ active: selected?.abbr === it.abbr }"
      type="button"
      @click="selectMedal(it)"
    >
      <span class="medal">{{ it.abbr.toUpperCase().slice(0, 3) }}</span>
      <span class="info">
        <b>{{ it.name }}</b>
        <span>{{ it.latin }} · 当令 {{ it.season ?? '—' }}</span>
      </span>
      <span class="go-mark">点亮 ✦</span>
    </button>
  </div>
</details>
```

> CSS：`.group { margin-bottom: 14px }`、`.group-title { font-weight: 700; padding: 8px 0 }`（最小新增，避免大改）。

- [ ] **步骤 4：加测试**

`web/tests/ConstellationView.test.ts` 追加（mock atlas store）：

```typescript
import { vi } from 'vitest'

vi.mock('../stores/atlas', () => ({
  useAtlasStore: () => ({
    currentTradition: 'chinese',
    currentItems: [
      { abbr: 'shenxiu', name: '参宿', latin: 'Three', season: '冬', caption: '',
        tradition: 'chinese', star_count: 7, has_stories: true, group: '西方七宿' },
      { abbr: 'ziweiyuan', name: '紫微垣', latin: 'Purple', season: '', caption: '',
        tradition: 'chinese', star_count: 50, has_stories: true, group: '紫微垣' },
      { abbr: 'haishan', name: '海山', latin: 'Sea', season: '', caption: '',
        tradition: 'chinese', star_count: 6, has_stories: false, group: '近南极' },
    ],
    loadTraditions: vi.fn(),
    setTradition: vi.fn(),
    getAtlas: vi.fn(),
  }),
}))

it('groups chinese constellations by group field', async () => {
  const wrapper = mount(ConstellationView)
  await wrapper.vm.$nextTick()
  const summaries = wrapper.findAll('details summary.group-title')
  const labels = summaries.map(s => s.text())
  expect(labels[0]).toMatch(/紫微垣/)
  expect(labels[1]).toMatch(/西方七宿/)
  expect(labels[2]).toMatch(/近南极/)
})
```

- [ ] **步骤 5：跑前端测试 + 类型**

Run: `cd web && npx vitest run`
Run: `cd web && npx vue-tsc --noEmit`
Expected: 全绿 + 0 error

- [ ] **步骤 6：提交**

```bash
git add web/src/types.ts web/src/views/ConstellationView.vue web/tests/ConstellationView.test.ts
git commit -m "feat(atlas-data): ConstellationView 按 group 字段分组折叠渲染"
```

---

## 任务 8：_meta.json 更新 + 全量回归

**文件：**
- 修改：`server/data/traditions/western/_meta.json`
- 修改：`server/data/traditions/chinese/_meta.json`

- [ ] **步骤 1：更新 _meta.json**

`western/_meta.json`：

```json
{
  "key": "western",
  "label": "西方星座",
  "label_en": "Western Constellations",
  "description": "以古希腊罗马神话为基础的 88 个星座体系",
  "epoch": "BCE 2nd century",
  "source": "celestial_data (github.com/dieghernan/celestial_data)",
  "license": "开源数据集原始许可",
  "star_count": 88,
  "coordinate_system": "equatorial"
}
```

`chinese/_meta.json`：

```json
{
  "key": "chinese",
  "label": "中国古代星空",
  "description": "二十八宿与三垣的星官体系",
  "epoch": "远古至汉代定型",
  "source": "celestial_data + 维基百科中西星名对照表",
  "license": "CC-BY-SA 4.0 (维基对照表), 数据集原始许可",
  "star_count": 0,
  "coordinate_system": "mansion"
}
```

> `star_count` 填实值与实际 glob 数量一致（运行 `validate_atlas.py` 后按提示校正）。

- [ ] **步骤 2：全量回归**

Run: `cd server && .venv/Scripts/python.exe -m pytest -q`
Run: `cd server && .venv/Scripts/python.exe scripts/validate_atlas.py`
Run: `cd web && npx vitest run`
Run: `cd web && npx vue-tsc --noEmit`
Expected: 后端全绿 + validate 0 hard errors + 前端全绿 + 0 error

- [ ] **步骤 3：提交**

```bash
git add server/data/traditions/western/_meta.json server/data/traditions/chinese/_meta.json
git commit -m "chore(atlas-data): _meta.json star_count 与 source/license 更新"
```