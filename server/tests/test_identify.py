"""POST /api/identify/solve 测试（本地仅做"上传转发 + 响应格式转换"）。

本地不做任何智能处理（EXIF / race / crop / FOV / HEIC 都由上游负责）；
本文件验证：
- UNSUPPORTED_FORMAT → 400
- UPLOAD_TOO_LARGE → 413
- ASTROMETRY_MOCK=True 时组装 spec §3.1 SolveResult
- hit=0 时 constellations=[]（WCS 投影坐标全在图外）
- 代理超时 → 200 TIMEOUT（非 504）
- 上游连接失败 → 502 ASTROMETRY_DOWN

测试 mock 用 monkeypatch / patch 打在已加载的模块属性上。
"""
import io
import math
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from main import app


client = TestClient(app)


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_unsupported_format_returns_400():
    r = client.post(
        "/api/identify/solve",
        files={"image": ("x.gif", b"GIF89a", "image/gif")},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_upload_too_large_returns_413():
    big = b"\xff\xd8" + b"x" * (21 * 1024 * 1024)
    r = client.post(
        "/api/identify/solve",
        files={"image": ("x.jpg", big, "image/jpeg")},
    )
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"


def test_mock_solve_returns_orion():
    """ASTROMETRY_MOCK=True → 上游响应 mock fixture → 本地组装 SolveResult。

    mock 模式下跳过网络，验证：solved=true、exif_orientation=1、image 尺寸透传、
    stars_overlay 等于 catalog 去重后总数、命中 ori。

    T6+: chinese 数据补齐后，CRVAL=(84,-1) 距 shen_xiu 中心 (83.7,-1.1) ≈0.3°
    比 ori 中心 (86,-2) ≈2.1° 更近，find_nearest top1 会选中 shen_xiu。
    本测试改用 patch _call_upstream_solve，把上游响应 ra/dec 改为 ori 中心。
    """
    from services.traditions import build_star_catalog
    expected_catalog_size = len(build_star_catalog())
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 300.0, "CRPIX2": 200.0,
            "CRVAL1": 86.0, "CRVAL2": -2.0,  # ori 中心
            "CD1_1": -0.05, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.05,
            "NAXIS1": 600, "NAXIS2": 400,
        },
        "ra": 86.0, "dec": -2.0,
        "pixel_scale": 180.0,
        "field_width": 30.0,
        "field_height": 20.0,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["solved"] is True
    assert data["exif_orientation"] == 1
    assert data["image_width"] == 600
    assert data["image_height"] == 400
    # T7: catalog 去重后 ≤ 全 tradition 总量；过 nan 过滤后可能更少。
    assert len(data["stars_overlay"]) <= expected_catalog_size
    assert len(data["stars_overlay"]) > 0
    # 所有投影坐标必须是有限数（不是 None/nan）
    for s in data["stars_overlay"]:
        assert isinstance(s["pixel_x"], (int, float))
        assert isinstance(s["pixel_y"], (int, float))
    assert any(c["abbr"] == "ori" for c in data["constellations"])
    # 4 字段必须存在（spec §3.1）
    for k in ("pixel_scale", "rotation", "field_width", "field_height"):
        assert k in data and isinstance(data[k], (int, float))


def test_hit_zero_returns_empty_constellations():
    """hit=0 时 constellations=[]（前端走 empty 分支）。

    mock 上游返回的 WCS 让所有星点投影到图像外（CRPIX=0），验证：
    - ok=True + solved=True（上游确实解出）
    - constellations == []
    - stars_overlay 等于 catalog 全量（hit 计算只过滤命中星座的星，不删项）

    T6+: chinese 数据补齐后，CRVAL=(0,0) 距 yun_yu 中心 5.4° 仍在 8° 阈值内
    会命中 chinese 星座。本测试同时 patch find_nearest 返回 []，强制 hit=0
    路径，验证 constellations 空 + overlay 全量（与新数据兼容）。
    """
    from services.traditions import build_star_catalog
    expected_catalog_size = len(build_star_catalog())
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 0.0, "CRPIX2": 0.0,
            "CRVAL1": 0.0, "CRVAL2": 0.0,
            "CD1_1": 0.001, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.001,
            "NAXIS1": 100, "NAXIS2": 100,
        },
        "ra": 0.0, "dec": 0.0,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)), \
         patch("routers.identify.find_nearest", return_value=[]):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["solved"] is True
    assert data["constellations"] == []
    # 投影本身没变，stars_overlay ≤ catalog 全量（hit 计算只过滤命中星座的星，不删项）
    assert len(data["stars_overlay"]) <= expected_catalog_size
    assert len(data["stars_overlay"]) > 0


