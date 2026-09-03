"""观星指数端点单测（monkeypatch 桩掉 Open-Meteo）。"""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)



def test_index_missing_params():
    r = client.get("/api/index")
    assert r.status_code == 422


def test_index_returns_score(monkeypatch):
    async def fake_forecast(lat, lon, days=7, client=None):
        return {
            "latitude": lat,
            "longitude": lon,
            "timezone": "Asia/Shanghai",
            "time": [f"2026-08-27T{i:02d}:00" for i in range(24)],
            "cloud_cover": [10] * 24,
            "precipitation_probability": [0] * 24,
            "wind_speed_10m": [5.0] * 24,
            "temperature_2m": [20.0] * 24,
        }

    monkeypatch.setattr("routers.index.fetch_forecast", fake_forecast)
    r = client.get("/api/index?lat=39.9&lon=116.4")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["city"] == "北京"
    assert body["bortle"] == 8
    assert 0 <= body["score"] <= 100
    assert body["grade"] in ("优", "良", "一般", "差")
    assert len(body["hourly"]) == 24
    assert body["moon"]["label"] in (
        "新月", "蛾眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"
    )


def test_index_weather_down(monkeypatch):
    from services.weather import WeatherUnavailable

    async def fake_forecast(lat, lon, days=7, client=None):
        raise WeatherUnavailable("boom")

    monkeypatch.setattr("routers.index.fetch_forecast", fake_forecast)
    r = client.get("/api/index?lat=39.9&lon=116.4")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "WEATHER_DOWN"