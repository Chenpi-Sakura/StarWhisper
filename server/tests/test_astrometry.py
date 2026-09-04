"""services.astrometry 投影层单测。

覆盖：
- project_lines()：把星座 line 端点（HIP key）从 ICRS 投到像素坐标
- 跳过端点 ra/dec 缺失 / nan 的情况
- 端点无法在 entry.stars 找到时跳过
"""
from __future__ import annotations

import math

from services.astrometry import project_lines
from services.traditions import get_constellation


# 真实 WCS：CRVAL 在 vul 狐狸座中心 (ra=303.5, dec=24.4)，
# CD 矩阵给 ~3"/pixel（典型天文相机），CRPIX 1000 落在图像中央
VUL_WCS = {
    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
    "CRPIX1": 1000.0, "CRPIX2": 1000.0,
    "CRVAL1": 303.5, "CRVAL2": 24.4,
    "CD1_1": -0.000833, "CD1_2": 0.0,
    "CD2_1": 0.0, "CD2_2": 0.000833,
    "NAXIS1": 2000, "NAXIS2": 2000,
}


def _vul_fixture():
    """取真实的 vul 狐狸座数据（line 端点全是 HIP，bayer 全空）。"""
    entry = get_constellation("western", "vul")
    assert entry is not None, "vul 数据缺失"
    return entry


def test_project_lines_vul_produces_4_pixel_pairs():
    """vul 4 条连线 → 4 个像素坐标 quad（修复原 bayer 查找 miss 的 bug）。

    修复前：vul 的 line 端点 bayer 全空，服务端 fallback 到 HIP 字符串
    '94703'，前端 bayerMap 查不到，线全画不出来。
    修复后：服务端直接投端点 ra/dec → 像素，4 条线全部产出。
    """
    entry = _vul_fixture()
    lines = entry["lines"]
    out = project_lines(VUL_WCS, lines, entry["stars"], image_height=2000)
    assert len(out) == 4, f"期望 4 条 vul 连线，实际 {len(out)}: {out}"
    for quad in out:
        assert len(quad) == 4
        for v in quad:
            assert math.isfinite(v), f"端点非有限数: {quad}"


def test_project_lines_skips_missing_endpoint():
    """line 端点在 entry.stars 找不到 → 跳过该条线（不抛错）。"""
    entry = _vul_fixture()
    # 第一个端点用真实 HIP，第二个端点用不存在的 HIP
    bad_lines = [["94703", "9999999"]]
    out = project_lines(VUL_WCS, bad_lines, entry["stars"], image_height=2000)
    assert out == [], f"端点缺失时应跳过，实际: {out}"


def test_project_lines_skips_missing_ra_dec():
    """line 端点的 ra/dec 缺失（None）→ 跳过该条线。"""
    bad_entry_stars = {
        "94703": {"ra": 289.05, "dec": 21.39, "bayer": ""},
        "95771": {"ra": None, "dec": None, "bayer": ""},  # 缺 ra/dec
    }
    out = project_lines(VUL_WCS, [["94703", "95771"]], bad_entry_stars, image_height=2000)
    assert out == [], f"ra/dec 缺失时应跳过，实际: {out}"


def test_project_lines_returns_pixel_coordinates_in_wcs_space():
    """vul 端点 ra/dec 经 WCS 投影 → 像素坐标，必须是有限数（NaN/inf
    在 WCS 边界外会被 astropy 产出，我们应过滤掉）。不验精确值：
    WCS 中心是 vul 大致中心 ra=303.5，但最远端点 ra=289 离 CRVAL 14.5°，
    按 0.000833 deg/px 算 ≈ 17400 px 偏移——这是合成 WCS 的产物，
    真实图片解算后 WCS 中心 = 解算中心，端点偏离通常 < 5°。
    """
    entry = _vul_fixture()
    out = project_lines(VUL_WCS, entry["lines"], entry["stars"], image_height=2000)
    assert len(out) == 4
    for x1, y1, x2, y2 in out:
        for v in (x1, y1, x2, y2):
            assert math.isfinite(v), f"端点非有限数: {v}"


def test_project_lines_with_y_flip():
    """y_flip=True 时 y 坐标被 image_height - 1 - y 翻转。"""
    entry = _vul_fixture()
    out_normal = project_lines(VUL_WCS, entry["lines"], entry["stars"],
                                image_height=2000, y_flip=False)
    out_flip = project_lines(VUL_WCS, entry["lines"], entry["stars"],
                              image_height=2000, y_flip=True)
    assert len(out_normal) == len(out_flip) == 4
    for (xn1, yn1, xn2, yn2), (xf1, yf1, xf2, yf2) in zip(out_normal, out_flip):
        assert abs(xf1 - xn1) < 0.01, "y_flip 不应改 x 坐标"
        assert abs(xf2 - xn2) < 0.01
        assert abs(yf1 + yn1 - 1999) < 0.5, f"y_flip 翻转错误: {yf1} + {yn1} 应 ≈ 1999"
        assert abs(yf2 + yn2 - 1999) < 0.5


def test_project_lines_empty_input():
    """空 lines / 缺字段 → 返回空 list，不抛错。"""
    assert project_lines(VUL_WCS, [], {}, image_height=2000) == []
    # 非 2 元组的 line 跳过
    assert project_lines(VUL_WCS, [["a"]], {}, image_height=2000) == []
    assert project_lines(VUL_WCS, [["a", "b", "c"]], {}, image_height=2000) == []


def test_project_stars_passes_through_constellations(monkeypatch):
    """★ 多归属透传（用户反馈：选人马座后人马座内部星点不亮）：

    stars_overlay[].constellations 应为 catalog 的跨 tradition 全部归属
    abbr 列表（单一 constellation 被 chinese 抢注 → 前端 dim 判断对
    western chip 全部 miss）。catalog 旧条目无该字段时 fallback 单归属。"""
    from services import astrometry, traditions

    fake_catalog = [
        {"bayer": "α Sgr", "name": "Kaus Australis", "name_zh": "箕宿三",
         "magnitude": 1.85,
         "ra": 303.5, "dec": 24.4, "constellation": "dou_xiu",
         "tradition": "chinese", "hip": "89642",
         "constellations": ["sgr", "dou_xiu"]},
        {"bayer": "", "name": "LegacyOnly", "magnitude": 3.0,
         "ra": 303.6, "dec": 24.3, "constellation": "ori",
         "tradition": "western", "hip": "99999"},  # 旧条目：无 constellations
    ]
    monkeypatch.setattr(traditions, "build_star_catalog", lambda: fake_catalog)
    out = astrometry.project_stars(VUL_WCS, image_height=2000, y_flip=True)
    by_name = {s["name"]: s for s in out}
    assert by_name["Kaus Australis"]["constellations"] == ["sgr", "dou_xiu"]
    # 旧字段保留首现归属（向后兼容）
    assert by_name["Kaus Australis"]["constellation"] == "dou_xiu"
    # 旧 catalog 条目 fallback [constellation]
    assert by_name["LegacyOnly"]["constellations"] == ["ori"]
    # ★ 视觉调节 5：name_zh 透传（canvas 标注亮星名用；缺失 fallback 空串）
    assert by_name["Kaus Australis"]["name_zh"] == "箕宿三"
    assert by_name["LegacyOnly"]["name_zh"] == ""
