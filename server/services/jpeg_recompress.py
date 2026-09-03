"""服务端 JPEG 自适应重压：满足公网上传 ≤ 4MB 约束（API.md §1 关键约束 1）。

为什么放在服务端（不放在前端）：
- Web 端 canvas Skia 与 @jsquash/jpeg mozjpeg-wasm 的 encoder 在 chrominance
  quantization / DCT 实现上与 native libjpeg 有微小像素差异，部分相机长焦
  + 大图（test1 D610 MPO 6016x4016、test2 8192x6144）即便 EXIF 完整保留，
  astrometry.net 的 source extractor 仍可能因像素细节差异而拒绝。
- 服务端是 native libjpeg（PIL backend），与 astrometry.net 同源；
  实测 q70-q95 全部能解 ra=92.9295，前端 canvas q80-q95 全部 SOLVE_FAILED。

关键约束（不可破坏，详见 API.md §1）：
- 不 resize：实测丢 81% 星点，解算变慢 30%，成功率下降
- 不丢 EXIF：FocalLength 决定服务端走 EXIF 路径还是 race，丢 2-3 倍慢
- 不降质量低于 q70：精度损 ~0.0001°，再低开始影响可靠性
- 不压缩 PNG/FITS：破坏像素数据，solve-field 会失败
"""
from __future__ import annotations

import io
import logging
import time

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


JPEG_MAGIC = b"\xff\xd8"
# 上限来自 docs/API.md §1 关键约束 1：公网 117.72.38.57:8010 ≤ 4MB 成功
DEFAULT_TARGET_BYTES = 4 * 1024 * 1024
# 自适应降级序列（不可低于 70，否则精度开始损失）
DEFAULT_QUALITY_STEPS: tuple[int, ...] = (90, 85, 80)
MIN_QUALITY = 70


def is_jpeg(content: bytes) -> bool:
    """快速检测 JPEG 魔数（FF D8）。

    替代 PIL.Image.format 检测（要解析整个文件头，慢）。
    """
    return len(content) >= 2 and content[:2] == JPEG_MAGIC


def recompress_jpeg_to_target(
    content: bytes,
    target_bytes: int = DEFAULT_TARGET_BYTES,
    quality_steps: tuple[int, ...] = DEFAULT_QUALITY_STEPS,
) -> tuple[bytes, dict]:
    """JPEG 自适应重压：按 quality_steps 降级重压，直到 ≤ target_bytes。

    返回 (new_bytes, info)：
    - new_bytes: 压缩后的 JPEG bytes；若不需要压缩则与入参同一对象
    - info: dict 含 compressed / quality / original_bytes / output_bytes /
      elapsed_ms / reason（仅当 not compressed）

    抛出：
    - ValueError: 不是有效 JPEG（魔数失败 / PIL 无法解析）
    - RuntimeError: 全部 quality 都失败仍超 target（极罕见，PNG 误判或图本身
      已接近 JPEG 上限的极端场景）

    不依赖 piexif：PIL 的 ``img.info.get('exif')`` 已经返回原始 EXIF bytes，
    写入时直接传 exif=... 即可完整保留（含 APP1 marker）。
    """
    if not is_jpeg(content):
        raise ValueError("not a JPEG (bad magic)")

    if len(content) <= target_bytes:
        return content, {
            "compressed": False,
            "quality": 100,
            "original_bytes": len(content),
            "output_bytes": len(content),
            "reason": "already_within_target",
        }

    t0 = time.perf_counter()
    try:
        img = Image.open(io.BytesIO(content))
        # 强制 load：MIME 标记的 JPEG 在 save 时若没 load 会抛 OSError
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"cannot decode JPEG: {e}") from e

    # 提取 EXIF bytes（如果有）—— PIL 在 save(..., exif=...) 时会原样插入 APP1
    exif_bytes = img.info.get("exif", b"")
    # MPO (multi-picture) / 罕见模式转 RGB，避免某些 save 路径拒收
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    last_bytes: bytes | None = None
    last_quality = quality_steps[0] if quality_steps else 90
    for q in quality_steps:
        if q < MIN_QUALITY:
            break
        buf = io.BytesIO()
        # subsampling=4:2:0 与 astrometry.net 默认一致（标准 JPEG chroma 子采样）
        # optimize=True 让 PIL 重排 Huffman，进一步缩体积
        img.save(
            buf,
            format="JPEG",
            quality=q,
            optimize=True,
            subsampling="4:2:0",
            exif=exif_bytes,
        )
        out = buf.getvalue()
        if len(out) <= target_bytes:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "JPEG 重压 %d → %d bytes (q%d, %.0fms)",
                len(content), len(out), q, elapsed_ms,
            )
            return out, {
                "compressed": True,
                "quality": q,
                "original_bytes": len(content),
                "output_bytes": len(out),
                "elapsed_ms": round(elapsed_ms, 1),
            }
        last_bytes = out
        last_quality = q

    elapsed_ms = (time.perf_counter() - t0) * 1000
    # 全部 quality 都失败 → 极罕见（PNG 误判或图本身已接近 JPEG 上限）
    # 兜底：仍返回最后一个 quality 的 bytes（不一定满足 target，但比原图小）
    # 上游可能仍能解（小图一般也能过公网 4MB 临界点）
    if last_bytes is not None and len(last_bytes) < len(content):
        logger.warning(
            "JPEG 重压到 q%d 仍 %d bytes（目标 %d），使用最后结果",
            last_quality, len(last_bytes), target_bytes,
        )
        return last_bytes, {
            "compressed": True,
            "quality": last_quality,
            "original_bytes": len(content),
            "output_bytes": len(last_bytes),
            "elapsed_ms": round(elapsed_ms, 1),
            "warning": "did_not_meet_target",
        }
    raise RuntimeError(
        f"JPEG 重压到 q{last_quality} 仍 {len(last_bytes) or len(content)} bytes"
        f"（目标 {target_bytes}），可能不是有效 JPEG"
    )
