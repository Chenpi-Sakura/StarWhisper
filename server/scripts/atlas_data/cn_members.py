"""星官成员归组 + 连线端点回填。依赖 coords 纯函数。"""
import csv
from scripts.atlas_data.coords import (
    asterism_key, haversine_deg, normalize_ra, strip_suffix,
)

# 成员星名与星官名无任何前缀/后缀关系的「独立古名」星官（启发式失效）。
# 用 HIP 号精确指定成员，避免中文名歧义（如「太子」「帝」在多个星官重复）。
EXPLICIT_MEMBERS: dict[str, list[str]] = {
    "北斗": ["54061", "53910", "58001", "59774", "62956", "65378", "67301"],
    "北极": ["75097", "72607", "70692", "69112", "11767", "62572"],
    "三台": ["44127", "44471", "50372", "50801", "55219", "55203"],
    "十二国": [
        "103226", "103616", "104019", "104139", "104365", "104429",
        "104963", "105143", "105515", "105665", "105881", "105928", "106039",
    ],
}


def group_members(constellations_path, starnames_path):
    """按星官归组 starnames.cn 单星名。

    返回 {归组 key: [{id(HIP), name, desig}, ...]}。归组 key 见 coords.asterism_key：
    - 主名 + @归属 区分同名星官（杵@箕宿 vs 杵@危宿）
    - 「附官」等纯说明标记不入 key（伐(附官)→伐）
    - 显式映射（独立古名型）优先用 HIP 精确定位
    """
    asterisms = set()
    with open(constellations_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            asterisms.add(asterism_key(row["name"]))

    groups = {}
    with open(starnames_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            asterism = asterism_key(row["name"])
            if asterism not in asterisms:
                continue
            groups.setdefault(asterism, []).append(
                {"id": row["id"], "name": row["name"], "desig": row["desig"]}
            )

    # 显式映射：成员名与星官名无关，按 HIP 反查注入
    by_id = {}
    with open(starnames_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_id[row["id"]] = {
                "id": row["id"], "name": row["name"], "desig": row["desig"],
            }
    for asterism, hips in EXPLICIT_MEMBERS.items():
        members = [by_id[h] for h in hips if h in by_id]
        if members:
            groups[asterism] = members

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