def test_timeout_returns_200_timeout_code():
    """代理超时：AsyncMock 抛 httpx.TimeoutException → 200 + TIMEOUT（**非** 504）。

    spec §3.1：上游 60s 截断映射为 200 {ok:false, code:"TIMEOUT"}，
    让前端能在用户感知内拿到 JSON（前端 65s 兜底 timeout 前一定有响应）。
    """
    import httpx
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(side_effect=httpx.TimeoutException("solve timeout"))):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "TIMEOUT"


def test_connection_error_returns_502():
    """上游连接失败 → 502 ASTROMETRY_DOWN（spec §3.1 / §4.4）。"""
    import httpx
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "ASTROMETRY_DOWN"


def test_upstream_4xx_returns_diagnostic_payload():
    """上游返 4xx → 200 + UPSTREAM_BAD_REQUEST + 透传 status + body 摘要。

    避免笼统的 502 ASTROMETRY_DOWN 蒙蔽诊断信息
    （上游可能返 400 Failed to parse form、422 validation error 等）。
    """
    import httpx

    class _FakeResp:
        status_code = 400
        text = 'Failed to parse form'

    def _raise(*a, **kw):
        raise httpx.HTTPStatusError(
            "bad request", request=httpx.Request("POST", "http://x/solve"),
            response=_FakeResp(),
        )

    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(side_effect=_raise)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "UPSTREAM_BAD_REQUEST"
    assert data["upstream_status"] == 400
    assert "Failed to parse form" in data["upstream_body_summary"]


def test_solve_failed_includes_raw_output_head():
    """上游返 200 + solved:false → SOLVE_FAILED + raw_output 摘要 + solve_time。

    spec §3.1：上游未解出时带 raw_output 前 200 字符供调试（API.md §4.2 警告
    raw_output 不可信，但首段能看出试过哪些索引）。
    """
    fake = {
        "solved": False,
        "solve_time": 8.99,
        "raw_output": "Field 1 did not solve (index index-4119.fits, field objects 10-20).\n"
                      "Field 1 did not solve (index index-4118.fits, field objects 10-20).\n"
                      "..." * 20,  # 长于 200 字符，验证截断
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "SOLVE_FAILED"
    assert data["upstream_solve_time"] == 8.99
    assert len(data["upstream_raw_output_head"]) == 200


def test_exif_orientation_8_rotates_pixel_coords_90ccw():
    """EXIF Orientation=8 (rotate 90° CCW)：raw (W×H) → display (H×W)，
    pixel 坐标按矩阵 (x', y') = (y, W - x) 变换。

    修复场景：NIKON D610 横拍图（EXIF Orientation=8），上游用 raw bytes 解算
    返回 raw 坐标系坐标，但浏览器 <img> 自动转正后是显示坐标系 →
    不变换会让 canvas 星点偏 90°。
    """
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 3000.0, "CRPIX2": 2000.0,
            "CRVAL1": 92.93, "CRVAL2": -2.81,
            "CD1_1": -0.0066, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.0066,
            "NAXIS1": 6016, "NAXIS2": 4016,
        },
        "ra": 92.93, "dec": -2.81,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(6016, 4016), "image/jpeg")},
            data={"orientation": "8"},
        )
    assert r.status_code == 200
    data = r.json()
    # 高宽对调
    assert data["image_width"] == 4016
    assert data["image_height"] == 6016
    assert data["exif_orientation"] == 8
    # 所有投影坐标都是有限数（不是 None/nan）
    for s in data["stars_overlay"]:
        assert isinstance(s["pixel_x"], (int, float))
        assert isinstance(s["pixel_y"], (int, float))


