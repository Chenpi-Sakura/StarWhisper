"""从 server/data/raw/ 重生西方 88 星座 JSON。

数据源（按 controller pre-flight 7 条修正）：
- constellations.lines.geojson    89 features（Ser 分 Caput/Cauda 两段，合并为 88 entry）
  - geometry.type = MultiLineString（3 层嵌套）
  - coordinates 是 [lon, lat]，不是 HIP；通过最近邻匹配到 stars.8.min.geojson
- stars.8.min.geojson             id 是 HIP，coordinates 是 [lon, lat]
  - ra = lon % 360（python 对负数 mod 360 仍返回正数）
  - dec = lat
- starnames.csv                   hip 列形如 "HIP 24436"，需 split + int
  - name = 英文常用名（如 "Rigel"）
  - bayer = 拜尔字母（"β"、"α"）
  - zh = 中文古名（如 "参宿七"）
- constellations.csv              id = abbr（如 "Ori"），提供 en / la / zh / name
  - 无 hip / ra / dec 列（仅元数据表）

收录规则（controller ruling 6）：
- 不用边界（constellations.boundaries.csv 不存在）
- 仅 line 端点 → 最近邻 HIP（≤ 0.5°）；未匹配则丢该 line segment
- 端点共用的星自然去重
- LABEL_MAG_THRESHOLD = 4.5：mag < 4.5 → label: true

字段策略：
- abbr：lines.id（如 "Ori"）→ 小写
- name：constellations.csv.en（"Orion"）
- name_zh：constellations.csv.zh
- latin：constellations.csv.la
- season：优先旧 JSON（"冬季"→"winter"），否则按 RA 推季节
- caption / glyph / stories：保留旧 JSON
"""
from __future__ import annotations
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.atlas_projection import compute_field, compute_center, project  # noqa: E402

RAW = ROOT / "data" / "raw"
WESTERN_DIR = ROOT / "data" / "traditions" / "western"
ASSETS = ROOT / "data" / "traditions" / "western"  # missing-*.md 也写这里便于定位

VIEWBOX = {"w": 700, "h": 700}
PADDING = 30
LABEL_MAG_THRESHOLD = 4.5
MATCH_THRESHOLD_DEG = 0.5
LAT_PRE_FILTER_DEG = 1.0  # 加速用：先按 |lat - lat0| 过滤


# ----------------------------------------------------------------------------
# 简繁转换（CSV zh 列混合繁简，统一为简体）
# ----------------------------------------------------------------------------
# 优先 opencc-python-reimplemented；如未安装则用 _T2S dict 兜底（仅覆盖 CSV 实际差异字）。
# 当前 CSV 中实际出现 42 个差异字（基于 constellations.csv + starnames.csv 扫描）。
_T2S: dict[str, str] = {
    "儀": "仪", "劍": "剑", "圓": "圆", "壇": "坛", "寶": "宝",  # 仪剑圆坛宝
    "戶": "户", "搖": "摇", "時": "时", "極": "极", "烏": "乌",  # 户摇时极乌
    "爐": "炉", "獅": "狮", "獵": "猎", "盤": "盘", "網": "网",  # 炉狮猎盘网
    "繪": "绘", "羅": "罗", "蒼": "苍", "處": "处", "蠅": "蝇",  # 绘罗苍处蝇
    "蠍": "蝎", "規": "规", "貓": "猫", "遠": "远", "鏡": "镜",  # 蝎规猫远镜
    "鐘": "钟", "長": "长", "雙": "双", "顯": "显", "飛": "飞",  # 钟长双显飞
    "馬": "马", "髮": "发", "魚": "鱼", "鯨": "鲸", "鳳": "凤",  # 马发鱼鲸凤
    "鴉": "鸦", "鴿": "鸽", "鵑": "鹃", "鵝": "鹅", "鶴": "鹤",  # 鸦鸽鹃鹅鹤
    "鷹": "鹰", "龍": "龙",
}


def t2s(text: str) -> str:
    """繁体 → 简体（保留简体的 noop）。

    优先 opencc-python-reimplemented；如未安装则用 _T2S dict 兜底（仅覆盖 CSV 实际差异字）。
    """
    if not text:
        return text
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except ImportError:
        return "".join(_T2S.get(c, c) for c in text)


