"""生成「星空识别」页的样图快速测试素材（test1 / test2 两张）。

用途：识别页 idle 态展示两张真实星图缩略图，评审 / 测试者点一下即可完成一次
端到端识别，无需自己找星图。

为什么不在浏览器里现压：见 CLAUDE.md「公网 4MB 约束」——canvas / mozjpeg-wasm
与 native libjpeg 的像素差异会让 astrometry.net source extractor 拒绝长焦大图。
因此这里**直接复用服务端生产函数** ``services.jpeg_recompress.recompress_jpeg_to_target``
（同一 quality 阶梯 90→85→80、同一 target 4MB、同一 subsampling / optimize、
同样保留 EXIF），生成的文件与"用户上传原图经服务端重压后发给上游"的产物等价。

产物（均在 web/public/samples/，入库）：
- quick-test{1,2}.jpg          全尺寸样图（≤4MB，保留 EXIF 含 Orientation / FocalLength）
- quick-test{1,2}-thumb.jpg    列表缩略图（480px 宽，按 EXIF 转正，不用于解算）

运行：
    server/.venv/Scripts/python.exe scripts/prepare_quick_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "server"))

from services.jpeg_recompress import (  # noqa: E402
    DEFAULT_TARGET_BYTES,
    recompress_jpeg_to_target,
)

SOURCE_DIR = REPO_ROOT / "assets"
OUT_DIR = REPO_ROOT / "web" / "public" / "samples"
SAMPLES = ("test1", "test2")
THUMB_WIDTH = 480
THUMB_QUALITY = 72


def prepare(name: str) -> None:
    src = SOURCE_DIR / f"{name}.jpg"
    content = src.read_bytes()
    out_bytes, info = recompress_jpeg_to_target(content)

    full_path = OUT_DIR / f"quick-{name}.jpg"
    full_path.write_bytes(out_bytes)

    # 缩略图：按 EXIF 转正后等比缩放，只用于 UI 展示，不参与解算
    with Image.open(full_path) as im:
        upright = ImageOps.exif_transpose(im).convert("RGB")
        ratio = THUMB_WIDTH / upright.width
        thumb = upright.resize(
            (THUMB_WIDTH, max(1, round(upright.height * ratio))),
            Image.LANCZOS,
        )
        thumb_path = OUT_DIR / f"quick-{name}-thumb.jpg"
        thumb.save(thumb_path, format="JPEG", quality=THUMB_QUALITY, optimize=True)

    print(
        f"{name}: {len(content) / 1048576:.1f}MB -> "
        f"{len(out_bytes) / 1048576:.2f}MB (q{info.get('quality')}, "
        f"compressed={info.get('compressed')}) | thumb "
        f"{thumb_path.stat().st_size / 1024:.0f}KB {thumb.size[0]}x{thumb.size[1]}"
    )
    if len(out_bytes) > DEFAULT_TARGET_BYTES:
        raise SystemExit(f"{name} 重压后仍超过 4MB，不能用作样图")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in SAMPLES:
        prepare(name)


if __name__ == "__main__":
    main()
