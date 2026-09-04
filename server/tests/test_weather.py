"""Open-Meteo 客户端单测（httpx.MockTransport 桩）。"""

import httpx
import pytest

from services.weather import WeatherUnavailable, fetch_forecast


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _forecast_body(extra: dict | None = None) -> dict:
    base = {
        "latitude": 39.9,
        "longitude": 116.4,
        "timezone": "Asia/Shanghai",
        "hourly": {
            "time": ["2026-08-27T00:00", "2026-08-27T01:00"],
            "cloud_cover": [10, 20],
            "precipitation_probability": [0, 5],
            "wind_speed_10m": [3.0, 4.0],
            "temperature_2m": [22.0, 21.0],
        },
    }
    if extra:
        base.update(extra)
    return base


def test_fetch_forecast_parses_fields():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "cloud_cover" in request.url.params["hourly"]
        return httpx.Response(200, json=_forecast_body())

    result = None

    import asyncio

    async def run():
        nonlocal result
        result = await fetch_forecast(39.9, 116.4, days=7, client=_client(handler))

    asyncio.run(run())

    assert result["cloud_cover"] == [10, 20]
    assert result["wind_speed_10m"] == [3.0, 4.0]


def test_fetch_forecast_non_200_raises():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    import asyncio

    async def run():
        with pytest.raises(WeatherUnavailable):
            await fetch_forecast(39.9, 116.4, client=_client(handler))

    asyncio.run(run())


def test_fetch_forecast_network_error_raises():
    import asyncio

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async def run():
        with pytest.raises(WeatherUnavailable):
            await fetch_forecast(39.9, 116.4, client=_client(handler))

    asyncio.run(run())


def test_fetch_forecast_invalid_json_raises():
    import asyncio

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    async def run():
        with pytest.raises(WeatherUnavailable):
            await fetch_forecast(39.9, 116.4, client=_client(handler))

    asyncio.run(run())