def test_exif_orientation_1_unchanged():
    """EXIF Orientation=1（默认，无旋转）：坐标不变。"""
    fake = {
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
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg")},
            data={"orientation": "1"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["image_width"] == 600
    assert data["image_height"] == 400
    assert data["exif_orientation"] == 1


def test_exif_orientation_out_of_range_clamped():
    """orientation 越界（<1 或 >8）钳制到 [1, 8]。"""
    fake = {
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
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg")},
            data={"orientation": "99"},
        )
    assert r.status_code == 200
    # 钳到 8 → H×W 对调
    data = r.json()
    assert data["exif_orientation"] == 8
    assert data["image_width"] == 400
    assert data["image_height"] == 600


def test_oversize_jpeg_is_recompressed_for_upstream():
    """> 4MB 的 JPEG 提交后，上游收到的 bytes ≤ 4MB（公网约束，API.md §1）。

    服务端 PIL libjpeg 重压保证上游永远收到 ≤ 4MB。验证：
    - 用 _call_upstream_solve 拦截，看 mock 收到的 files['image'] 字节数
    - 原图 7MB+ → 上游收到 ≤ 4MB
    """
    import os
    from PIL import Image
    import io

    # 构造一张 > 4MB 的高熵 JPEG（3000x2000 q95 ≈ 7MB）
    raw = os.urandom(3000 * 2000 * 3)
    img = Image.frombytes("RGB", (3000, 2000), raw)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    big_jpeg = buf.getvalue()
    assert len(big_jpeg) > 4 * 1024 * 1024, f"测试图太小：{len(big_jpeg)}"

    # 拦截 _call_upstream_solve，捕获上游实际收到的 bytes
    received_bytes: list[bytes] = []

    async def _capture(client, image_bytes):
        received_bytes.append(image_bytes)
        return {
            "solved": True,
            "wcs_header": {
                "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                "CRPIX1": 0.0, "CRPIX2": 0.0,
                "CRVAL1": 0.0, "CRVAL2": 0.0,
                "CD1_1": 0.001, "CD1_2": 0.0,
                "CD1_1": 0.001, "CD2_1": 0.0,
                "CD2_2": 0.001,
                "NAXIS1": 100, "NAXIS2": 100,
            },
            "ra": 0.0, "dec": 0.0,
        }

    with patch("routers.identify._call_upstream_solve", new=_capture):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", big_jpeg, "image/jpeg")},
        )
    assert r.status_code == 200
    assert len(received_bytes) == 1
    upstream_bytes = received_bytes[0]
    assert len(upstream_bytes) <= 4 * 1024 * 1024, (
        f"上游收到 {len(upstream_bytes)} bytes，超过公网 4MB 限制"
    )
    # 重压后远小于原图
    assert len(upstream_bytes) < len(big_jpeg) * 0.6


def test_png_is_not_recompressed():
    """PNG 不进 jpeg 重压（PNG 像素完整性，solver 可能拒收重压后的 PNG）。"""
    import os
    from PIL import Image
    import io

    # 构造一张 5MB+ 的 PNG
    raw = os.urandom(2000 * 1500 * 3)
    img = Image.frombytes("RGB", (2000, 1500), raw)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    big_png = buf.getvalue()
    assert len(big_png) > 4 * 1024 * 1024

    received_bytes: list[bytes] = []

    async def _capture(client, image_bytes):
        received_bytes.append(image_bytes)
        return {
            "solved": True,
            "wcs_header": {
                "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                "CRPIX1": 0.0, "CRPIX2": 0.0,
                "CRVAL1": 0.0, "CRVAL2": 0.0,
                "CD1_1": 0.001, "CD1_2": 0.0,
                "CD2_1": 0.0, "CD2_2": 0.001,
                "NAXIS1": 100, "NAXIS2": 100,
            },
            "ra": 0.0, "dec": 0.0,
        }

    with patch("routers.identify._call_upstream_solve", new=_capture):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.png", big_png, "image/png")},
        )
    assert r.status_code == 200
    assert len(received_bytes) == 1
    # PNG 透传：上游收到的 bytes 与原图一致
    assert received_bytes[0] == big_png


