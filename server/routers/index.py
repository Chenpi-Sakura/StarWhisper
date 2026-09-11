"""观星指数端点。

GET /api/index?lat=&lon=&start_hour=&hours=
       （向后兼容 days=1|7：days=1 → start_hour=0,hours=24；days=7 → 0,168）

- 按最近国内城市反查 Bortle 等级
- 一次性拉 7 天 Open-Meteo，模块级缓存 (lat,lon) 10min
- 计算 daily_moon[7] 与 daily_astro[7]（含日出）
- 按 start_hour/hours 切片返回 hourly 与聚合 score/grade/now
- hourly 每点带 `night`（日落→天文晨光为夜间可观测），供前端区分昼夜
"""

from datetime import datetime, timedelta
import asyncio

from fastapi import APIRouter, HTTPException, Query

from services import astro_times
from services import index as index_svc
from services.weather import WeatherUnavailable, fetch_forecast

router = APIRouter(prefix="/api/index", tags=["index"])

_CACHE_TTL = 600.0  # seconds
# 缓存条目：{expires_at, moon_date, forecast, daily_moon, daily_astro}
_forecast_cache: dict[tuple[float, float], dict] = {}
# 模块级锁，保护 get→fetch→set 临界区，避免缓存击穿（单城市场景全局锁足够）
_cache_lock = asyncio.Lock()


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 3), round(lon, 3))


def _build_daily_astro(lat: float, lon: float, now_local: datetime) -> list[dict]:
    """7 天逐日天文时刻。

    每日 8 项：日出 / 日落 / 天文暮光结束 / 天文晨光 / 月出 / 月落 /
    银心升起 / 银心落下。月亮与银心各自共享一条高度角序列（共 2 次 astropy 扫描/天）。
    """
    out: list[dict] = []
    for i in range(7):
        d = now_local.date() + timedelta(days=i)
        day_start = datetime.combine(d, datetime.min.time()).replace(tzinfo=astro_times.TZ)
        moon = astro_times.moon_events(lat, lon, day_start)
        galactic = astro_times.galactic_events(lat, lon, day_start)
        out.append({
            "sunrise": astro_times.sunrise_time(lat, lon, d),
            "sunset": astro_times.sunset_time(lat, lon, d),
            "astro_dusk": astro_times.astro_dusk_time(lat, lon, day_start),
            "astro_dawn": astro_times.astro_dawn_time(lat, lon, day_start),
            "moonrise": moon["moonrise"],
            "moonset": moon["moonset"],
            "galactic_rise": galactic["galactic_rise"],
            "galactic_set": galactic["galactic_set"],
        })
    return out