# ----------------------------------------------------------------------------
# 加载器
# ----------------------------------------------------------------------------
def load_lines_geojson() -> dict[str, list[list[tuple[float, float]]]]:
    """abbr → MultiLineString groups (each = [(lon, lat), ...])。

    Ser 在源数据里有两个 features，合并到同一 key 'ser'。
    """
    path = RAW / "constellations.lines.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[list[tuple[float, float]]]] = {}
    for feat in data["features"]:
        abbr_upper = feat["properties"]["id"]
        abbr = abbr_upper.lower()  # "Ori" → "ori"
        geom = feat["geometry"]
        if geom["type"] != "MultiLineString":
            # 防御：当前数据全是 MultiLineString，但万一
            continue
        groups = []
        for line in geom["coordinates"]:
            # 3 层嵌套：MultiLineString.coords = [[ [lon,lat], ... ], ...]
            # 每条 line 是一串点
            groups.append([(float(pt[0]), float(pt[1])) for pt in line])
        out.setdefault(abbr, []).extend(groups)
    return out


def load_stars() -> dict[str, dict]:
    """hip（str 形式，如 "27989"）→ {ra, dec, mag}。

    ra = lon % 360（python `lon % 360` 对负数返回正数，0..360）
    """
    path = RAW / "stars.8.min.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data["features"]:
        p = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        hip = str(int(p["id"]))
        out[hip] = {
            "ra": lon % 360.0,
            "dec": float(lat),
            "mag": float(p["mag"]),
        }
    return out


def load_starnames() -> dict[str, dict]:
    """hip → {name (en), bayer, zh}。

    hip 列形如 "HIP 24436"（带 prefix + 不间断空格），split 取数字。
    """
    path = RAW / "starnames.csv"
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hip_raw = (row.get("hip") or "").strip()
            if not hip_raw:
                continue
            # 形如 "HIP 24436" → 24436
            digits = "".join(c for c in hip_raw if c.isdigit())
            if not digits:
                continue
            out[digits] = {
                "name": (row.get("name") or "").strip(),
                "bayer": (row.get("bayer") or "").strip(),
                "zh": (row.get("zh") or "").strip(),
            }
    return out


def load_starnames_cn() -> dict[str, dict]:
    """hip → {name (zh 中国传统名), bayer, en (English)}。

    现代中国天文文化星名（starnames.cn.csv）。用作 starnames.csv 的 zh 字段
    fallback——starnames.csv 中很多西方 IAU 体系暗星 zh=NA，但
    starnames.cn.csv 里仍有中国传统星官名（如 鹿豹 HIP 29997=上卫增二、
    狐狸 HIP 94703=齐增三、鹿豹 HIP 17884=上丞增一）。

    字段格式：id, name, desig, en, pinyin — id 是 HIP 数字字符串。
    """
    path = RAW / "starnames.cn.csv"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hip = (row.get("id") or "").strip()
            name = (row.get("name") or "").strip()
            if not hip or not name or name == "NA":
                continue
            out[hip] = {
                "name": name,
                "bayer": (row.get("desig") or "").strip(),
                "en": (row.get("en") or "").strip(),
            }
    return out