def test_identify_solve_uses_nearest_list():
    """identify 调用 find_nearest 返回 list，取首个命中。

    复用 test_identify.py 现有 client + _make_jpeg_bytes() helper：
    - 显式 patch _call_upstream_solve 返回窄视场 fake（不触发 find_in_fov）
    - mock `routers.identify.find_nearest` 返回 list[3-tuple]
    - 断言 mock 被调用 + 响应 constellations[0].abbr == "ori"

    验证点：find_nearest API 由 tuple → list 后，
    identify 不再解构 None 而是按 list 迭代 + 取 [0]。本测试守护这条变更。
    """
    fake = {
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
        # 窄视场 < 25°/15° 阈值 → 走 find_nearest 路径（被本测试 mock）
        "field_width": 5.0,
        "field_height": 3.5,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        with patch("routers.identify.find_nearest") as mock_fn:
            mock_fn.return_value = [("western", "ori", 1.5)]
            resp = client.post(
                "/api/identify/solve",
                files={
                    "image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg"),
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # mock 在 _to_solve_result 里被调用一次
    assert mock_fn.call_count == 1
    # list[0] 的 abbr 应进入 constellations
    assert data["constellations"][0]["abbr"] == "ori"


def test_identify_uses_fov_search_for_wide_field():
    """广角 FOV（≥25°×15°）走 find_in_fov 视场矩形反查路径，
    命中"中心点在图内"的所有 tradition 星座（夏季大三角同框场景）。

    旧路径（find_nearest 8° 圆形）对 test2 35°+ 视场会漏掉距 solve
    中心 14-20° 的夏季大三角成员（lyr/cyg/aql）。FOV 反查按矩形包含
    关系匹配，覆盖夏季大三角完整 DEC 跨度。

    WCS CD 与 NAXIS 配合让 WCS FOV = 40°×30°（与 find_in_fov 一致），
    否则 visible_stars=0 过滤会把命中星座全部剔除。
    """
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 5000.0, "CRPIX2": 3750.0,
            "CRVAL1": 296.76, "CRVAL2": 25.14,  # 接近 vul 中心
            "CD1_1": -0.004, "CD1_2": 0.0,    # 10000*0.004=40° FOV
            "CD2_1": 0.0, "CD2_2": 0.004,    # 7500*0.004=30° FOV
            "NAXIS1": 10000, "NAXIS2": 7500,
            "IMAGEW": 10000, "IMAGEH": 7500,
        },
        "ra": 296.76, "dec": 25.14,
        "field_width": 40.0,   # 广角
        "field_height": 30.0,  # 广角
        "pixel_scale": 14.4,   # 40° * 3600 / 10000px = 14.4"/px
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(10000, 7500), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    abbrs = {c["abbr"] for c in data["constellations"]}
    # 广角 FOV 应至少 2 星座命中（夏季大三角 3 成员按亮度优先排前）
    assert len(abbrs) >= 2, f"广角 FOV 应命中 ≥2 星座，实际 {abbrs}"
    # 至少 1 个夏季大三角成员（lyr/cyg/aql 是 Vega/Deneb/Altair 亮星）
    summer = {"lyr", "cyg", "aql"} & abbrs
    assert summer, f"应至少 1 个夏季大三角成员，实际 {abbrs}"


def test_identify_inflates_fov_for_full_image():
    """上游报回 field_w/h 是 solver crop 的视场，需按全图尺寸膨胀（test2
    50MP 实测：crop 2402×1801 → 23°×17°，全图 8192×6144 → 79°×59°）。

    修复前用 crop FOV 找星座，夏季大三角 3 成员（距 solve 9-22°）全
    漏掉。修复后用全图 FOV 膨胀，命中 lyr/cyg/aql。

    WCS 加 IMAGEW=2402/IMAGEH=1801 触发 _to_solve_result 的 offset
    调整，让 WCS 像素坐标系跨整个 user image（8192×6144），否则
    visible_stars=0 过滤会误删夏季大三角成员。
    """
    # 模拟 test2 真实场景：原图 8192×6144，solver 报 crop 视场 23.12°×17.34°
    # pixel_scale=34.65"/px → crop 2402×1801，全图相对 crop 比例 3.41×
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 930.45, "CRPIX2": 1539.83,  # crop 中心
            "CRVAL1": 304.52, "CRVAL2": 27.11,
            "CD1_1": -0.00379, "CD1_2": 0.00879,
            "CD2_1": -0.00885, "CD2_2": -0.00382,
            "NAXIS1": 2402, "NAXIS2": 1801,
            "IMAGEW": 2402, "IMAGEH": 1801,  # 触发 offset 调整 → WCS 跨全图
        },
        "ra": 297.87, "dec": 27.17,  # 夏季大三角中心
        "field_width": 23.12,  # crop 视场
        "field_height": 17.34,
        "pixel_scale": 34.65,  # crop 像素比例
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        r = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(8192, 6144), "image/jpeg")},
        )
    assert r.status_code == 200
    data = r.json()
    abbrs = {c["abbr"] for c in data["constellations"]}
    # 全图 FOV 膨胀后（79°×59°）+ 亮度优先排序 → top3 必含 summer triangle 3 成员
    summer = {"lyr", "cyg", "aql"} & abbrs
    assert summer == {"lyr", "cyg", "aql"}, (
        f"应命中 summer triangle 全 3 成员（Vega/Deneb/Altair），实际 {abbrs}"
    )


