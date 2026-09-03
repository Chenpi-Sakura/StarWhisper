"""观星指数端点。

GET /api/index?lat=&lon=&days=1

- 按最近国内城市反查 Bortle 等级
- 聚合 Open-Meteo 逐小时天气 + 当日月相 + Bortle → 综合指数
- 返回：综合分 + 四档 + 逐小时曲线（days=1 默认 24h，最大 7 天）

失败映射：Open-Meteo 不可达 → 502 WEATHER_DOWN。
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from services import index as index_svc
from services.weather import WeatherUnavailable, fetch_forecast

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("")
async def stargaze_index(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    days: int = Query(1, ge=1, le=7),
):
    city = index_svc.nearest_city(lat, lon)

    try:
        forecast = await fetch_forecast(lat, lon, days=7)
    except WeatherUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "WEATHER_DOWN",
                "message": "天气服务暂不可用",
                "advice": "请稍后重试",
            },
        ) from exc

    today = date.today()
    moon = index_svc.moon_info(today)

    hours = min(days * 24, len(forecast["time"]))
    hourly = index_svc.build_hourly(
        forecast,
        moon["illumination"],
        city["bortle"],
        hours,
    )

    # 当前时段取第一个小时（今天）；score/grade 与之对齐
    first = hourly[0] if hourly else None
    if first is None:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "WEATHER_EMPTY",
                "message": "天气数据为空",
                "advice": "请稍后重试",
            },
        )

    components = index_svc.compute_components(
        cloud=first["cloud"],
        precip=first["precip"],
        wind=float(forecast["wind_speed_10m"][0]),
        temp=float(forecast["temperature_2m"][0]),
        illumination=moon["illumination"],
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
        "moon": moon,
        "now": {
            "time": first["time"],
            "cloud": first["cloud"],
            "precip": first["precip"],
            "wind": float(forecast["wind_speed_10m"][0]),
            "temp": float(forecast["temperature_2m"][0]),
        },
        "components": components,
        "hourly": hourly,
    }