def load_constellations_csv() -> dict[str, dict]:
    """abbr → {en, la, zh, name, display_ra, display_dec, display_scale}。

    abbr = csv.id（如 "Ori"）；小写化后用作 JSON 文件名和 entry.abbr。
    """
    path = RAW / "constellations.csv"
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            abbr_upper = (row.get("id") or "").strip()
            if not abbr_upper:
                continue
            abbr = abbr_upper.lower()
            out[abbr] = {
                "en": (row.get("en") or "").strip(),
                "la": (row.get("la") or "").strip(),
                "zh": (row.get("zh") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "display_ra": (row.get("display_ra") or "").strip(),
                "display_dec": (row.get("display_dec") or "").strip(),
                "display_scale": (row.get("display_scale") or "").strip(),
            }
    return out


# ----------------------------------------------------------------------------
# 端点 → HIP 匹配
# ----------------------------------------------------------------------------
def match_endpoint(
    lon: float, lat: float, stars_db: dict[str, dict]
) -> tuple[str | None, float]:
    """最近邻匹配（球面余弦 + lat 预过滤）。

    返回 (hip_or_None, sep_deg)。sep >= MATCH_THRESHOLD_DEG 视为无匹配。
    """
    ra = lon % 360.0
    candidates = [
        (hip, s) for hip, s in stars_db.items()
        if abs(s["dec"] - lat) < LAT_PRE_FILTER_DEG
    ]
    if not candidates:
        return None, float("inf")
    best, best_sep = None, MATCH_THRESHOLD_DEG
    for hip, s in candidates:
        sep = _angsep(ra, lat, s["ra"], s["dec"])
        if sep < best_sep:
            best, best_sep = hip, sep
    return best, best_sep


def _angsep(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """球面余弦定理算角距（度）。"""
    dra = math.radians(ra1 - ra2)
    cos_c = (
        math.sin(math.radians(dec1)) * math.sin(math.radians(dec2))
        + math.cos(math.radians(dec1)) * math.cos(math.radians(dec2))
        * math.cos(dra)
    )
    cos_c = max(-1.0, min(1.0, cos_c))
    return math.degrees(math.acos(cos_c))


# ----------------------------------------------------------------------------
# 季节推断 / 字段映射
# ----------------------------------------------------------------------------
_SEASON_ZH_TO_EN = {
    "冬季": "winter", "春天": "spring", "春季": "spring",
    "夏季": "summer", "秋天": "autumn", "秋季": "autumn",
}


def map_season(old: str, center_ra: float) -> str:
    """优先旧 JSON（中文 → 英文），否则按 RA 推。

    RA 0-6h ∪ 18-24h = winter；6-12h = spring；12-18h = summer。
    """
    if old:
        mapped = _SEASON_ZH_TO_EN.get(old)
        if mapped:
            return mapped
        # 已经是英文？
        if old in {"winter", "spring", "summer", "autumn"}:
            return old
    h = (center_ra / 15.0) % 24
    if h < 6 or h >= 18:
        return "winter"
    if h < 12:
        return "spring"
    if h < 18:
        return "summer"
    return "autumn"


# ----------------------------------------------------------------------------
# 星星名选取（中文优先，回退英文，再回退 bayer）
# ----------------------------------------------------------------------------
def _pick_star_zh(sn: dict) -> str:
    """从 starnames 行选中文名（"NA" → ""，混合繁简 t2s，复合名拆简单名）。

    starnames.csv 的 zh 列对三垣恒星会写"太微左垣二 东上相"这种
    enclosure+wall+position+name 复合名。前端 displayNameFor 也拆，但 build
    阶段拆一次可避免下游每个用到 name/name_zh 的地方都要复制 split 逻辑。
    规则：含空格且第一段含"太微/紫微/天市" → 取最后一段（星名本身）。
    """
    raw = (sn.get("zh") or "").strip()
    if not raw or raw == "NA":
        return ""
    raw = t2s(raw)
    if " " in raw and any(c in raw[: raw.index(" ")] for c in "太微紫微天市"):
        raw = raw.split()[-1]
    return raw


def _pick_star_primary_name(sn: dict) -> str:
    """星星主名：中文 > 英文 > bayer。"""
    zh = _pick_star_zh(sn)
    if zh:
        return zh
    en = (sn.get("name") or "").strip()
    if en:
        return en
    return (sn.get("bayer") or "").strip()


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def _resolve_zh(hip: str, sn: dict, starnames_cn: dict[str, dict] | None) -> str:
    """中文名：starnames.csv 的 zh 优先；空时 fallback 到 starnames.cn.csv"""
    zh = (sn.get("zh") or "").strip()
    if zh and zh != "NA":
        return zh
    if starnames_cn:
        cn = starnames_cn.get(hip, {}).get("name", "").strip()
        if cn and cn != "NA":
            return cn
    return ""


def build_one(
    abbr: str,
    line_groups: list[list[tuple[float, float]]],
    stars_db: dict[str, dict],
    starnames: dict[str, dict],
    csv_row: dict,
    old_json: dict | None,
    starnames_cn: dict[str, dict] | None = None,
) -> tuple[dict, list[str]]:
    """生成单个星座 entry。

    Returns: (entry, unmatched_endpoint_count)
    """
    # 1. 收集所有 line 端点 → 唯一端点集
    all_points: list[tuple[float, float]] = []
    for group in line_groups:
        all_points.extend(group)

    # 2. 端点 → HIP 匹配
    endpoint_hips: list[str | None] = []
    unmatched = 0
    for lon, lat in all_points:
        hip, _ = match_endpoint(lon, lat, stars_db)
        endpoint_hips.append(hip)
        if hip is None:
            unmatched += 1

    # 3. 收集出现过的唯一 HIP + 配对 lines
    seen_hips: dict[str, None] = {}  # ordered set (Python 3.7+ dict 保序)
    new_lines: list[list[str]] = []
    idx = 0
    for group in line_groups:
        group_hips = endpoint_hips[idx: idx + len(group)]
        idx += len(group)
        for i in range(len(group_hips) - 1):
            a, b = group_hips[i], group_hips[i + 1]
            if a is None or b is None:
                continue
            new_lines.append([f"HIP_{a}", f"HIP_{b}"])
            seen_hips.setdefault(a, None)
            seen_hips.setdefault(b, None)

    # 4. stars dict（HIP-keyed）
    star_coords: list[dict] = []
    bright_coords: list[dict] = []  # 用来算 center（mag < LABEL_MAG_THRESHOLD）
    stars_dict: dict[str, dict] = {}
    for hip in seen_hips:
        s = stars_db[hip]
        sn = starnames.get(hip, {})
        cn_zh = _resolve_zh(hip, sn, starnames_cn)
        is_bright = s["mag"] < LABEL_MAG_THRESHOLD
        star_coords.append({"ra": s["ra"], "dec": s["dec"]})
        if is_bright:
            bright_coords.append({"ra": s["ra"], "dec": s["dec"]})
        primary_name = cn_zh or (sn.get("name") or "").strip() or (sn.get("bayer") or "").strip() or f"HIP {hip}"
        stars_dict[f"HIP_{hip}"] = {
            "bayer": sn.get("bayer", ""),
            "name": primary_name,
            "name_zh": cn_zh,
            "name_en": (sn.get("name") or "").strip(),
            "magnitude": s["mag"],
            "ra": s["ra"],
            "dec": s["dec"],
            # 全部标：displayNameFor 退到 bayer（α/β/γ/δ）也是有效标识，
            # dim 星（mag 4+）fontSize 自动缩到 8px，不会 clutter。
            # 否则小星座（如 Scutum 4 星、γ mag 4.67 / δ mag 4.70）会被
            # LABEL_MAG_THRESHOLD 误伤，bayer 字母也看不到。
            "label": True,
            "hip": hip,
        }

    # 5. 投影
    # center 用「亮星」（label=true, mag < 4.5）算 3D 向量均值——
    # 全部 line 端点含很多暗星（4~5 mag 周边），平均会偏离视觉中心。
    # 例：Orion 8 主星（< 4.5）→ 3D mean (83.96, 0.30)，与 spec 示例 (83.96, -2.5) 接近；
    # 全部 24 端点 → (81.49, 6.98)，偏离 belt 太远。
    # scale 用全成员最大角距，避免暗星被裁出 viewBox。
    if star_coords:
        # center: 优先亮星均值，退到全成员
        if bright_coords and len(bright_coords) >= 3:
            center_ra, center_dec = compute_center(bright_coords)
        else:
            center_ra, center_dec = compute_center(star_coords)
        # scale: 全成员最大角距
        from scripts.atlas_projection import angular_separation as _angsep2
        max_c = max(
            _angsep2(s["ra"], s["dec"], center_ra, center_dec)
            for s in star_coords
        )
        if max_c > 170.0:
            raise ValueError(
                f"{abbr}: 成员存在接近对跖点（max_c={max_c:.1f}° > 170°）"
            )
        if max_c < 1e-6:
            scale = 1.0
        else:
            max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
            scale = min(
                (VIEWBOX["w"] / 2.0 - PADDING) / max_radius,
                (VIEWBOX["h"] / 2.0 - PADDING) / max_radius,
            )
        for key, star in stars_dict.items():
            x, y = project(
                star["ra"], star["dec"],
                center_ra, center_dec,
                scale, VIEWBOX,
            )
            star["x"] = round(x, 1)
            star["y"] = round(y, 1)
    else:
        # 退路（理论上不会发生：所有端点都失配）
        center_ra, center_dec = 0.0, 0.0

    # 6. 字段拼装
    # 主名 = 简化后的中文（CSV zh 列混合繁简，统一为简体）
    zh_raw = (csv_row.get("zh") or "").strip()
    name_zh = t2s(zh_raw)  # 简化后的中文
    name = name_zh  # 主名 = 中文（用户反馈要求）
    name_en = (csv_row.get("en") or "").strip()  # 英文（新增字段，做副标题备选）
    latin = (csv_row.get("la") or csv_row.get("en") or "").strip()

    old = old_json or {}
    season = map_season(old.get("season", ""), center_ra)
    caption = old.get("caption", "")
    glyph = old.get("glyph", "")
    stories = old.get("stories", {}) or {}

    entry = {
        "abbr": abbr,
        "name": name,
        "name_zh": name_zh,
        "name_en": name_en,
        "latin": latin,
        "glyph": glyph,
        "season": season,
        "caption": caption,
        "viewBox": {"width": VIEWBOX["w"], "height": VIEWBOX["h"]},
        "center": {"ra": round(center_ra, 4), "dec": round(center_dec, 4)},
        "stars": stars_dict,
        "lines": new_lines,
        "mansion": None,
        "asterism_id": None,
        "stories": stories,
    }
    return entry, [str(unmatched)]


def main() -> None:
    print("Loading data sources...")
    lines_db = load_lines_geojson()
    stars_db = load_stars()
    starnames = load_starnames()
    starnames_cn = load_starnames_cn()
    csv_db = load_constellations_csv()
    print(f"  lines_db: {len(lines_db)} abbrs (raw features merged)")
    print(f"  stars_db: {len(stars_db)} HIPs")
    print(f"  starnames: {len(starnames)} entries")
    print(f"  starnames_cn: {len(starnames_cn)} entries (现代中国天文文化 fallback)")
    print(f"  csv_db: {len(csv_db)} entries")

    # 健全性检查：lines_db 中多于 csv_db 的（不该有）
    missing_in_csv = sorted(set(lines_db) - set(csv_db))
    if missing_in_csv:
        print(f"  WARN: lines abbr not in constellations.csv: {missing_in_csv}")

    WESTERN_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    missing_constellations: list[str] = []
    missing_stars: set[str] = set()

    for abbr in sorted(lines_db.keys()):
        csv_row = csv_db.get(abbr)
        if csv_row is None:
            missing_constellations.append(abbr)
            continue

        # 旧 JSON（保留 caption / stories / season / glyph）
        old_path = WESTERN_DIR / f"{abbr}.json"
        old_json: dict | None = None
        if old_path.exists() and old_path.name != "_meta.json":
            try:
                old_json = json.loads(old_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"WARN {abbr}: failed to read old json ({e}), rebuilding from scratch")
                old_json = None

        entry, unmatched = build_one(
            abbr,
            lines_db[abbr],
            stars_db,
            starnames,
            csv_row,
            old_json,
            starnames_cn=starnames_cn,
        )
        if int(unmatched[0]) > 0:
            # 记到 missing_stars（其实只是端点未匹配，不一定是 HIP 缺失；
            # 这里记下 abbr 让 controller 知道哪些有降级）
            missing_stars.add(abbr)

        (WESTERN_DIR / f"{abbr}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1

    print(f"Wrote {written} entries to {WESTERN_DIR}")
    if missing_constellations:
        (ASSETS / "missing_constellations.md").write_text(
            "# Missing abbrs in constellations.csv\n\n"
            + "\n".join(f"- {c}" for c in missing_constellations),
            encoding="utf-8",
        )
        print(f"WARN: {len(missing_constellations)} missing → missing_constellations.md")
    if missing_stars:
        (ASSETS / "missing-stars.md").write_text(
            "# Constellations with unmatched line endpoints\n\n"
            + "端点最近邻 > 0.5° 的星座（line 段已丢弃）。\n\n"
            + "\n".join(f"- {c}" for c in sorted(missing_stars)),
            encoding="utf-8",
        )
        print(f"WARN: {len(missing_stars)} constellations with unmatched endpoints "
              f"→ missing-stars.md")


if __name__ == "__main__":
    main()
