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
    """去掉序号/增星后缀，返回归属星官名。参宿四→参宿；参宿增卅八→参宿；天庾一*→天庾。"""
    n = re.sub(r"\[.*", "", name)
    n = re.sub(r"[*★]+$", "", n)
    n = re.sub(r"增[一二三四五六七八九十百廿卅0-9]+$", "", n)
    n = re.sub(r"[一二三四五六七八九十百廿卅0-9]+$", "", n)
    return n.strip()


def split_constellation_name(name: str) -> tuple[str, str]:
    """拆星官/成员名为 (主名, 归属)。

    柱(毕宿)→(柱,毕宿)；柱一[毕宿]→(柱一,毕宿)；
    伐(附官)→(伐,附官)；伐一→(伐一,"")。
    """
    m = re.match(r"^([^\[(]+?)(?:[\[(]([^\])]+)[\])])?$", name)
    if not m:
        return (name.strip(), "")
    main = m.group(1).strip()
    scope = (m.group(2) or "").strip()
    return (main, scope)


def asterism_key(name: str) -> str:
    """星官归组 key：主名去序号 + 归属区分。

    柱(毕宿)→柱@毕宿；柱一[毕宿]→柱@毕宿；伐(附官)→伐；
    参宿四→参宿；天枢→天枢。

    「附官」标记不入 key（成员名不带该标注）；真正的宿/垣归属用 @ 区分同名星官
    （杵(箕宿) vs 杵(危宿) → 杵@箕宿 vs 杵@危宿）。
    """
    main, scope = split_constellation_name(name)
    main = strip_suffix(main)
    if scope and scope != "附官":
        return f"{main}@{scope}"
    return main


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