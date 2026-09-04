"""astrometry 投影层（spec §4.2）。

本模块仅做"上游响应 → 前端 canvas overlay 像素坐标"的转换。

WCS 投影：从上游 wcs_header 算标准星 ICRS → 像素坐标，供前端 canvas 描出用。

所有智能处理（EXIF 焦距识别 / race 4 段 / crop 1/2 / FOV 边界 / 索引选择）
均由上游 astrometry 服务负责（API.md §1「默认是智能的：只传图片」）。

T7 (atlas tradition) 改造：星表数据源从 server/data/bayer_index.json
迁移到 traditions.build_star_catalog() — 多 tradition 去重后的统一星表。
"""
from __future__ import annotations

from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


# Y_FLIP 模块常量：真解回归后由 scripts/wcs_regression.py 锁定为 True/False。
# 本仓库无真解服务器，先 False 占位。
Y_FLIP: bool = False


def _coerce_wcs_types(wcs_header: dict) -> dict:
    """上游 JSON serializer 把所有 WCS 字段都序列化为字符串；astropy SIP
    解析器要 int/float 对比（`header["A_ORDER"] > 1` 会 TypeError）。

    按 WCS keyword 约定分类转换：
    - ``*_ORDER`` → int（A_ORDER / B_ORDER / AP_ORDER / BP_ORDER）
    - ``CRPIX* / CRVAL* / CD* / A_* / B_* / AP_* / BP_*`` → float
    - ``NAXIS*`` → int
    - 其他保持不变（CTYPE* 是字符串）
    """
    out = dict(wcs_header)
    for k in list(out.keys()):
        v = out[k]
        if not isinstance(v, str):
            continue
        if k.endswith('_ORDER') or k.startswith('NAXIS'):
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                pass
        elif k.startswith(('CRPIX', 'CRVAL', 'CD', 'A_', 'B_', 'AP_', 'BP_')):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def project_lines(
    wcs_header: dict,
    lines: list[list[str]],
    entry_stars: dict,
    image_height: int,
    y_flip: bool = Y_FLIP,
) -> list[list[float]]:
    """把星座 ``lines`` 的端点（HIP key）从 ICRS 投到像素坐标。

    与 ``project_stars`` 的关键差异：line 端点的 ra/dec 直接从
    ``entry_stars`` 读（key=HIP catalog number），**不依赖
    build_star_catalog 去重后的子集**——这很重要，因为传统上暗星座
    （如 Vul / Sge / Equ）的连线端点往往不在被去重过滤掉的星里。

    返回 ``[[x1, y1, x2, y2], ...]``（raw 坐标系），端点无法投影时跳过该条线。
    投影到显示坐标系的 EXIF 变换由调用方在 ``identify.py`` 完成（与
    ``project_stars`` 走同一份变换矩阵，保证线和星点一致）。
    """
    wcs = WCS(fits.Header(_coerce_wcs_types(wcs_header)))
    import math
    out: list[list[float]] = []
    if not lines:
        return out
    for line in lines:
        if not isinstance(line, (list, tuple)) or len(line) != 2:
            continue
        a_key, b_key = line
        a = entry_stars.get(a_key)
        b = entry_stars.get(b_key)
        if not a or not b:
            continue
        try:
            sa = SkyCoord(ra=a["ra"] * u.deg, dec=a["dec"] * u.deg, frame="icrs")
            sb = SkyCoord(ra=b["ra"] * u.deg, dec=b["dec"] * u.deg, frame="icrs")
            xa, ya = wcs.world_to_pixel(sa)
            xb, yb = wcs.world_to_pixel(sb)
            xa, ya, xb, yb = float(xa), float(ya), float(xb), float(yb)
            if not (math.isfinite(xa) and math.isfinite(ya)
                    and math.isfinite(xb) and math.isfinite(yb)):
                continue
            if y_flip:
                ya = image_height - 1 - ya
                yb = image_height - 1 - yb
            out.append([round(xa, 2), round(ya, 2),
                        round(xb, 2), round(yb, 2)])
        except Exception:
            # astropy 单点投影失败（极罕见，如 NaN CRVAL）→ 跳过该条线
            continue
    return out


