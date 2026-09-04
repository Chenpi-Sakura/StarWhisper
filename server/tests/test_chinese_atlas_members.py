"""中国星官数据回归：独立古名 + 括号星官的 stars/lines 不得为空。

守护 `build_chinese_stars.py` 的成员归组修复：
- 括号双 key 归组（杵@箕宿 vs 杵@危宿）
- 显式映射（北斗/北极/三台/十二国）
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "traditions" / "chinese"


def _load() -> dict[str, dict]:
    by_name = {}
    for fp in DATA.glob("*.json"):
        if fp.name == "_meta.json":
            continue
        e = json.loads(fp.read_text(encoding="utf-8"))
        by_name[e["name"]] = e
    return by_name


def test_beidou_has_stars_and_lines():
    e = _load()["北斗"]
    assert len(e["stars"]) == 7
    assert len(e["lines"]) >= 6


def test_beiji_has_five_stars():
    e = _load()["北极"]
    assert len(e["stars"]) == 6
    # 北极最末点是「纽星」HIP 62572，连线末点 0.000° 命中
    assert "62572" in e["stars"]
    assert len(e["lines"]) >= 1


def test_santai_has_six_stars():
    e = _load()["三台"]
    assert len(e["stars"]) == 6
    assert len(e["lines"]) >= 1


def test_xin_xiu_has_lines():
    e = _load()["心宿"]
    assert len(e["stars"]) > 0
    assert len(e["lines"]) > 0


def test_hegu_has_lines():
    e = _load()["河鼓"]
    assert len(e["lines"]) > 0


def test_center_uses_geometric_mean_not_csv_display():
    """center 应是成员几何中心（与 csv display_ra/display_dec 解耦）。

    旧版用 csv 的人填值（如北斗 ra=183, dec=55），偏离实际成员 3-5°，
    画出来勺子整体偏。新版用 `_mean_ra` + 算术 Dec 均值。
    """
    e = _load()["北斗"]
    stars = list(e["stars"].values())
    mean_dec = sum(s["dec"] for s in stars) / len(stars)
    # center.dec 应在成员 Dec 均值 ±0.5° 之内
    assert abs(e["center"]["dec"] - mean_dec) < 0.5, (
        f"center.dec={e['center']['dec']} 与成员均值 {mean_dec:.2f} 偏差过大"
    )
    # center.ra 应是成员 RA 的 cos(Dec) 加权均值（验证 0.000° 附近）
    import math
    sx = sum(math.cos(math.radians(s["ra"])) * math.cos(math.radians(s["dec"]))
             for s in stars)
    sy = sum(math.sin(math.radians(s["ra"])) * math.cos(math.radians(s["dec"]))
             for s in stars)
    mean_ra = math.degrees(math.atan2(sy, sx)) % 360
    assert abs(e["center"]["ra"] - mean_ra) < 0.5, (
        f"center.ra={e['center']['ra']} 与 _mean_ra {mean_ra:.2f} 偏差过大"
    )


def test_beidou_bowl_and_handle_proportions_realistic():
    """北斗勺口（天枢-天璇）vs 勺柄（天璇-摇光）像素比应在合理区间。

    新公式 Azimuthal Stereographic 取代 cos(Dec) 等距投影。
    勺柄/勺口真实角距比 ≈ 25.6° / 5.4° ≈ 4.7（高 Dec 区 Stereographic 略放大）；
    我们期望像素比落在 [3.5, 5.5]（球面角距一致）。
    """
    e = _load()["北斗"]
    s = e["stars"]
    # 勺口：α UMa (天枢) — β UMa (天璇) 真实距离 ≈ 5.4°
    # 勺柄：β UMa (天璇) — η UMa (摇光) 真实距离 ≈ 25.6°
    # 比例 ≈ 1 : 4.7；新 Stereographic 下像素比应在 [3.5, 5.5] 区间
    dx_bowl = abs(s["54061"]["x"] - s["53910"]["x"])
    dy_bowl = abs(s["54061"]["y"] - s["53910"]["y"])
    bowl_pix = (dx_bowl ** 2 + dy_bowl ** 2) ** 0.5
    dx_handle = abs(s["53910"]["x"] - s["67301"]["x"])
    dy_handle = abs(s["53910"]["y"] - s["67301"]["y"])
    handle_pix = (dx_handle ** 2 + dy_handle ** 2) ** 0.5
    ratio = handle_pix / max(bowl_pix, 1)
    assert 3.5 <= ratio <= 5.5, (
        f"柄/勺比 {ratio:.2f} 偏离真实 4.7 过大，Stereographic 投影可能没生效"
    )


def test_beidou_east_is_right():
    """东=右（plan §2.1）：北斗 7 颗按 RA 增大方向画在**右侧**。

    真实 RA 升序：53910 < 54061 < 58001 < 59774 < 62956 < 65378 < 67301
    东=右约定下 x 应当**严格升序**（RA 大 → x 大）。
    """
    e = _load()["北斗"]
    s = e["stars"]
    ras_ordered = sorted(
        [(hip, s[hip]["x"]) for hip in s
         if hip in {"53910", "54061", "58001", "59774", "62956", "65378", "67301"}],
        key=lambda t: float(s[t[0]]["ra"])
    )
    xs = [x for _, x in ras_ordered]
    # 真实 RA 升序时 x 应当严格升序（东=右）
    for i in range(len(xs) - 1):
        assert xs[i] < xs[i + 1], (
            f"RA 升序时 x 应升序（东=右），但在 {ras_ordered[i][0]}({ras_ordered[i][1]}) "
            f"与 {ras_ordered[i+1][0]}({ras_ordered[i+1][1]}) 处违反"
        )
