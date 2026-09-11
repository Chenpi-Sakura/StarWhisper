"""观星指数端点单测（monkeypatch 桩掉 Open-Meteo）。"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_index(monkeypatch):
    """每个用例统一清空模块级缓存，并桩掉 astropy 天文计算降低耗时。

    个别用例可在其内部再次 monkeypatch 覆盖上述函数以断言具体取值；
    月亮/银心走共享序列的 moon_events / galactic_events（各返 dict）。
    """
    import routers.index as router_mod

    monkeypatch.setattr(router_mod, "_forecast_cache", {})
    for name in ("sunrise_time", "sunset_time", "astro_dusk_time",
                 "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, name, lambda *a, **k: "12:00")
    monkeypatch.setattr(router_mod.astro_times, "moon_events",
                        lambda *a, **k: {"moonrise": "12:00", "moonset": "12:00"})
    monkeypatch.setattr(router_mod.astro_times, "galactic_events",
                        lambda *a, **k: {"galactic_rise": "12:00",
                                         "galactic_set": "12:00"})


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


def test_index_response_contains_astro_fields(monkeypatch):
    import routers.index as router_mod

    monkeypatch.setattr(
        router_mod.astro_times, "sunrise_time", lambda *a, **k: "05:41")
    monkeypatch.setattr(
        router_mod.astro_times, "sunset_time", lambda *a, **k: "18:52")
    monkeypatch.setattr(
        router_mod.astro_times, "astro_dusk_time", lambda *a, **k: "20:36")
    monkeypatch.setattr(
        router_mod.astro_times, "astro_dawn_time", lambda *a, **k: "04:31")
    monkeypatch.setattr(
        router_mod.astro_times, "moon_events",
        lambda *a, **k: {"moonrise": "06:12", "moonset": "19:09"})
    monkeypatch.setattr(
        router_mod.astro_times, "galactic_events",
        lambda *a, **k: {"galactic_rise": "14:46", "galactic_set": "00:15"})

    resp = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert resp.status_code == 200
    astro = resp.json()["astro"]
    assert astro == {
        "sunrise": "05:41",
        "sunset": "18:52",
        "astro_dusk": "20:36",
        "astro_dawn": "04:31",
        "moonrise": "06:12",
        "moonset": "19:09",
        "galactic_rise": "14:46",
        "galactic_set": "00:15",
    }


def test_index_astro_fields_optional_null(monkeypatch):
    import routers.index as router_mod

    for name in ("sunrise_time", "sunset_time", "astro_dusk_time",
                 "astro_dawn_time"):
        monkeypatch.setattr(
            router_mod.astro_times, name, lambda *a, **k: None)
    monkeypatch.setattr(router_mod.astro_times, "moon_events",
                        lambda *a, **k: {"moonrise": None, "moonset": None})
    monkeypatch.setattr(router_mod.astro_times, "galactic_events",
                        lambda *a, **k: {"galactic_rise": None,
                                         "galactic_set": None})

    resp = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert resp.status_code == 200
    astro = resp.json()["astro"]
    assert astro["moonset"] is None
    assert astro["sunrise"] is None
    assert astro["astro_dusk"] is None
    assert astro["moonrise"] is None
    assert astro["galactic_set"] is None


def test_index_response_contains_daily_arrays(monkeypatch):
    import routers.index as router_mod

    monkeypatch.setattr(router_mod.astro_times, "sunrise_time",
                        lambda *a, **k: "05:41")
    monkeypatch.setattr(router_mod.astro_times, "sunset_time",
                        lambda *a, **k: "18:52")
    monkeypatch.setattr(router_mod.astro_times, "astro_dusk_time",
                        lambda *a, **k: "20:36")
    monkeypatch.setattr(router_mod.astro_times, "astro_dawn_time",
                        lambda *a, **k: "04:31")
    monkeypatch.setattr(router_mod.astro_times, "moon_events",
                        lambda *a, **k: {"moonrise": "06:12",
                                         "moonset": "19:09"})
    monkeypatch.setattr(router_mod.astro_times, "galactic_events",
                        lambda *a, **k: {"galactic_rise": "14:46",
                                         "galactic_set": "00:15"})

    resp = client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    assert resp.status_code == 200
    body = resp.json()
    assert body["day_index"] == 0
    assert isinstance(body["daily_moon"], list) and len(body["daily_moon"]) == 7
    assert isinstance(body["daily_astro"], list) and len(body["daily_astro"]) == 7
    assert body["daily_astro"][0]["sunset"] == "18:52"
    assert body["daily_astro"][0]["sunrise"] == "05:41"
    assert body["daily_astro"][0]["astro_dusk"] == "20:36"
    assert body["daily_astro"][0]["galactic_set"] == "00:15"
    # 区间切片：hours=24 → 24 条
    assert len(body["hourly"]) == 24
    # 每点带 night 标记（昼夜可区分）
    assert all("night" in p for p in body["hourly"])


def test_index_marks_night_between_sunset_and_dawn(monkeypatch):
    """night = 日落之后 或 天文晨光之前；白天（含暮光）为 False。"""
    import routers.index as router_mod

    monkeypatch.setattr(router_mod.astro_times, "sunset_time",
                        lambda *a, **k: "18:52")
    monkeypatch.setattr(router_mod.astro_times, "astro_dawn_time",
                        lambda *a, **k: "04:31")

    body = client.get("/api/index?lat=39.9&lon=116.4&hours=24").json()
    got = {p["time"][11:16]: p["night"] for p in body["hourly"]}
    assert got["23:00"] is True   # 日落后
    assert got["19:00"] is True   # 恰好日落之后
    assert got["18:00"] is False  # 日落前仍是白天
    assert got["03:00"] is True   # 天文晨光前
    assert got["04:00"] is True   # 04:00 < 04:31
    assert got["05:00"] is False  # 04:31 之后为白天
    assert got["12:00"] is False


def test_index_night_flag_follows_each_day_astro(monkeypatch):
    """每个小时点用其所属那天的日落/晨光判定（跨日切片正确换日）。"""
    from datetime import datetime

    import routers.index as router_mod

    monkeypatch.setattr(router_mod.astro_times, "sunset_time",
                        lambda *a, **k: "17:10")

    today = datetime.now(router_mod.astro_times.TZ).date()

    def dawn_by_day(lat, lon, now):
        # 第 0 天晨光 04:31；次日改为 09:00，用于区分“用了哪一天的 astro”
        idx = (now.date() - today).days
        return "09:00" if idx >= 1 else "04:31"

    monkeypatch.setattr(router_mod.astro_times, "astro_dawn_time", dawn_by_day)

    day0 = client.get("/api/index?lat=39.9&lon=116.4&start_hour=5&hours=1").json()
    assert day0["hourly"][0]["night"] is False  # 05:00 ≥ 04:31 → 白天

    day1 = client.get("/api/index?lat=39.9&lon=116.4&start_hour=29&hours=1").json()
    assert day1["day_index"] == 1
    assert day1["hourly"][0]["night"] is True  # 05:00 < 09:00 → 夜间


def test_index_night_flag_fallback_without_sun_events(monkeypatch):
    """极区无日出日落（均为 None）→ 退化为 20:00-05:00 粗粒度判定。"""
    import routers.index as router_mod

    for n in ("sunrise_time", "sunset_time", "astro_dusk_time",
              "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, n, lambda *a, **k: None)

    body = client.get("/api/index?lat=39.9&lon=116.4&hours=24").json()
    flags = {p["time"][11:16]: p["night"] for p in body["hourly"]}
    assert flags["21:00"] is True
    assert flags["03:00"] is True
    assert flags["12:00"] is False
    assert flags["05:00"] is False


def test_index_hours_param_slices_24h(monkeypatch):
    import routers.index as router_mod

    for n in ("sunrise_time", "sunset_time", "astro_dusk_time",
              "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, n, lambda *a, **k: "12:00")

    r = client.get("/api/index?lat=39.9&lon=116.4&start_hour=24&hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body["day_index"] == 1
    assert len(body["hourly"]) == 24


def test_index_legacy_days_param_still_works(monkeypatch):
    import routers.index as router_mod

    for n in ("sunrise_time", "sunset_time", "astro_dusk_time",
              "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, n, lambda *a, **k: "12:00")

    r1 = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert len(r1.json()["hourly"]) == 24
    r7 = client.get("/api/index?lat=39.9&lon=116.4&days=7")
    assert len(r7.json()["hourly"]) == 168


def test_index_cache_avoids_repeat_fetch(monkeypatch):
    import routers.index as router_mod

    fetch_calls = []
    real_fetch = router_mod.fetch_forecast

    async def spy(lat, lon, days=7, *, client=None):
        fetch_calls.append((lat, lon, days))
        return await real_fetch(lat, lon, days, client=client)
    monkeypatch.setattr(router_mod, "fetch_forecast", spy)

    client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    client.get("/api/index?lat=39.9&lon=116.4&start_hour=24&hours=24")
    client.get("/api/index?lat=39.9&lon=116.4&hours=168")
    assert len(fetch_calls) == 1  # 三个请求只 fetch 一次


def test_index_weather_down(monkeypatch):
    import routers.index as router_mod
    from services.weather import WeatherUnavailable

    async def fake_forecast(lat, lon, days=7, client=None):
        raise WeatherUnavailable("boom")

    monkeypatch.setattr("routers.index.fetch_forecast", fake_forecast)
    r = client.get("/api/index?lat=39.9&lon=116.4")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "WEATHER_DOWN"


def test_index_caches_daily_astro_across_requests(monkeypatch):
    """daily_moon/daily_astro 随 forecast 一起缓存，同 key 二次请求不重算。"""
    import routers.index as router_mod

    calls = {"n": 0}

    def counter(*a, **k):
        calls["n"] += 1
        return "12:00"

    def counter_pair(*a, **k):
        calls["n"] += 1
        return {"moonrise": "12:00", "moonset": "12:00",
                "galactic_rise": "12:00", "galactic_set": "12:00"}

    for n in ("sunrise_time", "sunset_time", "astro_dusk_time",
              "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, n, counter)
    monkeypatch.setattr(router_mod.astro_times, "moon_events", counter_pair)
    monkeypatch.setattr(router_mod.astro_times, "galactic_events", counter_pair)

    body = client.get("/api/index?lat=39.9&lon=116.4&hours=24").json()
    first = calls["n"]
    # 7 天 ×（日出/日落/暮光/晨光 4 次 + 月亮 1 次 + 银心 1 次）
    assert first == 42
    assert len(body["daily_moon"]) == 7
    assert len(body["daily_astro"]) == 7

    client.get("/api/index?lat=39.9&lon=116.4&start_hour=24&hours=24")
    assert calls["n"] == first  # 命中缓存，daily_astro 未重算


def test_index_cache_invalidated_when_moon_date_changes(monkeypatch):
    """缓存 moon_date 与本地今天不一致（跨自然日）→ 失效重算。"""
    import routers.index as router_mod

    calls = {"n": 0}

    def counter(*a, **k):
        calls["n"] += 1
        return "12:00"

    def counter_pair(*a, **k):
        calls["n"] += 1
        return {"moonrise": "12:00", "moonset": "12:00",
                "galactic_rise": "12:00", "galactic_set": "12:00"}

    for n in ("sunrise_time", "sunset_time", "astro_dusk_time",
              "astro_dawn_time"):
        monkeypatch.setattr(router_mod.astro_times, n, counter)
    monkeypatch.setattr(router_mod.astro_times, "moon_events", counter_pair)
    monkeypatch.setattr(router_mod.astro_times, "galactic_events", counter_pair)

    client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    first = calls["n"]
    key = router_mod._cache_key(39.9, 116.4)
    router_mod._forecast_cache[key]["moon_date"] = "2000-01-01"

    client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    assert calls["n"] > first
