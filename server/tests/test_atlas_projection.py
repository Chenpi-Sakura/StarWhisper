"""atlas_projection 单测：北斗 7 星 + Vega/Altair + 边界用例。"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import pytest

# 让脚本可 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.atlas_projection import (  # noqa: E402
    angular_separation,
    compute_center,
    compute_field,
    project,
    CENTER_GUARD_EPS,
)

VIEWBOX = {"w": 700, "h": 700}
PADDING = 30

# 北斗 7 星 (HIP, RA°, Dec°)
BEIDOU = [
    {"hip": "54061", "ra": 165.932, "dec": 61.751},  # 天枢 Dubhe
    {"hip": "53910", "ra": 165.460, "dec": 56.382},  # 天璇 Merak
    {"hip": "58001", "ra": 178.458, "dec": 53.695},  # 天玑 Phecda
    {"hip": "59774", "ra": 183.857, "dec": 57.033},  # 天权 Megrez
    {"hip": "62956", "ra": 193.507, "dec": 55.960},  # 玉衡 Alioth
    {"hip": "65378", "ra": 200.981, "dec": 54.925},  # 开阳 Mizar
    {"hip": "67301", "ra": 206.885, "dec": 49.313},  # 摇光 Alkaid
]

VEGA = {"ra": 279.23, "dec": 38.78}     # 织女一
ALTAIR = {"ra": 297.70, "dec": 8.87}    # 牛郎


def test_compute_center_known_constellation():
    """北斗 7 星 → center = (186.04°, 56.55°) ±0.05°"""
    ra, dec = compute_center(BEIDOU)
    assert abs(ra - 186.04) < 0.05, f"center_ra={ra}, expected 186.04"
    assert abs(dec - 56.55) < 0.05, f"center_dec={dec}, expected 56.55"


def test_angular_separation_known_pair():
    """Vega–Altair 教科书值 ~34.2°（±0.5°）"""
    sep = angular_separation(VEGA["ra"], VEGA["dec"], ALTAIR["ra"], ALTAIR["dec"])
    assert abs(sep - 34.2) < 0.5, f"Vega-Altair 角距={sep}, expected ~34.2°"


def test_angular_separation_same_point():
    """同一点 → 0°"""
    assert angular_separation(100, 30, 100, 30) == pytest.approx(0.0, abs=1e-9)


def test_compute_field_radial_symmetry():
    """最远星到 center 的最大 c 对应的 2·tan(c/2) × scale ≤ (viewbox/2 - padding)"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    scale = field["scale"]
    max_c = max(angular_separation(s["ra"], s["dec"], center_ra, center_dec) for s in BEIDOU)
    max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
    assert max_radius * scale <= (VIEWBOX["w"] / 2.0 - PADDING) + 1e-9
    assert max_radius * scale <= (VIEWBOX["h"] / 2.0 - PADDING) + 1e-9


def test_project_center_singularity():
    """传入 (center_ra, center_dec) → 返回画布中心，误差 < 1e-6 px"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    x, y = project(center_ra, center_dec, center_ra, center_dec, field["scale"], VIEWBOX)
    assert abs(x - VIEWBOX["w"] / 2.0) < 1e-6
    assert abs(y - VIEWBOX["h"] / 2.0) < 1e-6


def test_project_east_right():
    """ΔRA > 0 的星 x > viewbox.w/2"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    for s in BEIDOU:
        x, _ = project(s["ra"], s["dec"], center_ra, center_dec, field["scale"], VIEWBOX)
        if s["ra"] > center_ra:
            assert x > VIEWBOX["w"] / 2.0, f"{s['hip']}: ra={s['ra']} > center {center_ra} 但 x={x}"


def test_project_north_up():
    """Δdec > 0 的星 y < viewbox.h/2（屏幕 y 朝下）"""
    field = compute_field(BEIDOU, VIEWBOX, PADDING)
    center_ra, center_dec = field["center"]
    for s in BEIDOU:
        _, y = project(s["ra"], s["dec"], center_ra, center_dec, field["scale"], VIEWBOX)
        if s["dec"] > center_dec:
            assert y < VIEWBOX["h"] / 2.0, f"{s['hip']}: dec={s['dec']} > center {center_dec} 但 y={y}"
