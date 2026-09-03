"""Open-Meteo 天气客户端（观星指数数据源）。

无状态、无落盘的逐小时预报聚合。仅负责调 Open-Meteo 免费接口并
结构化返回；评分、月相、Bortle 都在 services/index.py 完成。

依赖注入：``client`` 参数允许测试注入 httpx.MockTransport 客户端，
生产路径在缺省时内部创建并关闭。
"""

import httpx

from config import OPEN_METEO_TIMEOUT, OPEN_METEO_URL

# Open-Meteo hourly 字段白名单（对应 brief §5：云量/降水/风速/温度）
HOURLY_FIELDS = (
    "cloud_cover",
    "precipitation_probability",
    "wind_speed_10m",
    "temperature_2m",
)


class WeatherUnavailable(Exception):
    """Open-Meteo 调用失败（网络错误 / 非 200）。router 层转 502 WEATHER_DOWN。"""


def _build_params(lat: float, lon: float, days: int) -> dict:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(HOURLY_FIELDS),
        "forecast_days": str(int(days)),
        "timezone": "auto",
    }


def _parse(data: dict) -> dict:
    """把 Open-Meteo 原始响应收敛为内部结构，字段缺失用空列表兜底。"""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    seq = {
        field: hourly.get(field, [])
        for field in HOURLY_FIELDS
    }
    return {
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "timezone": data.get("timezone", "auto"),
        "time": times,
        "cloud_cover": seq["cloud_cover"],
        "precipitation_probability": seq["precipitation_probability"],
        "wind_speed_10m": seq["wind_speed_10m"],
        "temperature_2m": seq["temperature_2m"],
    }


async def fetch_forecast(
    lat: float,
    lon: float,
    days: int = 7,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """拉取逐小时预报（默认 7 天，168 小时）。

    - 网络失败 / 非 200 → 抛 WeatherUnavailable
    - 成功返回 ``_parse`` 结构
    """
    params = _build_params(lat, lon, days)
    try:
        if client is not None:
            resp = await client.get(OPEN_METEO_URL, params=params)
        else:
            async with httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT) as cli:
                resp = await cli.get(OPEN_METEO_URL, params=params)
    except httpx.HTTPError as exc:
        raise WeatherUnavailable(f"Open-Meteo 请求失败: {exc}") from exc

    if resp.status_code != 200:
        raise WeatherUnavailable(f"Open-Meteo HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise WeatherUnavailable("Open-Meteo 响应非 JSON") from exc

    return _parse(payload)