"""观星指数聚合（纯函数，无 FastAPI 依赖，便于单测）。

算法对齐 docs/PROJECT_BRIEF.md §5：

    Score = 云量 40% + 降水 20% + 风/温度 10% + 月相 20% + 光污染 10%

一票否决（spec 2026-08-21 §18）：云量>80 或 降水>50 → score = min(score, 40)
输出四档：优(≥80) / 良(60-79) / 一般(40-59) / 差(<40)。
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path

from astral import moon

_CITIES_PATH = Path(__file__).parent.parent / "data" / "bortle_cities.json"
_cities: list[dict] | None = None


# ---- Bortle 光污染 ----


def bortle_coeff(bortle: int) -> float:
    """Bortle I~IX → 0.05~1.0 系数（I 最暗=1.0，IX 最亮≈0.05）。"""
    b = max(1, min(9, int(bortle)))
    return max(0.05, 1.0 - (b - 1) * 0.11875)


_BORTLE_LABELS = {
    1: "极暗夜空",
    2: "典型暗空",
    3: "乡村暗空",
    4: "乡村郊区过渡",
    5: "郊区",
    6: "明亮郊区",
    7: "郊区城市过渡",
    8: "城市",
    9: "市中心",
}


def bortle_label(bortle: int) -> str:
    return _BORTLE_LABELS.get(max(1, min(9, int(bortle))), "未知")


# ---- 月相 ----


def _moon_label(phase: float) -> str:
    if phase < 1.8 or phase >= 26.2:
        return "新月"
    if phase < 5.4:
        return "蛾眉月"
    if phase < 8.6:
        return "上弦月"
    if phase < 12.2:
        return "盈凸月"
    if phase < 15.8:
        return "满月"
    if phase < 19.4:
        return "亏凸月"
    if phase < 22.6:
        return "下弦月"
    return "残月"


def moon_illumination(phase: float) -> float:
    """月照度折算：0=新月（最佳），1=满月（最差）。"""
    return (1.0 - math.cos(2.0 * math.pi * phase / 28.0)) / 2.0


def moon_info(d: date) -> dict:
    phase = float(moon.phase(d))
    return {
        "phase": round(phase, 2),
        "illumination": round(moon_illumination(phase), 3),
        "label": _moon_label(phase),
    }


def build_daily_moon(start_date: date, days: int = 7) -> list[dict]:
    """生成未来 N 天的每日月相（与 moon_info(d) 同形态）。"""
    return [moon_info(start_date + timedelta(days=i)) for i in range(days)]


# ---- 子项评分 ----


def _cloud_sub(cloud: float) -> float:
    return max(0.0, 100.0 - cloud)


def _precip_sub(precip: float) -> float:
    return max(0.0, 100.0 - precip)


def _windtemp_sub(wind: float, temp: float) -> float:
    wind_sub = max(0.0, 100.0 - wind * 2.5)
    temp_sub = max(0.0, 100.0 - abs(temp - 15.0) * 3.0)
    return (wind_sub + temp_sub) / 2.0


def _moon_sub(illumination: float) -> float:
    return (1.0 - illumination) * 100.0


def _bortle_sub(bortle: int) -> float:
    return bortle_coeff(bortle) * 100.0


def compute_components(
    cloud: float,
    precip: float,
    wind: float,
    temp: float,
    illumination: float,
    bortle: int,
) -> dict:
    """返回五个子项子分（0-100），供前端仪表逐项展示。"""
    return {
        "cloud": round(_cloud_sub(cloud), 1),
        "precip": round(_precip_sub(precip), 1),
        "windtemp": round(_windtemp_sub(wind, temp), 1),
        "moon": round(_moon_sub(illumination), 1),
        "bortle": round(_bortle_sub(bortle), 1),
    }


def compute_score(
    cloud: float,
    precip: float,
    wind: float,
    temp: float,
    illumination: float,
    bortle: int,
) -> int:
    """综合观星指数（0-100，含一票否决）。"""
    subs = compute_components(cloud, precip, wind, temp, illumination, bortle)
    score = (
        subs["cloud"] * 0.40
        + subs["precip"] * 0.20
        + subs["windtemp"] * 0.10
        + subs["moon"] * 0.20
        + subs["bortle"] * 0.10
    )
    # 一票否决：云量>80 或降水>50 → 压到 39（<40 落入「差」档，spec §18 强制差）
    if cloud > 80.0 or precip > 50.0:
        score = min(score, 39.0)
    return int(round(score))


def grade(score: int) -> str:
    if score >= 80:
        return "优"
    if score >= 60:
        return "良"
    if score >= 40:
        return "一般"
    return "差"


# ---- 逐小时曲线 ----


def build_hourly(
    hourly: dict,
    illumination: float,
    bortle: int,
    hours: int,
) -> list[dict]:
    """把 Open-Meteo hourly 段聚合为逐小时指数点（月相/Bortle 当天固定）。"""
    times = hourly.get("time", [])
    out: list[dict] = []
    for i, t in enumerate(times[:hours]):
        cloud = float(hourly["cloud_cover"][i])
        precip = float(hourly["precipitation_probability"][i])
        wind = float(hourly["wind_speed_10m"][i])
        temp = float(hourly["temperature_2m"][i])
        s = compute_score(cloud, precip, wind, temp, illumination, bortle)
        out.append({
            "time": t,
            "score": s,
            "grade": grade(s),
            "cloud": int(round(cloud)),
            "precip": int(round(precip)),
        })
    return out


# ---- 城市查表 ----


def _load_cities() -> list[dict]:
    global _cities
    if _cities is None:
        _cities = json.loads(_CITIES_PATH.read_text(encoding="utf-8"))
    return _cities


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_city(lat: float, lon: float) -> dict:
    """返回距 (lat, lon) 最近的国内城市记录（含 name/province/lon/lat/bortle）。"""
    cities = _load_cities()
    best = cities[0]
    best_d = _haversine(lat, lon, best["lat"], best["lon"])
    for c in cities[1:]:
        d = _haversine(lat, lon, c["lat"], c["lon"])
        if d < best_d:
            best, best_d = c, d
    return best


def list_cities() -> list[dict]:
    return _load_cities()