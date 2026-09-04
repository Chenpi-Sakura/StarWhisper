"""星空识别路由（spec §3.1 + §4.2 + §10）。

本地仅做"上传转发 + 响应格式转换"：
- 接收前端 multipart JPG/PNG
- 转发到上游 ``/solve``（API.md §1：默认智能决策）
- WCS 投影 8 星（spec §4.2）
- 转换为 spec §3.1 的 SolveResult 返回前端

所有智能处理（EXIF 焦距识别 / race 4 段 / crop 1/2 / FOV 边界 / 索引选择 /
HEIC 解码）均由上游 astrometry 服务负责。本地不做任何图像处理。

失败映射（spec §3.1 / §10）：
- 200 + {ok:false, code}：SOLVE_FAILED / TIMEOUT
- 413：UPLOAD_TOO_LARGE
- 400：UNSUPPORTED_FORMAT
- 502：ASTROMETRY_DOWN
"""
from __future__ import annotations

import math
import time
from io import BytesIO
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

from config import (
    ASTROMETRY_MOCK,
    ASTROMETRY_SERVICE_URL,
    ASTROMETRY_TIMEOUT,
)
from services.astrometry import (
    Y_FLIP,
    project_constellation_to_pixels,
    project_lines,
    project_stars,
)
from services.jpeg_recompress import (
    DEFAULT_TARGET_BYTES,
    is_jpeg,
    recompress_jpeg_to_target,
)
from services.traditions import (
    build_star_catalog,
    find_in_fov,
    find_nearest,
    get_constellation,
)


router = APIRouter(prefix="/api/identify", tags=["identify"])

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_SIZE = 20 * 1024 * 1024


