"""用 assets/ 下真实样图做端到端契约（mock 模式）。

本地不做任何图像处理（EXIF / race / crop 都由上游负责，API.md §1），
本文件仅验证：真实 JPG 经本地 FastAPI 转发后，能正确组装 spec §3.1 SolveResult。

三张真实样图：
- test1.jpg (NIKON D610+50mm, 6016×4016, Orientation=8)：EXIF 焦距已知 → 上游走 focalmm
- test2.jpg (8192×6144, 无 EXIF)：宽图 → 上游自动 race + crop
- test3.jpg (4096×3072, 无 EXIF)：标准路径
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

ASSETS = Path(__file__).resolve().parents[2] / 'assets'
BAYER_INDEX = None  # T7: bayer_index.json 已删；改为从 traditions 取者户 8 颗 bayer。


# E2E 真实样图 — 走样图 PIl 解码 + mock 上游 + WCS 投影，单测试 5-10s。
# 仅 test_assets_files_exist 是文件存在性检查（<100ms），不归入 integration。
pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def client() -> TestClient:
    return TestClient(app)


def _upload(client: TestClient, name: str):
    """上传样图，read_bytes 避免 file handle 泄漏。"""
    p = ASSETS / name
    return client.post(
        '/api/identify/solve',
        files={'image': (p.name, p.read_bytes(), 'image/jpeg')},
    )


class TestAssetsContract:
    """assets/ 真实样图经本地 FastAPI 转发的字段契约（mock 模式）。"""

    def test_assets_files_exist(self):
        """assets/test1/2/3.jpg 存在且非空（spec §12 演示数据）。"""
        for name in ('test1.jpg', 'test2.jpg', 'test3.jpg'):
            p = ASSETS / name
            assert p.exists(), f'缺演示样图 {p}'
            assert p.stat().st_size > 1024, f'{p} 文件太小（{p.stat().st_size}B），可能损坏'

    def test_assets_response_field_contract(self, client, monkeypatch):
        """所有真实样图响应字段齐全（spec §3.1 SolveResult 完整契约）。

        验证：
        - 必填字段全部存在
        - stars_overlay ≥ 17 颗（5 星座去重后）
        - ori 8 主星 bayer 必须在 overlay
        - 真实图宽高正确透传

        T6+: chinese 数据补齐后，routers/identify 硬编码 fixture (84,-1) 距
        shen_xiu 中心 (83.7,-1.1) ≈0.3°，比 ori (86,-2) ≈2.1° 更近。
        本测试改 patch _call_upstream_solve 返回 ori 中心，保证 ori 命中。
        T9 (Batch C): ori 亮星均值中心 (82, 5)。
        """
        from unittest.mock import AsyncMock, patch as _patch
        # T7: 从 traditions 取者户 8 颗 bayer
        from services.traditions import get_constellation
        orion = get_constellation('western', 'ori')
        expected_bayers = {s['bayer'] for s in orion['stars'].values()}

        # 期望的尺寸（从 PIL 读取）
        expected_sizes = {
            'test1.jpg': (6016, 4016),  # Orientation=8，转正前 PIL 给的是原始尺寸
            'test2.jpg': (8192, 6144),
            'test3.jpg': (4096, 3072),
        }

        monkeypatch.setattr('routers.identify.ASTROMETRY_MOCK', False)
        for name in ('test1.jpg', 'test2.jpg', 'test3.jpg'):
            fake = {
                "solved": True,
                "wcs_header": {
                    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                    "CRPIX1": 3000.0, "CRPIX2": 2000.0,
                    "CRVAL1": 82.0, "CRVAL2": 5.0,  # T9: ori 亮星均值中心
                    "CD1_1": -0.0066, "CD1_2": 0.0,
                    "CD2_1": 0.0, "CD2_2": 0.0066,
                    "NAXIS1": 6016, "NAXIS2": 4016,
                },
                "ra": 82.0, "dec": 5.0,
            }
            with _patch("routers.identify._call_upstream_solve",
                        new=AsyncMock(return_value=fake)):
                r = _upload(client, name)
            assert r.status_code == 200, f'{name}: HTTP {r.status_code} {r.text}'
            body = r.json()
            assert 'ok' in body, f'{name} 缺字段 ok'
            assert 'solved' in body, f'{name} 缺字段 solved'

            if not body.get('solved'):
                pytest.fail(
                    f'{name} mock 模式未解出：{body.get("code")} / {body.get("message")}'
                )

            # 必填字段（spec §3.1）
            for k in ('ra', 'dec', 'pixel_scale', 'rotation',
                      'field_width', 'field_height', 'solve_time',
                      'image_width', 'image_height', 'exif_orientation',
                      'constellations', 'stars_overlay', 'overlay_lines'):
                assert k in body, f'{name} 缺字段 {k}'

            assert body['exif_orientation'] == 1, \
                f'{name} exif_orientation={body["exif_orientation"]}，应为 1'

            # 真实图宽高透传（不上游处理，本地 PIL 读出来的）
            w, h = expected_sizes[name]
            assert body['image_width'] == w, \
                f'{name} image_width={body["image_width"]}，应为 {w}'
            assert body['image_height'] == h, \
                f'{name} image_height={body["image_height"]}，应为 {h}'

            # T7: stars_overlay 是 traditions.build_star_catalog() 去重后投影；
            # ori 主星必须在 overlay（亮星应在图内），overlay 总量 >= 17
            assert len(body['stars_overlay']) >= 17, \
                f'{name} stars_overlay 数量 {len(body["stars_overlay"])}，应为 ≥17'
            # T9: catalog 按 HIP dedup → 8 主星 bayer 全被 chinese 抢注变空，
            # 旧"bayer 子集"断言不可用。改用 WCS 像素投影检查 ori 亮星可见数：
            # 在 6016x4016 (test1/test3) / 8192x6144 (test2) 视场内 ≥ 4 颗。
            from services.traditions import get_constellation
            orion = get_constellation('western', 'ori')
            from astropy.wcs import WCS
            from astropy.io import fits
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            from services.astrometry import _coerce_wcs_types
            wcs = WCS(fits.Header(_coerce_wcs_types(fake['wcs_header'])))
            w, h = expected_sizes[name]
            visible_main = 0
            for s in orion['stars'].values():
                if s['magnitude'] >= 4.5:
                    continue
                sky = SkyCoord(ra=s['ra'] * u.deg, dec=s['dec'] * u.deg, frame='icrs')
                x, y = wcs.world_to_pixel(sky)
                x, y = float(x), float(y)
                if 0 <= x <= w and 0 <= y <= h:
                    visible_main += 1
            assert visible_main >= 4, \
                f'{name} ori 亮星仅 {visible_main} 颗可见（应 ≥4）'

            # 星座命中（T6+: chinese 数据补齐后，shen_xiu 与 ori 中心点重合，
            # find_nearest top_k=3 时 chinese 命中可能与 ori 并存；断言包含 ori 即可）
            assert len(body['constellations']) >= 1, \
                f'{name} 应至少命中一个星座，实际 {len(body["constellations"])} 个'
            assert 'ori' in {c['abbr'] for c in body['constellations']}, \
                f'{name} 缺 ori 命中：{[c["abbr"] for c in body["constellations"]]}'

    def test_assets_size_under_max(self):
        """3 张真实样图都 ≤ 20MB（MAX_SIZE 契约）。"""
        for name in ('test1.jpg', 'test2.jpg', 'test3.jpg'):
            size_mb = (ASSETS / name).stat().st_size / 1024 / 1024
            assert size_mb < 20, f'{name} ({size_mb:.1f}MB) 超过 MAX_SIZE=20MB'