def _mark_night(
    hourly: list[dict], daily_astro: list[dict], start_hour: int,
) -> None:
    """就地给逐小时点标 `night`：夜间可观测 = 日落之后 或 天文晨光之前。

    白天（含暮光过渡）不是“没有指数”，而是不宜观测——前端据此在
    FIG.2 里区分昼夜并压低白昼柱。
    极区无日出日落（两项均 None）时退化为粗粒度判定（20:00-05:00）。
    """
    last = len(daily_astro) - 1
    for i, point in enumerate(hourly):
        day = min(last, max(0, (start_hour + i) // 24))
        astro = daily_astro[day]
        hhmm = str(point.get("time", ""))[11:16]
        sunset = astro.get("sunset")
        dawn = astro.get("astro_dawn")
        if sunset is None and dawn is None:
            hour = int(hhmm[:2] or 0)
            point["night"] = hour >= 20 or hour < 5
        else:
            point["night"] = bool(
                (sunset is not None and hhmm >= sunset)
                or (dawn is not None and hhmm < dawn)
            )


async def _get_index_data(lat: float, lon: float) -> dict:
    """取（含缓存）forecast + daily_moon + daily_astro 打包数据。

    命中条件：未过期 且 moon_date == 本地今天（daily_moon 随自然日变化）。
    """
    import time as _t

    key = _cache_key(lat, lon)
    async with _cache_lock:
        now_local = datetime.now(astro_times.TZ)
        today_iso = now_local.date().isoformat()
        hit = _forecast_cache.get(key)
        if (
            hit is not None
            and hit["expires_at"] > _t.time()
            and hit["moon_date"] == today_iso
        ):
            return hit
        try:
            forecast = await fetch_forecast(lat, lon, days=7)
        except WeatherUnavailable:
            _forecast_cache.pop(key, None)
            raise
        entry = {
            "expires_at": _t.time() + _CACHE_TTL,
            "moon_date": today_iso,
            "forecast": forecast,
            "daily_moon": index_svc.build_daily_moon(now_local.date(), days=7),
            "daily_astro": _build_daily_astro(lat, lon, now_local),
        }
        _forecast_cache[key] = entry
        return entry



@router.get("")
async def stargaze_index(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    days: int | None = Query(None, ge=1, le=7),
    start_hour: int = Query(0, ge=0, le=167),
    hours: int = Query(168, ge=1, le=168),
):
    # days 向后兼容
    if days is not None:
        if days == 1:
            start_hour, hours = 0, 24
        elif days == 7:
            start_hour, hours = 0, 168

    if start_hour + hours > 168:
        raise HTTPException(400, detail={
            "code": "RANGE_OUT_OF_BOUNDS",
            "message": "start_hour + hours 超出 168 小时",
        })

    city = index_svc.nearest_city(lat, lon)

    try:
        cached = await _get_index_data(lat, lon)
    except WeatherUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "WEATHER_DOWN",
                    "message": "天气服务暂不可用", "advice": "请稍后重试"},
        ) from exc

    forecast = cached["forecast"]
    daily_moon = cached["daily_moon"]
    daily_astro = cached["daily_astro"]

    # 区间切片
    sliced_times = forecast["time"][start_hour : start_hour + hours]
    sliced = {
        "time": sliced_times,
        "cloud_cover": forecast["cloud_cover"][start_hour : start_hour + hours],
        "precipitation_probability": forecast["precipitation_probability"][start_hour : start_hour + hours],
        "wind_speed_10m": forecast["wind_speed_10m"][start_hour : start_hour + hours],
        "temperature_2m": forecast["temperature_2m"][start_hour : start_hour + hours],
    }

    # 月相取切片对应日（一天的小时取该日 moon）
    day_index = start_hour // 24
    if day_index >= len(daily_moon):
        day_index = len(daily_moon) - 1
    moon_today = daily_moon[day_index]

    hourly = index_svc.build_hourly(
        sliced,
        moon_today["illumination"],
        city["bortle"],
        hours,
    )
    if not hourly:
        raise HTTPException(502, detail={
            "code": "WEATHER_EMPTY",
            "message": "天气数据为空", "advice": "请稍后重试",
        })
    _mark_night(hourly, daily_astro, start_hour)

    first = hourly[0]
    components = index_svc.compute_components(
        cloud=first["cloud"],
        precip=first["precip"],
        wind=float(sliced["wind_speed_10m"][0]),
        temp=float(sliced["temperature_2m"][0]),
        illumination=moon_today["illumination"],
        bortle=city["bortle"],
    )

    return {
        "ok": True,
        "city": city["name"],
        "province": city["province"],
        "lat": city["lat"],
        "lon": city["lon"],
        "timezone": forecast.get("timezone"),
        "bortle": city["bortle"],
        "bortle_label": index_svc.bortle_label(city["bortle"]),
        "score": first["score"],
        "grade": first["grade"],
        "moon": moon_today,
        "now": {
            "time": first["time"],
            "cloud": first["cloud"],
            "precip": first["precip"],
            "wind": float(sliced["wind_speed_10m"][0]),
            "temp": float(sliced["temperature_2m"][0]),
        },
        "components": components,
        "hourly": hourly,
        "day_index": day_index,
        "daily_moon": daily_moon,
        "daily_astro": daily_astro,
        "astro": daily_astro[day_index],  # 向后兼容
    }