async def _call_upstream_solve(
    client: httpx.AsyncClient,
    image_bytes: bytes,
) -> dict:
    """直接 POST 到上游 /solve（只发 image，走上游默认智能决策）。

    docs/API.md §1：「默认是智能的：只传图片，服务端脚本自动选最佳策略」；
    服务端会自动读 EXIF / 焦距 / 图像宽，决定 race / crop / scale_hint。
    本地不加 downsample_factor / depth_* 是产品原则——选择信任上游默认决策。

    mock 模式返回固定 WCS fixture。
    """
    if ASTROMETRY_MOCK:
        return {
            "solved": True,
            "wcs_header": {
                "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                "CRPIX1": 300.0, "CRPIX2": 200.0,
                "CRVAL1": 84.0, "CRVAL2": -1.0,
                "CD1_1": -0.05, "CD1_2": 0.0,
                "CD2_1": 0.0, "CD2_2": 0.05,
                "NAXIS1": 600, "NAXIS2": 400,
            },
            "ra": 84.0, "dec": -1.0,
            "pixel_scale": 180.0,
            "rotation": 0.0,
            "field_width": 30.0,
            "field_height": 20.0,
            "image_width": 600,
            "image_height": 400,
            "orientation": 1,
            "raw_output": "", "error": None,
        }
    r = await client.post(
        f"{ASTROMETRY_SERVICE_URL}/solve",
        files={"image": ("x.jpg", image_bytes, "image/jpeg")},
        timeout=ASTROMETRY_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


# EXIF Orientation 变换表（EXIF 2.3 §4.6.4 Orientation tag）。
# 上游解算坐标系是 raw bytes（不知 EXIF），但浏览器 <img> 会自动按 EXIF 转正
# 显示 → canvas 看到的是转正后坐标系。后端不能读 EXIF（“本地不做图像处理”），故由
# 前端读 EXIF Orientation 后随 FormData 传过来，本地按矩阵把 raw pixel 坐标变到
# 显示坐标系。
#
# 返回的 image_width/image_height 也要按 orientation 对调成显示图尺寸，让前端
# canvas 计算 aspect-fit 与显示图完全对齐。
#
# raw (x, y) in [0..W)×[0..H) → display (x', y') in [0..W')×[0..H')
_EXIF_ORIENTATION_TRANSFORMS = {
    1: lambda x, y, w, h: (x, y),           # 正常
    2: lambda x, y, w, h: (w - x, y),       # 水平翻转
    3: lambda x, y, w, h: (w - x, h - y),   # 旋转 180°
    4: lambda x, y, w, h: (x, h - y),       # 垂直翻转
    5: lambda x, y, w, h: (y, x),           # transpose (90° CW + 水平)
    6: lambda x, y, w, h: (h - y, x),       # 旋转 90° CW（显示 H×W）
    7: lambda x, y, w, h: (h - y, w - x),   # transverse
    8: lambda x, y, w, h: (y, w - x),       # 旋转 90° CCW（显示 H×W）
}
# Orientation 5/6/7/8 会让显示图高宽对调；1/2/3/4 不变
_EXIF_ORIENTATION_SWAPS_DIMS = {5, 6, 7, 8}


def _apply_exif_orientation(
    stars: list[dict],
    width: int,
    height: int,
    orientation: int,
) -> tuple[list[dict], int, int]:
    """按 EXIF Orientation 变换 star pixel_x/pixel_y 到显示坐标系。

    返回 (transformed_stars, display_w, display_h)。
    """
    transform = _EXIF_ORIENTATION_TRANSFORMS.get(orientation)
    if transform is None:
        return stars, width, height  # 未知 / 默认为 1
    if orientation in _EXIF_ORIENTATION_SWAPS_DIMS:
        display_w, display_h = height, width
    else:
        display_w, display_h = width, height
    out = []
    for s in stars:
        nx, ny = transform(s["pixel_x"], s["pixel_y"], width, height)
        out.append({**s, "pixel_x": round(nx, 2), "pixel_y": round(ny, 2)})
    return out, display_w, display_h


def _transform_line_to_display(
    line: list[float], orientation: int, width: int, height: int,
) -> list[float]:
    """把 [x1, y1, x2, y2] raw 像素端点按 EXIF Orientation 变换到显示坐标系。

    与 ``_apply_exif_orientation`` 共用同一份变换矩阵，保证线端点与
    stars_overlay 星点位置严格一致（线连的两颗星视觉上同位）。
    """
    transform = _EXIF_ORIENTATION_TRANSFORMS.get(orientation)
    if transform is None:
        return [round(v, 2) for v in line]
    x1, y1, x2, y2 = line
    nx1, ny1 = transform(x1, y1, width, height)
    nx2, ny2 = transform(x2, y2, width, height)
    return [round(nx1, 2), round(ny1, 2), round(nx2, 2), round(ny2, 2)]


def _to_solve_result(
    result: dict,
    width: int,
    height: int,
    orientation: int,
    solve_time: float,
) -> dict:
    """组装 SolveResult（spec §3.1）。

    T7 (atlas tradition): 走 wcs 中心反查 traditions；constellations 按命中 tradition × abbr 给出。
    visible_stars 按命中星座 (abbr) 过滤后统计在画面内的星点数（不含其他星座的可见星）。

    永远按"不限"全 tradition 反查（merged catalog），tradition 过滤由前端
    锁定 + UI 过滤（`scan.lockedTradition`）完成，避免后端 re-solve 浪费
    20s astrometry.net 调用。

    ``orientation`` 由前端读 EXIF Orientation 后传入；本函数把 raw pixel 坐标
    按 EXIF Orientation 矩阵变换到与浏览器 <img> 自动转正后一致的显示坐标系。
    """
    wcs_header = result["wcs_header"]
    # ★ WCS 坐标系对齐：上游 solver 对超大图（test2 50MP）做 1:1 中心 crop
    # 后解算（实测 crop 2402×1801，user 8192×6144），WCS 描述的是 crop 区域的
    # 全像素尺度（pixel scale = CD magnitude = 34.65"/px = user image pixel
    # scale，无 downscale）。WCS 像素 (x, y) 对应 user image 像素
    # (x + (user_w - crop_w)/2, y + (user_h - crop_h)/2)。
    # test1 24MP (6016×4016) 不走 crop，IMAGEW = 6016 = 用户图宽 → 不进此分支。
    # 验证（test2 夏季大三角）：Vega/Altair/Deneb/Albireo/Sadr 投影与用户图
    # 亮星位置误差 < 35 px（含 SIP 后 < 12 px）。
    # 上游不返回 NAXIS1/2（实测 None），用 IMAGEW/IMAGEH 字段。
    imagew_wcs = int(wcs_header.get("IMAGEW") or 0)
    imageh_wcs = int(wcs_header.get("IMAGEH") or 0)
    if imagew_wcs > 0 and imageh_wcs > 0 and (imagew_wcs != width or imageh_wcs != height):
        offset_x = (width - imagew_wcs) / 2.0
        offset_y = (height - imageh_wcs) / 2.0
        wcs_header = {
            **wcs_header,
            "NAXIS1": width,
            "NAXIS2": height,
            "IMAGEW": width,
            "IMAGEH": height,
            "CRPIX1": float(wcs_header.get("CRPIX1", 0)) + offset_x,
            "CRPIX2": float(wcs_header.get("CRPIX2", 0)) + offset_y,
        }
    raw_stars = project_stars(wcs_header, image_height=height, y_flip=Y_FLIP)

    stars, display_w, display_h = _apply_exif_orientation(
        raw_stars, width, height, orientation,
    )

    # ★ 反查 wcs 中心 → 命中 constellation（多命中：夏季大三角 3 个星座同框）
    constellations: list[dict] = []
    nearest_hits: list[tuple[str, str, float]] = []
    # 优先级：上游返回的 result['ra']/result['dec'] 是"后处理后的准确中心"；
    # 而 wcs_header 的 CRVAL1/CRVAL2 是 FITS header 原始中心，可能有 1-2° 偏差
    # （这导致猎户座样图 CRVAL=94.17° 实际响应 ra=92.93°，差 1.24°）。
    # 这里用上游 result 的 ra/dec 作为反查坐标，更贴近响应中展示给用户的值。
    target_ra = result.get("ra") if result.get("ra") is not None else wcs_header.get("CRVAL1", 0)
    target_dec = result.get("dec") if result.get("dec") is not None else wcs_header.get("CRVAL2", 0)
    # ★ 上游报回的 field_w/h 通常是 solver 处理过的 CROP 视场（test2 50MP
    # downscale 后 crop 2402×1801 → 23°×17°），但用户提交的是全图
    # 8192×6144，crop 居中 → 全图 FOV 约 79°×59°。直接用 crop FOV 找星座
    # 会漏掉夏季大三角 3 成员（距 solve 中心 9-22°，全在 crop FOV 外）。
    # 用全图 FOV（按 crop 居中假设 + 原图/crop 比例外推）做 find_in_fov。
    # 上游没报回 FOV 时 fallback find_nearest 8°。
    upstream_field_w = float(result.get("field_width") or 0)
    upstream_field_h = float(result.get("field_height") or 0)
    pixel_scale = float(result.get("pixel_scale") or 0)
    if upstream_field_w > 0 and upstream_field_h > 0 and pixel_scale > 0:
        crop_w = upstream_field_w * 3600.0 / pixel_scale
        crop_h = upstream_field_h * 3600.0 / pixel_scale
        # crop 居中假设：全图 FOV = crop FOV + 两侧扩展
        extra_w_deg = max(0.0, width - crop_w) / 2.0 * pixel_scale / 3600.0
        extra_h_deg = max(0.0, height - crop_h) / 2.0 * pixel_scale / 3600.0
        full_field_w = upstream_field_w + 2 * extra_w_deg
        full_field_h = upstream_field_h + 2 * extra_h_deg
        # 永远按"不限"全 tradition 反查（merged catalog），前端按
        # `scan.lockedTradition` 过滤展示。理由：tradition 仅影响 constellation
        # 标签（v4 §1 已确认 astrometry 与 tradition 完全无关），不必 re-solve
        # 浪费 20s 上游调用。
        hits = find_in_fov(
            float(target_ra), float(target_dec),
            field_w=full_field_w, field_h=full_field_h,
            top_k=3,
        )
        # FOV 反查空命中时 fallback find_nearest 8°（极端边缘 case）
        if not hits:
            hits = find_nearest(
                float(target_ra), float(target_dec),
                max_sep_deg=8.0,
                top_k=3,
            )
    else:
        # 没 FOV 数据：旧路径 8° 圆形距离阈值
        hits = find_nearest(
            float(target_ra), float(target_dec),
            max_sep_deg=8.0,
            top_k=3,
        )
    if hits:
        nearest_hits = list(hits)
        # ★ confidence 归一化分母：FOV 路径用 FOV 半宽（避免 sep 远大于 8°
        # 时 confidence 为负），find_nearest 路径保持 8° 旧公式。
        fov_radius = (upstream_field_w + 2 * extra_w_deg) / 2.0 if (
            upstream_field_w > 0 and pixel_scale > 0
        ) else 0
        candidates: list[dict] = []
        for trad, abbr, sep_deg in hits:
            entry = get_constellation(trad, abbr)
            if entry is None:
                continue
            total = len(entry["stars"])
            # ★ 关键：用 constellation 自己的 stars（不去重）算 visible_stars。
            # build_star_catalog() 按 HIP 去重，lyr 的星（Vega=91262）会被
            # chinese/zhi_nu 抢注，constellation="lyr" 的星在 catalog 中
            # 0 颗 → 用 catalog 数 visible_stars 永远是 0，会被错过滤掉。
            # project_constellation_to_pixels 用 entry["stars"] 直接投，
            # 保证 lyr 的星就在 lyr 标签下，visible_stars 真实可靠。
            raw_pixels = project_constellation_to_pixels(
                wcs_header,
                entry.get("stars", {}),
                image_height=height,
                y_flip=Y_FLIP,
            )
            transform = _EXIF_ORIENTATION_TRANSFORMS.get(orientation)
            visible_stars = 0
            for x, y in raw_pixels:
                if transform is not None:
                    nx, ny = transform(x, y, width, height)
                else:
                    nx, ny = x, y
                if 0 <= nx <= display_w and 0 <= ny <= display_h:
                    visible_stars += 1
            # confidence 公式：FOV 路径用 FOV 半宽（夏季大三角等远距离星座
            # 不会被算成负值），否则保持 8° 旧公式
            if fov_radius > 0:
                conf = max(0.0, round(1 - sep_deg / fov_radius, 3))
            else:
                conf = max(0.0, round(1 - sep_deg / 8.0, 3))
            candidates.append({
                "tradition": trad,
                "abbr": abbr,
                "name": entry["name"],
                "latin": entry.get("latin", ""),
                "confidence": conf,
                "visible_stars": visible_stars,
                "total_bright_stars": total,
            })
        # ★ 视野里有哪些星座就返回哪些星座：
        #   - visible_stars == 0 → FOV 矩形内但实际投影在图外（如 test3
        #     极广角场景下 LYR/CYG 因 cos(Dec) 校正被纳入 FOV 但星点
        #     实际在画布外）→ 过滤掉
        #   - 按 confidence 降序排：让最高 confidence 自动成为 [0]，
        #     前端 ScanView.activeConstellation 默认拿它当 active
        #   - 同步 nearest_hits 让 overlay_lines 只画过滤后的星座
        candidates = [c for c in candidates if c["visible_stars"] > 0]
        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        constellations = candidates
        nearest_hits = [
            (c["tradition"], c["abbr"], 0.0) for c in candidates
        ]
    # 无命中: constellations = []，前端走 empty 分支

    cd11 = float(wcs_header.get("CD1_1", 0.0))
    cd12 = float(wcs_header.get("CD1_2", 0.0))
    cd21 = float(wcs_header.get("CD2_1", 0.0))
    cd22 = float(wcs_header.get("CD2_2", 0.0))
    pixel_scale = round(((abs(cd11) + abs(cd22)) / 2.0) * 3600.0, 2)
    rotation = round(math.degrees(math.atan2(cd21, cd22)), 2)

    # ★ overlay_lines 改为 [[x1, y1, x2, y2], ...] 像素坐标（raw 坐标系）
    # 原因：暗星座（Vul / Sge / Equ）连线端点 bayer 全为空，前端按 bayer
    # 查 bayerMap 必 miss → 线全画不出来。改为服务端直接投影：
    # 1. 不依赖 entry.bayer 字段（暗星座无拜尔命名）
    # 2. 不依赖 build_star_catalog（去重后可能丢端点）
    # 3. 前端拿到的就是像素坐标，少一次字符串匹配
    # 4. 多命中合并：每个命中星座的 lines 都投影后拼接（夏季大三角 3 个星座
    #    同时显示，lines 来自 lyr + cyg + aql 三组 entry）
    # 投影在 raw 坐标系（height），再走与 stars 同一份 EXIF 变换矩阵，保证一致。
    # ★ T8: 同时返回 overlay_lines_by_abbr（按 abbr 分组），让前端 chip 切换
    # 时只画对应星座的线（修复 test4 反馈：点 chip 星点高亮但线不亮）——
    # 旧 overlay_lines（扁平合并）保留以兼容老前端/单测。
    overlay_lines_by_abbr: dict[str, list[list[float]]] = {}
    for trad, abbr, _sep in nearest_hits:
        entry = get_constellation(trad, abbr)
        if entry is None:
            continue
        overlay_lines_by_abbr[abbr] = project_lines(
            wcs_header,
            entry.get("lines", []),
            entry.get("stars", {}),
            image_height=height,
            y_flip=Y_FLIP,
        )
    overlay_lines_raw: list[list[float]] = []
    for abbr in overlay_lines_by_abbr:
        overlay_lines_raw.extend(overlay_lines_by_abbr[abbr])
    overlay_lines: list[list[float]] = [
        _transform_line_to_display(line, orientation, width, height)
        for line in overlay_lines_raw
    ]
    overlay_lines_by_abbr_display: dict[str, list[list[float]]] = {
        abbr: [
            _transform_line_to_display(line, orientation, width, height)
            for line in lines
        ]
        for abbr, lines in overlay_lines_by_abbr.items()
    }

    return {
        "ok": True,
        "solved": True,
        "ra": result.get("ra"),
        "dec": result.get("dec"),
        "pixel_scale": pixel_scale,
        "rotation": rotation,
        "field_width": result.get("field_width"),
        "field_height": result.get("field_height"),
        "solve_time": round(solve_time, 2),
        "image_width": display_w,
        "image_height": display_h,
        "exif_orientation": orientation,
        "constellations": constellations,
        "stars_overlay": stars,
        "overlay_lines": overlay_lines,
        "overlay_lines_by_abbr": overlay_lines_by_abbr_display,
    }


async def _solve_internal(
    image_bytes: bytes, width: int, height: int, orientation: int = 1,
) -> dict:
    """主流程：转发到上游 /solve → 失败映射或组装 SolveResult。

    失败映射分级：
    - TimeoutException → 200 TIMEOUT（上游 60s 未响应）
    - HTTPStatusError（4xx/5xx） → 200 UPSTREAM_BAD_REQUEST，带 status + body 摘要
      （透传上游真实原因给前端，避免 502 蒙蔽诊断信息）
    - HTTPError（连接/网络） → 502 ASTROMETRY_DOWN（上游不可达）
    - 200 + solved:false → SOLVE_FAILED / TIMEOUT（上游报告未解出）
    """
    start = time.time()
    async with httpx.AsyncClient(timeout=ASTROMETRY_TIMEOUT) as client:
        try:
            result = await _call_upstream_solve(client, image_bytes)
        except httpx.TimeoutException:
            return {
                "ok": False,
                "code": "TIMEOUT",
                "message": "上游解算超时",
                "advice": "请尝试视野稍窄的星空区域照片。",
            }
        except httpx.HTTPStatusError as e:
            # 上游主动返 4xx/5xx（不是网络问题）。透传 status + body 前 200 字符
            # 让前端能看到真实原因（“Failed to parse form”、“scale_low 越界”等）。
            body = (e.response.text or "")[:200]
            return {
                "ok": False,
                "code": "UPSTREAM_BAD_REQUEST",
                "message": f"上游返 HTTP {e.response.status_code}",
                "upstream_status": e.response.status_code,
                "upstream_body_summary": body,
                "advice": "请重试一次，或换一张照片。",
            }
        except httpx.HTTPError:
            # ConnectError / NetworkError / 其他传输问题 → 上游不可达
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "ASTROMETRY_DOWN",
                    "message": "星图解析引擎暂不可用",
                    "advice": "请稍后重试或换一张照片",
                },
            )

    if not result.get("solved"):
        error_text = (result.get("error") or "") + (result.get("raw_output") or "")
        if "timed out" in error_text.lower():
            return {
                "ok": False,
                "code": "TIMEOUT",
                "message": "上游解算超时",
                "advice": "请尝试视野稍窄的星空区域照片。",
            }
        return {
            "ok": False,
            "code": "SOLVE_FAILED",
            "message": "引擎未能解算",
            "upstream_solve_time": result.get("solve_time"),
            "upstream_raw_output_head": (result.get("raw_output") or "")[:200],
            "advice": "星点模糊或光害过强, 请用更澄澈的夜空照片重试。",
        }

    return _to_solve_result(result, width, height, orientation, time.time() - start)