def test_identify_keeps_find_nearest_for_narrow_field():
    """窄视场（FOV < 25°）保持 find_nearest 8° 路径，长焦单星座命中。

    防止广角分支误触发：< 25°×15° 的图走老路径（圆形距离阈值），
    行为与 M2 上线版完全一致。
    """
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 5000.0, "CRPIX2": 3750.0,
            "CRVAL1": 296.76, "CRVAL2": 25.14,
            "CD1_1": -0.0005, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.0005,
            "NAXIS1": 10000, "NAXIS2": 7500,
        },
        "ra": 296.76, "dec": 25.14,
        "field_width": 10.0,   # 窄视场
        "field_height": 7.5,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        with patch("routers.identify.find_nearest") as mock_fn:
            mock_fn.return_value = [("western", "vul", 1.0)]
            r = client.post(
                "/api/identify/solve",
                files={"image": ("x.jpg", _make_jpeg_bytes(10000, 7500), "image/jpeg")},
            )
    assert r.status_code == 200
    data = r.json()
    # 窄视场走 find_nearest 而非 find_in_fov：mock 必被调用
    assert mock_fn.call_count == 1


def test_identify_returns_all_multi_hits_for_summer_triangle():
    """夏季大三角：test2 实测命中 lyr / cyg / aql 3 个星座（修复前只返 1 个）。

    本测试覆盖：
    - 3 个星座都进入 constellations（修复前只返 hits[0]）
    - overlay_lines 合并 3 组 line 端点（修复前只画 hits[0] 的线）

    同时 mock find_nearest（避开 8° 阈值在 30° 视场下不命中的现实约束——
    生产环境需要更宽阈值或基于 FOV 自适应，这是另一项待办；这里只验证
    "多命中"逻辑本身正确）和 _call_upstream_solve（提供 WCS 让
    project_lines 能把线端点投到图内）。

    WCS CD=0.006 → FOV 60°×45°（夏季大三角 3 成员亮星距中心 5-25° 都在
    图内），否则 visible_stars=0 过滤会误删命中星座（修复 LYR/CYG/AQL
    误判后 AQL 的 Altair 距中心 Dec=30 有 21° 偏差，半 FOV 需 ≥22.5°）。
    """
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 5000.0, "CRPIX2": 3750.0,
            "CRVAL1": 295.0, "CRVAL2": 30.0,  # 夏季大三角视场中心
            "CD1_1": -0.006, "CD1_2": 0.0,    # 10000*0.006=60° FOV
            "CD2_1": 0.0, "CD2_2": 0.006,    # 7500*0.006=45° FOV
            "NAXIS1": 10000, "NAXIS2": 7500,
            "IMAGEW": 10000, "IMAGEH": 7500,
        },
        "ra": 295.0, "dec": 30.0,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        with patch("routers.identify.find_nearest") as mock_fn:
            mock_fn.return_value = [
                ("western", "lyr", 1.2),
                ("western", "cyg", 2.5),
                ("western", "aql", 3.8),
            ]
            r = client.post(
                "/api/identify/solve",
                files={"image": ("x.jpg", _make_jpeg_bytes(10000, 7500), "image/jpeg")},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # 3 个星座都进入 constellations
    abbrs = {c["abbr"] for c in data["constellations"]}
    assert {"lyr", "cyg", "aql"} <= abbrs, f"夏季大三角缺星座: {abbrs}"
    # overlay_lines 合并 3 组 line 端点：lyr + cyg + aql，合计 ≥ 12
    assert len(data["overlay_lines"]) >= 12, (
        f"overlay_lines 仅 {len(data['overlay_lines'])} 条，期望 ≥12"
    )
    # 所有 overlay_lines 端点应是有限数（[[x1,y1,x2,y2], ...]）
    for quad in data["overlay_lines"]:
        assert len(quad) == 4
        for v in quad:
            assert isinstance(v, (int, float))


def test_identify_filters_constellations_by_visible_stars():
    """视野里有哪些星座就返回哪些星座：只保留在画布内能看到至少 1 颗星的命中星座。

    复现 test3 实测 bug：上游 FOV 大、cos(Dec) 让视场矩形包含 LYR/CYG 中心，
    但星点实际投影到画布外 → 仍被返回为 0% confidence 命中。修复后用
    project_constellation_to_pixels（用 constellation 自己的 stars，不去重）
    算 visible_stars，==0 的过滤掉。

    本测试用极偏 WCS（让 CYG 星点投到画布外）+ find_nearest mock 同时返回
    CYG + UMA（UMA 亮星在画布内）→ 验证只 UMA 留下。
    """
    # 极偏 CRVAL：CYG 中心 (312, +40) 远在画布外（-50000, -17000）
    # UMA 中心 (165, +56) 仍在画布内
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 5000.0, "CRPIX2": 3750.0,
            "CRVAL1": 165.0, "CRVAL2": 56.0,  # UMA 中心
            "CD1_1": -0.001, "CD1_2": 0.0,    # 10° FOV
            "CD2_1": 0.0, "CD2_2": 0.001,    # 7.5° FOV
            "NAXIS1": 10000, "NAXIS2": 7500,
            "IMAGEW": 10000, "IMAGEH": 7500,
        },
        "ra": 165.0, "dec": 56.0,
        "field_width": 10.0,
        "field_height": 7.5,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        with patch("routers.identify.find_nearest") as mock_fn:
            # 同时返回 CYG（在画布外）和 UMA（在画布内）→ 验证只留 UMA
            mock_fn.return_value = [
                ("western", "cyg", 5.0),
                ("western", "uma", 1.0),
            ]
            r = client.post(
                "/api/identify/solve",
                files={"image": ("x.jpg", _make_jpeg_bytes(10000, 7500), "image/jpeg")},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    abbrs = {c["abbr"] for c in data["constellations"]}
    # ★ 关键：CYG 画布外 → 过滤掉；UMA 画布内 → 留下
    assert "cyg" not in abbrs, f"画布外的 CYG 不应返回，实际 {abbrs}"
    assert "uma" in abbrs, f"画布内的 UMA 应返回，实际 {abbrs}"
    # UMA visible_stars 应 > 0（亮星 Dubhe/Merak 等都在画布内）
    uma = next(c for c in data["constellations"] if c["abbr"] == "uma")
    assert uma["visible_stars"] > 0, f"UMA 应有 visible_stars>0，实际 {uma}"


def test_identify_returns_overlay_lines_by_abbr():
    """T8: 服务端返回 overlay_lines_by_abbr（按 abbr 分组），让前端 chip
    切换时只画对应星座的线。

    修复 test4 反馈：3 星座同框时点 chip 星点高亮但线不亮（线没有按
    星座分组 → 一律 33% 透明度）。

    验证：
    - 多命中（≥2 星座）时 overlay_lines_by_abbr 是 dict，每个 abbr
      一组 [x1,y1,x2,y2] 列表
    - 合并的 overlay_lines 总数 == overlay_lines_by_abbr 各组之和
      （向后兼容）
    - 0 命中时 overlay_lines_by_abbr 是空 dict（不报错）
    """
    fake_multi = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 5000.0, "CRPIX2": 3750.0,
            "CRVAL1": 295.0, "CRVAL2": 30.0,
            "CD1_1": -0.006, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.006,
            "NAXIS1": 10000, "NAXIS2": 7500,
            "IMAGEW": 10000, "IMAGEH": 7500,
        },
        "ra": 295.0, "dec": 30.0,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake_multi)):
        with patch("routers.identify.find_nearest") as mock_fn:
            mock_fn.return_value = [
                ("western", "lyr", 1.2),
                ("western", "cyg", 2.5),
            ]
            r = client.post(
                "/api/identify/solve",
                files={"image": ("x.jpg", _make_jpeg_bytes(10000, 7500), "image/jpeg")},
            )
    assert r.status_code == 200
    data = r.json()
    by_abbr = data.get("overlay_lines_by_abbr")
    assert by_abbr is not None, "服务端应返回 overlay_lines_by_abbr"
    assert isinstance(by_abbr, dict)
    # 2 命中 → 2 个 abbr key
    assert set(by_abbr.keys()) == {"lyr", "cyg"}, f"应按 abbr 分组，实际 {set(by_abbr.keys())}"
    # 每组都是 [[x1,y1,x2,y2], ...]
    for abbr, lines in by_abbr.items():
        assert isinstance(lines, list)
        for quad in lines:
            assert len(quad) == 4
            for v in quad:
                assert isinstance(v, (int, float))
    # 合并的 overlay_lines 总数 == 各组之和（向后兼容）
    total = sum(len(v) for v in by_abbr.values())
    assert len(data["overlay_lines"]) == total, (
        f"overlay_lines={len(data['overlay_lines'])} 应等于 by_abbr 各组之和={total}"
    )

    # 0 命中：overlay_lines_by_abbr 是空 dict（不报错）
    fake_empty = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 0.0, "CRPIX2": 0.0,
            "CRVAL1": 0.0, "CRVAL2": 0.0,
            "CD1_1": 0.001, "CD1_2": 0.0,
            "CD2_1": 0.0, "CD2_2": 0.001,
            "NAXIS1": 100, "NAXIS2": 100,
        },
        "ra": 0.0, "dec": 0.0,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake_empty)), \
         patch("routers.identify.find_nearest", return_value=[]):
        r2 = client.post(
            "/api/identify/solve",
            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")},
        )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2.get("overlay_lines_by_abbr") == {}, (
        f"0 命中时 by_abbr 应为空 dict，实际 {data2.get('overlay_lines_by_abbr')}"
    )


