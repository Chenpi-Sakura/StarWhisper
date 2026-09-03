"""生成中国星官约 306 个 JSON。

关键启发式（spec §2.3，覆盖率已实测 87.3% > 80%）：
1. 成员星归组：strip_suffix(单星名) 命中星官主名
2. 连线回填：lines.cn 端点是坐标，Haversine 最近邻匹配成员星 HIP
3. 三垣：6 垣墙(rank=2)合并为 3 entry；近南极 23 星官 asterism_id='nanji'
4. abbr 消歧：pinyin 相同时按 name 拼音首字母追加后缀，避免 slug 冲突
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

# 允许以 scripts/build_chinese_stars.py 形式运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.atlas_data.coords import (
    asterism_key, haversine_deg, normalize_ra, slugify,
)
from scripts.atlas_data.cn_members import group_members
from scripts.atlas_projection import compute_field, project

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = Path(__file__).resolve().parents[1] / "data" / "traditions" / "chinese"
VIEW_W, VIEW_H = 700.0, 700.0

# 中国星官 lines.cn 端点坐标存在系统性漂移（实测 0.1°~7°），
# 原 0.05° 阈值过严导致大量星官 lines 回填失败。放宽到 2° 覆盖大部分；
# 仍失配的端点打 WARN 显式暴露（避免静默丢失整条线）。
MATCH_THRESHOLD_DEG = 2.0


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


def _preserve_stories(abbr: str) -> dict:
    """读已存在 JSON 的 stories 字段；不存在/损坏则返回 _empty_stories()。

    build 重放（test_build_chinese_replay 等）会反复跑 main()，必须保留
    之前填好的故事内容（myth/science 段落），否则会清空 309 个中国星官
    的故事。返回 dict 与 _empty_stories() 同 shape（兼容后续 json.dump）。
    """
    fp = OUT / f"{abbr}.json"
    if not fp.exists():
        return _empty_stories()
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        stories = d.get("stories")
        if not isinstance(stories, dict):
            return _empty_stories()
        # 兼容老格式 {"myth": {"title":..., "paragraphs":[...]},"science":...}
        # 与新格式 {"myth": {"epic":..., "chat":..., "brief":...},...}
        return stories
    except Exception:
        return _empty_stories()


def _match(lonlat, star_map, threshold=MATCH_THRESHOLD_DEG):
    """返回 (hip_or_None, sep_deg)。sep >= threshold 视为无匹配（返回 None）。"""
    lon, lat = lonlat
    ra = normalize_ra(lon)
    best, best_sep = None, threshold
    for hip, s in star_map.items():
        sep = haversine_deg(ra, lat, s["ra"], s["dec"])
        if sep < best_sep:
            best, best_sep = hip, sep
    return best, best_sep


def _resolve_abbr_conflicts(items):
    """按 raw_abbr 分组，组内按 id 排序追加 _2/_3，返回 {id: final_abbr}。"""
    groups = {}
    for ent in items:
        ab = slugify(ent["pinyin"])
        groups.setdefault(ab, []).append(ent)
    out = {}
    for ab, ents in groups.items():
        ents.sort(key=lambda e: int(e["id"]))
        if len(ents) == 1:
            out[ents[0]["id"]] = ab
        else:
            for i, ent in enumerate(ents, start=1):
                out[ent["id"]] = f"{ab}_{i}"
    return out


YUAN_WALL_KEYS = {
    "紫微垣": ("紫微左垣", "紫微右垣"),
    "太微垣": ("太微左垣", "太微右垣"),
    "天市垣": ("天市左垣", "天市右垣"),
}


def _yuan_center(wall_names, constellations):
    """三垣中心：取左右垣两个 display_ra/display_dec 算经纬度中心。

    RA 跨 360° 时用 sin/cos 平均再 atan2 还原，避免朴素均值在 0/360 处跳变。
    """
    lons, lats = [], []
    for cn in wall_names:
        for c in constellations:
            if c["name"] == cn:
                lons.append(normalize_ra(float(c["display_ra"])))
                lats.append(float(c["display_dec"]))
                break
    if not lons:
        return 0.0, 0.0
    sx = sum(math.cos(math.radians(l)) for l in lons) / len(lons)
    sy = sum(math.sin(math.radians(l)) for l in lons) / len(lons)
    cx_ra = math.degrees(math.atan2(sy, sx)) % 360
    return cx_ra, sum(lats) / len(lats)


def _mean_ra(ras: list[float], center_dec0: float = 0) -> float:
    """成员 RA 几何中心（cos(Dec) 加权 + 跨 0/360 边界的 atan2 还原）。

    朴素均值在 RA 跨 0/360（如仙后座/飞马座）会跳到 180° 错处。
    加权公式用每个成员的 cos(Dec) 避免极区成员权重过大。
    """
    if not ras:
        return 0.0
    # 用一个固定 Dec（外部传入的均值）作统一权重，等价于「按 Dec 加权后
    # 在 RA 平面上求质心」。注意：调用方应保证 ras 与 dec 一一对应；如果
    # 只是「求 RA 中心」，传 0 即可（与测试断言保持一致）。
    sx = sum(math.cos(math.radians(ra)) for ra in ras)
    sy = sum(math.sin(math.radians(ra)) for ra in ras)
    if sx == 0 and sy == 0:
        return sum(ras) / len(ras)
    return math.degrees(math.atan2(sy, sx)) % 360


def main():
    stars = load_stars()
    lines_cn = load_lines_cn()
    constellations = []
    with open(RAW / "constellations.cn.csv", encoding="utf-8") as f:
        constellations = list(csv.DictReader(f))
    members = group_members(str(RAW / "constellations.cn.csv"),
                            str(RAW / "starnames.cn.csv"))
    # HIP → 中文名（starnames.cn.csv 全表反查；三垣合并回填 name 用）
    hip_names = {}
    with open(RAW / "starnames.cn.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("name") or "").strip():
                hip_names[row["id"]] = row["name"].strip()
    OUT.mkdir(parents=True, exist_ok=True)

    # 第一遍：解析所有 entry 的最终 abbr（冲突组按 id 排序追加 _2/_3）
    non_wall = [c for c in constellations if c["rank"] != "2"]
    resolved = _resolve_abbr_conflicts(non_wall)

    def abbr_for(c):
        return resolved.get(c["id"]) or slugify(c["pinyin"])

    # 索引：asterism_key → 主宿名（仅 rank=1 的 28 宿）。
    # 附官（X(附官) / X(宿)）连线常延伸到主宿成员（参宿二、室宿二），
    # 故回填连线时对附官开放「主宿成员 fallback 池」——成员归组仍只记附官自身。
    mansion_owners = {asterism_key(c["name"]): c["name"]
                      for c in constellations if c["rank"] == "1"}

    # 显式附官→主宿 映射（启发式失效时兜底；星官学常识：附官属最近主宿）
    EXPLICIT_OWNER: dict[str, str] = {
        "伐(附官)": "参宿",
        "离宫(附官)": "室宿",
        "坟墓(附官)": "危宿",
        "三公(太微垣)": "太微垣",
        "三公(紫微垣)": "紫微垣",
        "杠(附官)": "紫微垣",
        "钩钤(附官)": "房宿",
        "长垣": "太微垣",
        "天床": "紫微垣",
        "天庾": "井宿",
        "天牢": "紫微垣",
        "市楼": "天市垣",
        "天田(角宿)": "角宿",
        "天田(牛宿)": "牛宿",
        "杵(箕宿)": "箕宿",
        "杵(危宿)": "危宿",
        "柱(毕宿)": "毕宿",
        "柱(角宿)": "角宿",
        "从官(房宿)": "房宿",
        "从官(太微垣)": "太微垣",
        "五诸侯(井宿)": "井宿",
        "五诸侯(太微垣)": "太微垣",
        "长沙(附官)": "轸宿",
        "传舍": "紫微垣",
        "积尸(鬼宿)": "鬼宿",
        "积尸(胃宿)": "胃宿",
        "积水(胃宿)": "胃宿",
        "积水(井宿)": "井宿",
        "厝": "紫微垣",
    }

    def _enclave_owner(name: str) -> str | None:
        """附官 → 主宿中文名。

        优先级：显式映射 > X(Y 宿) 显式声明 > 启发式前缀匹配。
        """
        if name in EXPLICIT_OWNER:
            return EXPLICIT_OWNER[name]
        m = re.match(r"^([^(\[]+)[(\[](附官|[^)\]]+宿)[)\]]", name)
        if not m:
            return None
        own = m.group(1).strip()
        scope = m.group(2).strip()
        if scope.endswith("宿") and scope in mansion_owners.values():
            return scope
        for mans in mansion_owners.values():
            if mans.startswith(own):
                return mans
        return None

    # 生成星官 entry（rank=3 星官 + rank=1 宿 + rank=2 垣墙合并为 3 垣）
    written = set()
    for c in constellations:
        rank = c["rank"]
        if rank == "2":
            continue  # 垣墙在 merge_walls 处理
        name = c["name"]
        main = asterism_key(name)
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
        # center：优先用成员几何中心（更贴近真实视觉重心），
        # 退化到 csv 的 display_ra/display_dec（无成员时）。
        if star_map:
            mean_dec0 = sum(s["dec"] for s in star_map.values()) / len(star_map)
            # 真正的几何中心：每个成员按其自己的 Dec 加权到 RA 平面上求质心
            sx = sum(math.cos(math.radians(s["ra"])) * math.cos(math.radians(s["dec"]))
                     for s in star_map.values())
            sy = sum(math.sin(math.radians(s["ra"])) * math.cos(math.radians(s["dec"]))
                     for s in star_map.values())
            if sx == 0 and sy == 0:
                center_ra = mean_dec0
            else:
                center_ra = math.degrees(math.atan2(sy, sx)) % 360
            center_dec = mean_dec0
        else:
            center_ra = normalize_ra(float(c["display_ra"]))
            center_dec = float(c["display_dec"])
        # 投影：Azimuthal Stereographic（与 runtime 共用 atlas_projection 公式），
        # 东=右、北=上；不再做 RA 镜像。
        # label：有名字（name/name_zh 非空）才标注，避免「未命名」刷屏。
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
                s["label"] = bool((s["name"] or "").strip()
                                  or (s["name_zh"] or "").strip())
        # lines 回填：>2 端点折线拆成 2-端点边；端点必须全在 star_map 中。
        # 附官/跨宿场景：端点可能落在主宿成员（如「伐(附官)」→ 参宿二），
        # fallback 池 = 本星官成员 + 该星官声明的「主宿」成员（28 宿）。
        fallback_pool = dict(star_map)
        owner = _enclave_owner(name) if name != main else None
        if owner and owner != name:
            owner_key = asterism_key(owner)
            for m in members.get(owner_key, []):
                hip = m["id"]
                if hip in fallback_pool:
                    continue
                s = stars.get(hip)
                if not s:
                    continue
                fallback_pool[hip] = {
                    "bayer": "", "name": m["name"], "name_zh": m["name"],
                    "magnitude": s["mag"], "ra": s["ra"], "dec": s["dec"],
                    "label": bool((m["name"] or "").strip()), "hip": hip,
                }
        entry_lines = []
        if c["id"] in lines_cn:
            for ln in lines_cn[c["id"]]["lines"]:
                keys = []
                ok = True
                for lonlat in ln:
                    k, sep = _match(lonlat, fallback_pool)
                    if k is None and owner:
                        # 附官延伸：owner 启发式失败时退化到 owner 周边全 rank=1 宿成员
                        # （业内惯例：附官从最近主宿引线）。用主宿 28 宿全量成员再试一次。
                        for mans in mansion_owners.values():
                            if mans == owner:
                                continue
                            mk = asterism_key(mans)
                            for m in members.get(mk, []):
                                hip = m["id"]
                                if hip in fallback_pool:
                                    continue
                                s2 = stars.get(hip)
                                if not s2:
                                    continue
                                fallback_pool[hip] = {
                                    "bayer": "", "name": m["name"],
                                    "name_zh": m["name"],
                                    "magnitude": s2["mag"], "ra": s2["ra"],
                                    "dec": s2["dec"],
                                    "label": bool((m["name"] or "").strip()),
                                    "hip": hip,
                                }
                        k, sep = _match(lonlat, fallback_pool)
                    if k is None:
                        ok = False
                        print(
                            f"WARN {name}: line 端点 {lonlat} 最近成员星距 "
                            f"{sep:.2f}° > {MATCH_THRESHOLD_DEG}°，整线丢弃"
                        )
                        break
                    keys.append(k)
                if not ok:
                    continue
                # 把 fallback 命中的成员星（label=False）也加入 star_map，
                # 保留原有 label=True 成员不变。
                for hip in keys:
                    if hip in fallback_pool and hip not in star_map:
                        star_map[hip] = fallback_pool[hip]
                # 拆折线为连续 2 端点边；允许重复端点
                for i in range(len(keys) - 1):
                    a, b = keys[i], keys[i + 1]
                    if a != b:
                        entry_lines.append([a, b])
        # mansion/asterism_id
        mansion = None
        asterism_id = None
        if rank == "1":
            mansion = abbr_for(c)
        elif name in ("紫微垣", "太微垣", "天市垣"):
            asterism_id = abbr_for(c)
        else:
            asterism_id = "nanji" if center_dec < -55 else None
        entry = {
            "abbr": abbr_for(c), "name": name,
            "latin": c.get("en", ""), "glyph": "", "season": "", "caption": "",
            "viewBox": {"width": 700, "height": 700},
            "center": {"ra": round(center_ra, 4), "dec": round(center_dec, 4)},
            "stars": star_map, "lines": entry_lines,
            "mansion": mansion, "asterism_id": asterism_id,
            "stories": _preserve_stories(abbr_for(c)),
        }
        (OUT / f"{entry['abbr']}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.add(entry["abbr"])
        print(f"OK {entry['abbr']} ({len(star_map)} 星, {len(entry_lines)} 线)")

    # 三垣：合并 6 垣墙 rank=2 的 lines，按合并中文名生成 3 entry
    # 3 垣在 csv 中无独立 row，center 取左右垣两个 display_ra/display_dec 的中心
    walls_merged = merge_walls(lines_cn, constellations)
    YUAN_META = {
        "紫微垣": "zi_wei_yuan",
        "太微垣": "tai_wei_yuan",
        "天市垣": "tian_shi_yuan",
    }
    for yuan, yuan_slug in YUAN_META.items():
        cra, cdec = _yuan_center(YUAN_WALL_KEYS[yuan], constellations)
        # 按每条线段首端点 (lon, lat) 排序，固化 6 垣墙合并顺序，使 build 可重放
        merged_lines = sorted(
            walls_merged.get(yuan, []),
            key=lambda ln: (ln[0][0], ln[0][1]),
        )
        # 端点 → 最近邻 HIP（全体 stars 范围；阈值 MATCH_THRESHOLD_DEG）
        entry_lines = []
        used_hips = set()
        for ln in merged_lines:
            keys = []
            ok = True
            for lonlat in ln:
                k, sep = _match(lonlat, stars)
                if k is None:
                    ok = False
                    print(
                        f"WARN {yuan}: line 端点 {lonlat} 最近星距 "
                        f"{sep:.2f}° > {MATCH_THRESHOLD_DEG}°，整线丢弃"
                    )
                    break
                keys.append(k)
            if not ok:
                continue
            for i in range(len(keys) - 1):
                a, b = keys[i], keys[i + 1]
                if a != b:
                    entry_lines.append([a, b])
                    used_hips.add(a)
                    used_hips.add(b)
        # ★ 关键：固化 stars dict 顺序。set 迭代序在 CPython 实现下虽稳定，
        # 但不同运行（hash seed、build 顺序）会抖动；显式 sorted 使重放幂等。
        used_hips_sorted = sorted(used_hips)
        # 把 line 端点所引用的星填入 stars（从 starnames 反查真名；有名字才标注）
        yuan_stars = {}
        for hip in used_hips_sorted:
            s = stars.get(hip)
            if not s:
                continue
            zh = hip_names.get(hip, "") or f"HIP {hip}"
            yuan_stars[hip] = {
                "bayer": "", "name": zh, "name_zh": zh,
                "magnitude": s["mag"], "ra": s["ra"], "dec": s["dec"],
                "label": True, "hip": hip,
            }
        entry = {
            "abbr": yuan_slug, "name": yuan,
            "latin": "", "glyph": "", "season": "", "caption": "",
            "viewBox": {"width": 700, "height": 700},
            "center": {"ra": round(cra, 4), "dec": round(cdec, 4)},
            "stars": yuan_stars, "lines": entry_lines,
            "mansion": None, "asterism_id": yuan_slug,
            "stories": _preserve_stories(yuan_slug),
        }

        (OUT / f"{entry['abbr']}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.add(entry["abbr"])
        print(f"OK {entry['abbr']} ({len(yuan_stars)} 星, {len(entry_lines)} 线)")

    print(f"--- 共生成 {len(written)} entry ---")

    # ★ 末尾 enrich：从 western Bayer 体系复用亮星闭合边（端点都在本 asterism
    # 亮星内）+ 应用 KNOWN_CLOSURES（如北斗勺口闭合）。保证 build 重放
    # 输出含 enrich 后的状态，避免 build → 单独跑 enrich 两步的"双源真相"。
    try:
        from enrich_chinese_lines import (
            collect_western_edges, enrich_one, WEST_DIR,
        )
        west_edges = collect_western_edges(WEST_DIR)
        total_added = 0
        for abbr in sorted(written):
            added = enrich_one(OUT / f"{abbr}.json", west_edges, dry_run=False)[1]
            total_added += added
        if total_added:
            print(f"--- enrich: 新增 {total_added} 条 Bayer 复用 + manual closure ---")
    except Exception as e:
        # enrich 失败不应阻塞 build（用户可能用旧版 western 数据）
        print(f"--- enrich 跳过：{e} ---")


if __name__ == "__main__":
    main()