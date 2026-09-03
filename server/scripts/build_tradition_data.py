"""一次性脚本：生成 MVP 5 西方星座 JSON 到 server/data/traditions/western/.

数据源：
- server/data/constellations.json（star 坐标 + 名称 + 亮度 + lines）
- server/data/bayer_index.json（猎户座 RA/Dec）
- 4 个星座中心 RA/Dec + 各星 RA/Dec 用 IAU 公开值（HIP/HD 目录）

MVP 故事只填 brief（myth/science 各一套）；epic/chat 为空占位。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data"
OUT = ROOT / "data" / "traditions" / "western"

# 加载源数据
old = json.loads((SRC / "constellations.json").read_text(encoding="utf-8"))
bayer = json.loads((SRC / "bayer_index.json").read_text(encoding="utf-8"))


def b(star_key):
    """从 bayer_index 取 RA/Dec，缺则空字符串（但 MVP 5 星座都齐全）。"""
    return bayer.get(star_key, {})


def star_entry(key, x, y, name_zh, magnitude, ra, dec, label):
    b = bayer.get(key, {})
    return {
        "x": x, "y": y,
        "bayer": b.get("bayer", ""),
        "name": name_zh,  # 旧 constellations.json 的 name 字段实为中文名（迁移保留）
        "name_zh": name_zh,
        "magnitude": magnitude,
        "ra": ra,
        "dec": dec,
        "label": label,
    }


# === 猎户 ===
ori_stars = {
    "betelgeuse": star_entry("betelgeuse", 144, 62,  "参宿四", 0.42, 88.7929,   7.4071, True),
    "bellatrix":  star_entry("bellatrix",  330, 78,  "参宿五", 1.64, 81.2829,   6.3497, True),
    "meissa":     star_entry("meissa",     282, 28,  "觜宿一", 3.39, 83.7846,   9.9342, False),
    "alnitak":    star_entry("alnitak",    260, 148, "参宿一", 1.74, 85.1896,  -1.9428, True),
    "alnilam":    star_entry("alnilam",    280, 158, "参宿二", 1.69, 84.0533,  -1.2019, True),
    "mintaka":    star_entry("mintaka",    300, 168, "参宿三", 2.23, 83.0017,  -0.2991, True),
    "saiph":      star_entry("saiph",      228, 246, "参宿六", 2.06, 86.9392,  -9.6696, False),
    "rigel":      star_entry("rigel",      334, 238, "参宿七", 0.13, 78.6346,  -8.2017, True),
}
ori = {
    "abbr": "ori",
    "name": "猎户座",
    "latin": "Orion",
    "glyph": "\u2736",
    "season": "冬季",
    "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
    "viewBox": {"width": 500, "height": 300},
    "center": {"ra": 86.0, "dec": -2.0},
    "stars": ori_stars,
    "lines": [
        ["betelgeuse","bellatrix"], ["meissa","betelgeuse"], ["meissa","bellatrix"],
        ["betelgeuse","alnitak"], ["bellatrix","mintaka"], ["mintaka","alnilam"],
        ["alnilam","alnitak"], ["mintaka","rigel"], ["alnitak","saiph"], ["rigel","saiph"],
    ],
    "mansion": None,
    "asterism_id": None,
    "stories": {
        "myth": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "猎户座 · 神话概念", "paragraphs": [
                "猎户座（Orion），全天 88 星座之一，冬季代表星座。位置：赤纬 -10° 到 +20°。",
                "中国星官：参宿（西方白虎）。希腊神话主角：俄里翁（Orion），海神波塞冬之子，猎手。",
                "与天蝎座关系：被天蝎蛰死；二者分两冬夏，永不相见。",
                "象征：猎户、勇士、武士。",
            ]},
        },
        "science": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "猎户座 · 天文参数", "paragraphs": [
                "猎户座（Orion）。赤经 5h35m，赤纬 -5°23′。面积 594 平方度。",
                "主星：参宿四（α Ori，Betelgeuse，红超巨星）、参宿七（β Ori，Rigel，蓝超巨星）、参宿五（γ Ori，Bellatrix）、参宿一（ζ Ori）、参宿二（ε Ori）、参宿三（δ Ori）。",
                "深空天体：M42 猎户大星云（距 1344 光年）、M43、M78、马头星云（IC 434）。",
                "最佳观测月份：12 月 - 3 月。",
            ]},
        },
    },
}

# === 天鹅 ===
cyg_stars = {
    "deneb":   {"x": 320, "y": 40,  "bayer": "Alpha Cyg",   "name": "天津四", "name_zh": "天津四", "magnitude": 1.25, "ra": 310.36, "dec": 45.28, "label": True},
    "sadr":    {"x": 320, "y": 180, "bayer": "Gamma Cyg",   "name": "天津一", "name_zh": "天津一", "magnitude": 2.23, "ra": 305.55, "dec": 40.26, "label": True},
    "gienah":  {"x": 180, "y": 140, "bayer": "Epsilon Cyg", "name": "天津九", "name_zh": "天津九", "magnitude": 2.48, "ra": 311.55, "dec": 33.97, "label": False},
    "delta":   {"x": 460, "y": 140, "bayer": "Delta Cyg",   "name": "天津二", "name_zh": "天津二", "magnitude": 2.87, "ra": 296.24, "dec": 45.13, "label": False},
    "albireo": {"x": 320, "y": 340, "bayer": "Beta Cyg",    "name": "辇道增七", "name_zh": "辇道增七", "magnitude": 3.05, "ra": 292.68, "dec": 27.96, "label": True},
}
cyg = {
    "abbr": "cyg",
    "name": "天鹅座",
    "latin": "Cygnus",
    "glyph": "\u269d",
    "season": "夏季",
    "caption": "银河中振翅的天鹅。十字展开，颈指南天。",
    "viewBox": {"width": 500, "height": 400},
    "center": {"ra": 312.0, "dec": 42.0},
    "stars": cyg_stars,
    "lines": [
        ["deneb", "sadr"], ["sadr", "gienah"], ["sadr", "delta"], ["sadr", "albireo"],
    ],
    "mansion": None,
    "asterism_id": None,
    "stories": {
        "myth": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "天鹅座 · 神话概念", "paragraphs": [
                "天鹅座（Cygnus），全天 88 星座之一，夏夜代表星座。位置：赤纬 +27° 到 +61°，跨银道。",
                "中国星官：天津（北方玄武）。希腊神话：宙斯化天鹅接近勒达；亦说为俄耳甫斯的琴。",
                "主星连线成十字，亦称『北十字』，与南十字相对。",
                "象征：天鹅、仙鸟、北十字。",
            ]},
        },
        "science": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "天鹅座 · 天文参数", "paragraphs": [
                "天鹅座（Cygnus）。赤经 20h38m，赤纬 +42°01′。面积 804 平方度。",
                "主星：天津四（α Cyg，Deneb，蓝白超巨星）、天津一（γ Cyg，Sadr）、辇道增七（β Cyg，Albireo，著名双星）。",
                "深空天体：NGC 7000 北美洲星云、IC 5070 鹈鹕星云、面纱星云。",
                "最佳观测月份：7 月 - 10 月。",
            ]},
        },
    },
}

# === 天蝎 ===
sco_stars = {
    "graffias":  {"x": 240, "y": 140, "bayer": "Beta Sco",   "name": "房宿四",   "name_zh": "房宿四",   "magnitude": 2.62, "ra": 241.36, "dec": -19.81, "label": False},
    "dschubba":  {"x": 280, "y": 150, "bayer": "Delta Sco",  "name": "房宿三",   "name_zh": "房宿三",   "magnitude": 2.32, "ra": 240.08, "dec": -22.62, "label": True},
    "antares":   {"x": 320, "y": 210, "bayer": "Alpha Sco",  "name": "心宿二",   "name_zh": "心宿二",   "magnitude": 1.06, "ra": 247.35, "dec": -26.43, "label": True},
    "zeta":      {"x": 360, "y": 290, "bayer": "Zeta Sco",   "name": "尾宿一",   "name_zh": "尾宿一",   "magnitude": 3.62, "ra": 253.69, "dec": -42.36, "label": False},
    "shaula":    {"x": 380, "y": 360, "bayer": "Lambda Sco", "name": "尾宿八",   "name_zh": "尾宿八",   "magnitude": 1.62, "ra": 263.40, "dec": -37.10, "label": True},
    "sargas":    {"x": 400, "y": 380, "bayer": "Theta Sco",  "name": "尾宿五",   "name_zh": "尾宿五",   "magnitude": 1.86, "ra": 264.33, "dec": -42.99, "label": False},
}
sco = {
    "abbr": "sco",
    "name": "天蝎座",
    "latin": "Scorpius",
    "glyph": "\u264f",
    "season": "夏季",
    "caption": "南天巨蝎。心宿二是古观『大火』, 农人定季的星。",
    "viewBox": {"width": 500, "height": 400},
    "center": {"ra": 247.0, "dec": -26.0},
    "stars": sco_stars,
    "lines": [
        ["graffias", "dschubba"], ["dschubba", "antares"], ["antares", "zeta"],
        ["zeta", "shaula"], ["shaula", "sargas"],
    ],
    "mansion": None,
    "asterism_id": None,
    "stories": {
        "myth": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "天蝎座 · 神话概念", "paragraphs": [
                "天蝎座（Scorpius），全天 88 星座之一，黄道星座，夏夜代表。位置：赤纬 -8° 到 -46°。",
                "中国星官：房宿、心宿、尾宿（东方苍龙）。希腊神话：被赫拉克勒斯（武仙座）所杀；天后赫拉升天为蝎。",
                "心宿二（Antares）古称『大火』，农人定季节用：仲夏黄昏见于正南，即『七月流火』。",
                "象征：蝎、毒刺、战神。",
            ]},
        },
        "science": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "天蝎座 · 天文参数", "paragraphs": [
                "天蝎座（Scorpius）。赤经 16h53m，赤纬 -26°。面积 497 平方度。",
                "主星：心宿二（α Sco，Antares，红超巨星，『火星的敌手』）、尾宿八（λ Sco，Shaula）、房宿三（δ Sco，Dschubba）。",
                "深空天体：M4（球状星团）、M6 蝴蝶星团、M7 托勒密星团。",
                "最佳观测月份：6 月 - 8 月。",
            ]},
        },
    },
}

# === 狮子 ===
leo_stars = {
    "rasalas":   {"x": 460, "y": 180, "bayer": "Epsilon Leo", "name": "轩辕九",       "name_zh": "轩辕九",   "magnitude": 2.97, "ra": 146.46, "dec": 23.77, "label": False},
    "algieba":   {"x": 460, "y": 130, "bayer": "Gamma Leo",   "name": "轩辕十二",     "name_zh": "轩辕十二", "magnitude": 2.61, "ra": 154.99, "dec": 19.84, "label": False},
    "regulus":   {"x": 480, "y": 80,  "bayer": "Alpha Leo",   "name": "轩辕十四",     "name_zh": "轩辕十四", "magnitude": 1.36, "ra": 152.09, "dec": 11.97, "label": True},
    "zosma":     {"x": 430, "y": 260, "bayer": "Delta Leo",   "name": "太微右垣五",   "name_zh": "太微右垣五", "magnitude": 2.56, "ra": 168.53, "dec": 20.52, "label": False},
    "chertan":   {"x": 440, "y": 300, "bayer": "Theta Leo",   "name": "西次相",       "name_zh": "西次相",   "magnitude": 3.34, "ra": 168.56, "dec": 15.43, "label": False},
    "denebola":  {"x": 520, "y": 360, "bayer": "Beta Leo",    "name": "五帝座一",     "name_zh": "五帝座一", "magnitude": 2.14, "ra": 177.27, "dec": 14.57, "label": True},
}
leo = {
    "abbr": "leo",
    "name": "狮子座",
    "latin": "Leo",
    "glyph": "\u264c",
    "season": "春季",
    "caption": "春夜兽王。镰刀当胸, 五帝座一为尾。",
    "viewBox": {"width": 600, "height": 400},
    "center": {"ra": 162.0, "dec": 17.0},
    "stars": leo_stars,
    "lines": [
        ["regulus", "algieba"], ["algieba", "rasalas"], ["regulus", "zosma"],
        ["zosma", "chertan"], ["chertan", "denebola"],
    ],
    "mansion": None,
    "asterism_id": None,
    "stories": {
        "myth": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "狮子座 · 神话概念", "paragraphs": [
                "狮子座（Leo），全天 88 星座之一，黄道星座，春夜代表。位置：赤纬 -6° 到 +33°。",
                "中国星官：轩辕、太微右垣、五帝座。希腊神话：尼米亚巨狮，刀枪不入，被赫拉克勒斯扼死。",
                "主星连线像反写的问号（镰刀），轩辕十四（Regulus）为其底。",
                "象征：狮子、王者、兽王。",
            ]},
        },
        "science": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "狮子座 · 天文参数", "paragraphs": [
                "狮子座（Leo）。赤经 10h40m，赤纬 +16°。面积 947 平方度。",
                "主星：轩辕十四（α Leo，Regulus，蓝白主序星）、五帝座一（β Leo，Denebola）、轩辕十二（γ Leo，Algieba，著名双星）。",
                "深空天体：M65、M66、 NGC 3623（狮子三重星系）。",
                "最佳观测月份：3 月 - 5 月。",
            ]},
        },
    },
}

# === 仙女 ===
and_stars = {
    "alpheratz": {"x": 140, "y": 100, "bayer": "Alpha And", "name": "壁宿二",   "name_zh": "壁宿二",   "magnitude": 2.06, "ra":   2.10, "dec": 29.09, "label": True},
    "delta":     {"x": 240, "y": 160, "bayer": "Delta And", "name": "奎宿五",   "name_zh": "奎宿五",   "magnitude": 3.27, "ra":   9.83, "dec": 30.86, "label": False},
    "mirach":    {"x": 320, "y": 220, "bayer": "Beta And",  "name": "奎宿九",   "name_zh": "奎宿九",   "magnitude": 2.06, "ra":  17.43, "dec": 35.62, "label": True},
    "almach":    {"x": 440, "y": 300, "bayer": "Gamma And", "name": "天大将军一", "name_zh": "天大将军一", "magnitude": 2.10, "ra":  30.97, "dec": 42.33, "label": False},
}
and_ = {
    "abbr": "and",
    "name": "仙女座",
    "latin": "Andromeda",
    "glyph": "\u2640",
    "season": "秋季",
    "caption": "秋夜仙女。身旁悬着肉眼可见的仙女星系。",
    "viewBox": {"width": 500, "height": 400},
    "center": {"ra": 12.0, "dec": 38.0},
    "stars": and_stars,
    "lines": [
        ["alpheratz", "delta"], ["delta", "mirach"], ["mirach", "almach"],
    ],
    "mansion": None,
    "asterism_id": None,
    "stories": {
        "myth": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "仙女座 · 神话概念", "paragraphs": [
                "仙女座（Andromeda），全天 88 星座之一，秋夜代表。位置：赤纬 +21° 到 +53°。",
                "中国星官：壁宿、奎宿、天大将军。希腊神话：埃塞俄比亚公主，被献祭给海怪，被珀尔修斯（英仙座）所救。",
                "主星连线：从壁宿二（α And，Alpheratz）经奎宿五、奎宿九（Mirach）至天大将军一（Almach）。",
                "象征：仙女、公主、铁链。",
            ]},
        },
        "science": {
            "epic":  {"title": "尚未撰写", "paragraphs": []},
            "chat":  {"title": "尚未撰写", "paragraphs": []},
            "brief": {"title": "仙女座 · 天文参数", "paragraphs": [
                "仙女座（Andromeda）。赤经 0h48m，赤纬 +37°。面积 722 平方度。",
                "主星：壁宿二（α And，Alpheratz，双星）、奎宿九（β And，Mirach，红巨星）、天大将军一（γ And，Almach，著名双星）。",
                "深空天体：M31 仙女星系（距 254 万光年，肉眼可见）、M32、M110。",
                "最佳观测月份：9 月 - 11 月。",
            ]},
        },
    },
}


def write_entry(entry):
    abbr = entry["abbr"]
    path = OUT / f"{abbr}.json"
    path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK {abbr} -> {path}")


for e in (ori, cyg, sco, leo, and_):
    write_entry(e)

# 验证：abbr 与 filename 一致
print("\n=== 自检 ===")
for p in sorted(OUT.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["abbr"] == p.stem, f"{p}: abbr != filename"
    assert "ra" in d["center"] and "dec" in d["center"]
    for sk, s in d["stars"].items():
        assert "ra" in s and "dec" in s and "magnitude" in s and "label" in s
        assert isinstance(s["label"], bool)
    for line in d["lines"]:
        assert len(line) == 2 and line[0] in d["stars"] and line[1] in d["stars"]
    for view in ("myth", "science"):
        for narr in ("epic", "chat", "brief"):
            assert "title" in d["stories"][view][narr]
    print(f"OK {p.name}")
print("\n5 个 western JSON 生成 + 自检完成")
