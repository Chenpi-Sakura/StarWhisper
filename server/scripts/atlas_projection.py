"""Atlas 共享投影公式（Azimuthal Stereographic）。

双端实现：
- Python: server/scripts/atlas_projection.py（本文件，build 脚本用）
- TypeScript: web/src/utils/atlasProjection.ts（runtime 渲染用）

公式基于球面余弦定理。中心点 c=0 时显式返回画布中心（避免双端舍入差异）。
"""
from __future__ import annotations
import math
from typing import Iterable

# 中心点 guard 阈值：cos_c ≈ 1 时返回画布中心
CENTER_GUARD_EPS = 1e-14

# 三角函数 acos 输入保护
_ACOS_CLAMP = (-1.0, 1.0)


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """球面余弦定理算角距（度）。

    >>> angular_separation(0, 0, 0, 0)
    0.0
    >>> abs(angular_separation(279.23, 38.78, 297.70, 8.87) - 34.2) < 0.5
    True
    """
    dra = math.radians(ra1 - ra2)
    cos_c = (
        math.sin(math.radians(dec1)) * math.sin(math.radians(dec2))
        + math.cos(math.radians(dec1)) * math.cos(math.radians(dec2)) * math.cos(dra)
    )
    cos_c = max(_ACOS_CLAMP[0], min(_ACOS_CLAMP[1], cos_c))
    return math.degrees(math.acos(cos_c))


def compute_center(stars: Iterable[dict]) -> tuple[float, float]:
    """单位球面 3D 向量平均 → 归一化回 (RA, Dec)。

    >>> # 北斗 7 星 golden value：(186.04, 56.55)
    >>> beidou = [
    ...     {"ra": 165.932, "dec": 61.751},
    ...     {"ra": 165.460, "dec": 56.382},
    ...     {"ra": 178.458, "dec": 53.695},
    ...     {"ra": 183.857, "dec": 57.033},
    ...     {"ra": 193.507, "dec": 55.960},
    ...     {"ra": 200.981, "dec": 54.925},
    ...     {"ra": 206.885, "dec": 49.313},
    ... ]
    >>> ra, dec = compute_center(beidou)
    >>> abs(ra - 186.04) < 0.05 and abs(dec - 56.55) < 0.05
    True
    """
    stars = list(stars)
    if not stars:
        return (0.0, 0.0)
    vx = sum(math.cos(math.radians(s["dec"])) * math.cos(math.radians(s["ra"])) for s in stars)
    vy = sum(math.cos(math.radians(s["dec"])) * math.sin(math.radians(s["ra"])) for s in stars)
    vz = sum(math.sin(math.radians(s["dec"])) for s in stars)
    n = len(stars)
    vx /= n
    vy /= n
    vz /= n
    ra = math.degrees(math.atan2(vy, vx)) % 360
    dec = math.degrees(math.atan2(vz, math.hypot(vx, vy)))
    return (ra, dec)


def compute_field(stars: Iterable[dict], viewbox: dict, padding: int = 30) -> dict:
    """找最大球面角距对应的平面半径，等比 fit 进 viewbox。

    Stereographic 下球面角距 c 对应的平面半径 r = 2·tan(c/2)。
    若 max_c > 170°，说明存在接近对跖的成员（投影会爆炸），raise。
    """
    stars = list(stars)
    center_ra, center_dec = compute_center(stars)
    if not stars:
        return {"scale": 1.0, "center": (center_ra, center_dec), "padding": padding}

    max_c = max(angular_separation(s["ra"], s["dec"], center_ra, center_dec) for s in stars)
    if max_c > 170.0:
        raise ValueError(
            f"星座成员存在接近对跖点（max_c={max_c:.1f}° > 170°），"
            f"Stereographic 投影会爆炸。请检查数据或换投影。"
        )
    if max_c < 1e-6:
        return {"scale": 1.0, "center": (center_ra, center_dec), "padding": padding}

    max_radius = 2.0 * math.tan(math.radians(max_c / 2.0))
    scale = min(
        (viewbox["w"] / 2.0 - padding) / max_radius,
        (viewbox["h"] / 2.0 - padding) / max_radius,
    )
    return {"scale": scale, "center": (center_ra, center_dec), "padding": padding}


def project(
    ra: float,
    dec: float,
    center_ra: float,
    center_dec: float,
    scale: float,
    viewbox: dict,
) -> tuple[float, float]:
    """单点 Az度thmic Stereographic 投影。

    东=右、北=上（屏幕 y 取负）。中心点 guard：cos_c ≈ 1 时返回画布中心。
    """
    dra_rad = math.radians(ra - center_ra)
    dec_rad = math.radians(dec)
    dec0_rad = math.radians(center_dec)

    cos_c = (
        math.sin(dec0_rad) * math.sin(dec_rad)
        + math.cos(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad)
    )
    cos_c = max(_ACOS_CLAMP[0], min(_ACOS_CLAMP[1], cos_c))

    # 中心点 guard
    if abs(1.0 - cos_c) < CENTER_GUARD_EPS:
        return (viewbox["w"] / 2.0, viewbox["h"] / 2.0)

    k = 2.0 / (1.0 + cos_c)

    x_local = math.cos(dec_rad) * math.sin(dra_rad)
    y_local = (
        math.cos(dec0_rad) * math.sin(dec_rad)
        - math.sin(dec0_rad) * math.cos(dec_rad) * math.cos(dra_rad)
    )

    x = viewbox["w"] / 2.0 + k * x_local * scale
    y = viewbox["h"] / 2.0 - k * y_local * scale  # 屏幕 y 翻转
    return (x, y)