def project_stars(wcs_header: dict, image_height: int, y_flip: bool = Y_FLIP) -> list[dict]:
    """从上游 ``wcs_header`` 投影标准星 ICRS → 像素坐标。

    - ``WCS(fits.Header(...))`` 是 spec 锁定的唯一正确构造方式。
    - 上游 JSON serializer 把所有 WCS 字段都序列化为字符串；用
      ``_coerce_wcs_types`` 转回 int/float 避免 astropy SIP 解析 TypeError。
    - ``world_to_pixel`` 已 0-based（astropy ≥ 5.0），禁止再 ``-1``。
    - ``y_flip=True`` 时用 ``image_height - 1 - y``。
    - T7: 星表来源改为 ``traditions.build_star_catalog()``（多 tradition 去重）。
    """
    from services.traditions import build_star_catalog
    import math
    wcs = WCS(fits.Header(_coerce_wcs_types(wcs_header)))
    catalog = build_star_catalog()
    out: list[dict] = []
    for entry in catalog:
        sky = SkyCoord(ra=entry["ra"] * u.deg, dec=entry["dec"] * u.deg, frame="icrs")
        x, y = wcs.world_to_pixel(sky)
        x_val = float(x)
        y_val = float(y)
        # 过滤 nan/inf（astropy world_to_pixel 在投影边界外返 NaN）；
        # 这种星点本身就不可用，不写入 stars_overlay。
        if not (math.isfinite(x_val) and math.isfinite(y_val)):
            continue
        pixel_x = round(x_val, 2)
        pixel_y = round(y_val, 2)
        if y_flip:
            pixel_y = round(image_height - 1 - pixel_y, 2)
        out.append({
            "bayer": entry["bayer"],
            "name": entry["name"],
            # ★ 视觉调节 5（用户需求：canvas 标注最亮前 10% 星名）：
            # 中文名透传给前端 displayNameFor（name_zh 优先 → 含中文 name
            # 兜底 → HIP fallback）。catalog 条目自带 name_zh。
            "name_zh": entry.get("name_zh", ""),
            "magnitude": entry["magnitude"],
            "pixel_x": pixel_x,
            "pixel_y": pixel_y,
            "constellation": entry["constellation"],
            # ★ 多归属透传（用户反馈：选人马座后人马座内部星点不亮）：
            # 单一 constellation 被 chinese 抢注（build_star_catalog 去重
            # 保留首现，chinese 按目录序先加载），前端 dim 判断对 western
            # chip 全部 miss。constellations = 跨 tradition 全部归属 abbr。
            # catalog 旧版本（单测 fixture）无此字段 → fallback 单归属。
            "constellations": entry.get("constellations", [entry["constellation"]]),
        })
    return out


def project_constellation_to_pixels(
    wcs_header: dict,
    constellation_stars: dict,
    image_height: int,
    y_flip: bool = Y_FLIP,
) -> list[tuple[float, float]]:
    """把单个星座自己的 stars 字典（**不去重**）投到 raw 像素坐标。

    与 ``project_stars`` 的差异：
    - ``project_stars`` 用 ``build_star_catalog()``（HIP 去重后），同颗
      物理星可能被 chinese/zhi_nu 抢注，``constellation="lyr"`` 的星
      在 catalog 中 0 颗 → 拿它数 visible_stars 永远是 0。
    - 本函数用 constellation 自己的 ``entry["stars"]``（不跨 tradition
      去重），保证 ``lyr`` 的星就在 ``lyr`` 标签下，visible_stars 正确。

    复现：test3 极广角场景下 LYR 0/0 CYG 0/0 UMA 9/20；修复后
    LYR 5/6 CYG 4/5 UMA 9/20（按真实 WCS 投影）。

    返回 ``[(x, y), ...]`` raw 坐标，EXIF 变换由调用方负责（与
    ``project_stars`` + ``_apply_exif_orientation`` 共用同一份变换矩阵）。
    """
    wcs = WCS(fits.Header(_coerce_wcs_types(wcs_header)))
    import math
    out: list[tuple[float, float]] = []
    if not constellation_stars:
        return out
    for s_data in constellation_stars.values():
        s_ra = s_data.get("ra")
        s_dec = s_data.get("dec")
        if s_ra is None or s_dec is None:
            continue
        try:
            sky = SkyCoord(ra=s_ra * u.deg, dec=s_dec * u.deg, frame="icrs")
            x, y = wcs.world_to_pixel(sky)
            x_val = float(x)
            y_val = float(y)
            if not (math.isfinite(x_val) and math.isfinite(y_val)):
                continue
            if y_flip:
                y_val = image_height - 1 - y_val
            out.append((x_val, y_val))
        except Exception:
            # 单星投影失败（极罕见，如 NaN CRVAL）→ 跳过
            continue
    return out