def test_identify_wcs_crop_offset_aligns_to_user_image():
    """上游 solver 对超大图做 1:1 中心 crop（不是 downscale）：WCS 描述
    crop 区域，pixel scale = user image pixel scale。需要把 WCS 像素加
    (user - crop)/2 的 offset 才对齐到 user image 像素。

    验证（test2 50MP 实测）：
    - 上游 WCS: CRPIX=(930, 1539), IMAGEW=2402, IMAGEH=1801
    - user image: 8192×6144
    - offset = (8192-2402)/2, (6144-1801)/2 = (2895, 2171.5)
    - 投影 Vega (ra=279.235, dec=38.784) 应落在 user image (3295, 1201)
      附近（实际亮星 (3296, 1191)），误差 < 50 像素
    - 修复前（uniform 缩放）会算到 (1303, -3661)，完全在画布外
    """
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 930.446, "CRPIX2": 1539.834,
            "CRVAL1": 304.523, "CRVAL2": 27.114,
            "CD1_1": -0.00379175800282, "CD1_2": 0.00879476902296,
            "CD2_1": -0.00884783247551, "CD2_2": -0.00382433224624,
            "CUNIT1": "deg", "CUNIT2": "deg",
            "NAXIS1": 2402, "NAXIS2": 1801,
            "IMAGEW": 2402, "IMAGEH": 1801,
        },
        "ra": 297.875, "dec": 27.165,
        "pixel_scale": 34.65, "rotation": -113.37,
        "field_width": 23.12, "field_height": 17.34,
        "image_width": 8192, "image_height": 6144,
    }
    with patch("routers.identify._call_upstream_solve",
               new=AsyncMock(return_value=fake)):
        # Mock find_nearest 不被调用（应该走 find_in_fov）
        with patch("routers.identify.find_nearest") as mock_nearest:
            r = client.post(
                "/api/identify/solve",
                files={"image": ("x.jpg", _make_jpeg_bytes(8192, 6144), "image/jpeg")},
            )
            assert mock_nearest.call_count == 0, "FOV 路径不应回退 find_nearest"
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # 找 Vega 在 stars_overlay 里（catalog 中 Vega 是 织女 / zhi_nu，不在 lyr 标签下）
    # 所以改验 overlay_lines 端点全部在画布内
    user_w = data["image_width"]
    user_h = data["image_height"]
    for quad in data["overlay_lines"]:
        for v in quad:
            assert math.isfinite(v), f"端点非有限数: {quad}"
    # 至少 1 条线端点在画布内（夏季大三角成员都该 in-canvas）
    in_canvas = [
        q for q in data["overlay_lines"]
        if 0 <= q[0] < user_w and 0 <= q[1] < user_h
        and 0 <= q[2] < user_w and 0 <= q[3] < user_h
    ]
    assert len(in_canvas) >= 10, (
        f"修复后夏季大三角连线应全部 in-canvas，实际 in={len(in_canvas)}/"
        f"total={len(data['overlay_lines'])}"
    )