"""Y_FLIP 锁定脚本：用 max(diffs) 判定，杜绝赌 CTYPE（spec §16.1.2）。

用法（手动或 T8 E2E 真解回拐）：

    from scripts.wcs_regression import lock_y_flip
    y_flip = lock_y_flip(solved_stars, fixture_stars, img_h)
    # 然后写入 services/astrometry.py: Y_FLIP = y_flip

FITS 像素坐标系 Y 朝上（北在上），Canvas / PIL 像素坐标系 Y 朝下
（原点在左上）。如果不解是否翻转就直接套 overlay，整张图会上下颠倒。
本脚本用真解 + 手点 fixture 比对，最大单星误差 < 2px 才认定一种朝向；
都不匹配则抛 RegressionError，阻止主链路带错配置运行。

判定逻辑：
    - 单颗星靠近中心时翻不翻都 < 2px，必须 max 防侥幸。
    - 都不匹配 → RegressionError（不让主链路带错配置跑）。
"""
from typing import TypedDict


class StarXY(TypedDict):
    x: float
    y: float


class RegressionError(Exception):
    """两种朝向都不匹配时抛错：Y_FLIP 无法判定，禁止默认选边进入主链路。"""


def _euclid(a: StarXY, b: StarXY) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


def lock_y_flip(
    solved: list[StarXY],
    fixture: list[StarXY],
    img_h: int,
    tol_px: float = 2.0,
) -> bool:
    """用 max(diffs) 判定 Y_FLIP。

    - 单星座靠近中心时翻不翻都会 < 2px，必须用 max 才能避免错选。
    - 都不匹配 → RegressionError（不让主链路带错配置跑）。
    """
    if len(solved) != len(fixture) or len(solved) == 0:
        raise RegressionError(f"长度不一致：solved={len(solved)}, fixture={len(fixture)}")

    diffs_no_flip = [_euclid(s, f) for s, f in zip(solved, fixture)]
    diffs_flip = [
        _euclid({"x": s["x"], "y": img_h - 1 - s["y"]}, f)
        for s, f in zip(solved, fixture)
    ]

    if max(diffs_no_flip) < tol_px:
        return False
    if max(diffs_flip) < tol_px:
        return True
    raise RegressionError(
        f"两种朝向都不匹配：no_flip_max={max(diffs_no_flip):.2f}px, "
        f"flip_max={max(diffs_flip):.2f}px, tol={tol_px}px"
    )