@router.post("/solve")
async def solve(
    image: UploadFile = File(...),
    orientation: int = Form(1),
) -> Any:
    """解算星图。

    ``orientation`` 来自前端读 EXIF Orientation（1-8），用于把上游 raw 像素
    坐标变换到浏览器自动转正后的显示坐标系。本地不读 EXIF（按"本地不做图像处理"原则），
    orientation 为可选字段，缺省=1（无旋转）。

    T8+：tradition 过滤移到前端。后端永远按"不限"全 tradition 反查（merged
    catalog），前端按 ``scan.lockedTradition`` 过滤展示 constellation 列表。
    原因：astrometry 与 tradition 完全无关，切 tradition 不应触发 20s 重解。
    """
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_FORMAT",
                "message": "仅支持 JPG、PNG 格式",
                "advice": None,
            },
        )
    content = await image.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "UPLOAD_TOO_LARGE",
                "message": "图片超过 20MB 限制",
                "advice": None,
            },
        )

    # 公网上传 ≤ 4MB 约束（API.md §1 关键约束 1）：服务端用 PIL libjpeg 自适应
    # 重压 JPEG（默认 q90 → q85 → q80，≥ 70）。原因：web 端 canvas Skia 与
    # mozjpeg-wasm 在 chrominance quantization / DCT 实现上与 native libjpeg
    # 存在像素差异，部分相机长焦 + 大图（实测 test1 D610 MPO、test2 50MP）会
    # 触发 astrometry.net source extractor 拒绝。服务端 native libjpeg 与
    # astrometry.net 同源，最稳定。
    # PNG 不动（保持 PNG 像素数据完整性，避免解算失败）。
    # 失败兜底：保留原图继续，不阻塞 solve（warning 已在服务层 log）。
    if is_jpeg(content):
        try:
            new_content, info = recompress_jpeg_to_target(
                content, target_bytes=DEFAULT_TARGET_BYTES,
            )
            if info["compressed"]:
                content = new_content
        except (ValueError, RuntimeError):
            # 无效 JPEG 或极端 case（PNG 误判 / 已接近 JPEG 上限）→ 保留原图
            # 让上游自己处理（最坏情况：上游 400 "Failed to parse form"）
            pass

    # 读真实尺寸（透传给上游的 image_width/image_height）。
    # EXIF Orientation 由前端读后传入，避免本地读 EXIF（“本地不做图像处理”原则）。
    img = Image.open(BytesIO(content))
    width, height = img.size
    orientation = max(1, min(8, int(orientation)))  # 限制 1-8

    return await _solve_internal(
        content, width, height, orientation,
    )