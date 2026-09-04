"""观星指数纯函数单测（services/index.py）。"""
from datetime import date

import pytest

from services import index as idx


def test_bortle_coeff_bounds():
    assert idx.bortle_coeff(1) == 1.0
    assert idx.bortle_coeff(9) == pytest.approx(0.05)
    assert idx.bortle_coeff(99) == pytest.approx(0.05)  # 越界 clamp


def test_bortle_label():
    assert idx.bortle_label(1) == "极暗夜空"
    assert idx.bortle_label(9) == "市中心"


def test_grade_four_tiers():
    assert idx.grade(85) == "优"
    assert idx.grade(75) == "良"
    assert idx.grade(50) == "一般"
    assert idx.grade(30) == "差"


def test_moon_illumination_new_and_full():
    assert abs(idx.moon_illumination(0.0)) < 1e-6       # 新月≈0
    assert abs(idx.moon_illumination(14.0) - 1.0) < 1e-6  # 满月≈1


def test_moon_labels():
    assert idx._moon_label(0.5) == "新月"
    assert idx._moon_label(14.0) == "满月"
    assert idx._moon_label(21.0) == "下弦月"


def test_compute_components_ideal_full_score():
    comps = idx.compute_components(cloud=0, precip=0, wind=0, temp=15,
                                   illumination=0.0, bortle=1)
    assert comps["cloud"] == 100.0
    assert comps["moon"] == 100.0
    assert comps["bortle"] == 100.0


def test_compute_score_ideal_is_100():
    assert idx.compute_score(0, 0, 0, 15, 0.0, 1) == 100


def test_compute_score_veto_on_cloud():
    # 云量 90 触发一票否决，无论如何都应是「差」档（<40）
    s = idx.compute_score(90, 0, 0, 15, 0.0, 1)
    assert s < 40
    assert idx.grade(s) == "差"


def test_compute_score_veto_on_precip():
    s = idx.compute_score(0, 60, 0, 15, 0.0, 1)
    assert s < 40
    assert idx.grade(s) == "差"


def test_nearest_city_beijing():
    c = idx.nearest_city(39.9042, 116.4074)
    assert c["name"] == "北京"
    assert c["bortle"] == 8


def test_build_hourly_length_and_fields():
    n = 3
    hourly = {
        "time": [f"2026-08-27T{i:02d}:00" for i in range(n)],
        "cloud_cover": [10, 85, 30],
        "precipitation_probability": [0, 5, 60],
        "wind_speed_10m": [5.0, 8.0, 12.0],
        "temperature_2m": [15.0, 14.0, 13.0],
    }
    rows = idx.build_hourly(hourly, illumination=1.0, bortle=8, hours=n)
    assert len(rows) == n
    assert rows[0]["time"] == "2026-08-27T00:00"
    assert set(rows[0].keys()) == {"time", "score", "grade", "cloud", "precip"}
    # 云量 85 的第 2 个小时应触发否决 → 差
    assert rows[1]["grade"] == "差"


def test_moon_info_smoke():
    info = idx.moon_info(date(2026, 8, 27))
    assert 0.0 <= info["phase"] < 28.0
    assert 0.0 <= info["illumination"] <= 1.0
    assert info["label"] in ("新月", "蛾眉月", "上弦月", "盈凸月",
                             "满月", "亏凸月", "下弦月", "残月")