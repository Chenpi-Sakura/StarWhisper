"""生成西方 88 星座 JSON。跳过已存在的 MVP 5 座（保留手绘 x/y）。"""
import csv
import json
from pathlib import Path

from scripts.atlas_data.coords import main_name, normalize_ra, ra_wrap

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
                dra = ra_wrap(s["ra"] - lon)
                ddec = s["dec"] - lat
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
            # 折线 N 个端点 → N-1 条边（每边恰好 2 元素，匹配 validate_atlas 约束）
            for i in range(len(seg) - 1):
                entry_lines.append([seg[i], seg[i + 1]])
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


if __name__ == "__main__":
    main()