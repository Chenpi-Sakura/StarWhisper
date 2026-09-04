"""server/services/jpeg_recompress.py 单测。

覆盖：
- 魔数检测：JPEG 通过 / 非 JPEG 拒绝 / 截断拒绝
- passthrough：≤ 4MB 原样返回 + reason 字段
- 自适应降级：5MB → q90 → 4MB OK；q90 还超 → 降级 q85
- q70 硬下限：quality_steps 含 60 直接 break
- EXIF 保留：构造带 EXIF 的 JPEG，重压后 head 仍能 parse 出 Orientation
- PNG 不动（PNG 不进本函数，但 is_jpeg 检测要正确）
- 兜底：q90/q85/q80 都还超 → 返回 last_bytes + warning 字段
- 解码失败：垃圾 bytes 抛 ValueError
"""
from __future__ import annotations

import io
import os

import piexif
from PIL import Image

from services.jpeg_recompress import (
    DEFAULT_QUALITY_STEPS,
    DEFAULT_TARGET_BYTES,
    MIN_QUALITY,
    is_jpeg,
    recompress_jpeg_to_target,
)


def _make_high_entropy_jpeg(width: int, height: int, quality: int = 95) -> bytes:
    """构造一张高熵 JPEG（接近不可压缩），用于触发 > 4MB 路径。

    真实星空照片 vs 渐变色：JPEG 对渐变压缩率极高（50:1），
    对随机噪声只能压到 2-3:1。要让 JPEG 真实超过 4MB 必须用高熵像素。
    """
    raw = os.urandom(width * height * 3)
    img = Image.frombytes("RGB", (width, height), raw)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _make_solid_jpeg(width: int, height: int, quality: int = 95) -> bytes:
    """构造一张渐变 JPEG（保留供小图测试用）。"""
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _make_jpeg_with_exif(width: int = 100, height: int = 100) -> bytes:
    """构造带 EXIF (Orientation=6) 的 JPEG，方便断言 EXIF 保留。"""
    img = Image.new("RGB", (width, height), color=(50, 100, 150))
    # piexif 只接受 Orientation (1-8) + dict 结构
    zeroth = {piexif.ImageIFD.Orientation: 6}
    exif_dict = {"0th": zeroth, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, exif=exif_bytes)
    return buf.getvalue()


def test_is_jpeg_accepts_real_jpeg():
    assert is_jpeg(b"\xff\xd8\xff\xe0...") is True


def test_is_jpeg_rejects_png():
    assert is_jpeg(b"\x89PNG\r\n\x1a\n") is False


def test_is_jpeg_rejects_truncated():
    # 长度 < 2 视为 truncated
    assert is_jpeg(b"") is False
    assert is_jpeg(b"\xff") is False  # 1 字节
    # 完整 2 字节魔数 = valid（即使后面是垃圾，也叫 valid magic）
    assert is_jpeg(b"\xff\xd8") is True
    assert is_jpeg(b"\xff\xd8\x00\x00") is True


def test_passthrough_when_within_target():
    """≤ 4MB 的小图直接原样返回，compressed=False。"""
    small = _make_solid_jpeg(100, 100)  # 远小于 4MB
    assert len(small) <= DEFAULT_TARGET_BYTES
    out, info = recompress_jpeg_to_target(small)
    assert out is small  # 同一对象引用
    assert info["compressed"] is False
    assert info["quality"] == 100
    assert info["original_bytes"] == len(small)
    assert info["reason"] == "already_within_target"


def test_compresses_oversize_jpeg_to_target():
    """> 4MB 的图压到 ≤ 4MB。验证：

    - 确实压缩了
    - quality 在 [70, 80] 范围（高熵图 q90 不够，必须降级）
    - 输出 ≤ target
    - 输出仍是有效 JPEG
    """
    # 构造一张 > 4MB 的高熵 JPEG（3000x2000 随机像素 q95 ≈ 7MB）
    big = _make_high_entropy_jpeg(3000, 2000, quality=95)
    assert len(big) > DEFAULT_TARGET_BYTES, f"测试图太小：{len(big)}"
    out, info = recompress_jpeg_to_target(big)
    assert info["compressed"] is True
    # 高熵图 q90 仍可能 > 4MB（实测 ≈ 4.9MB），必然降级
    assert info["quality"] in (85, 80)
    assert info["quality"] >= MIN_QUALITY
    assert len(out) <= DEFAULT_TARGET_BYTES
    # 输出仍是有效 JPEG
    assert is_jpeg(out)
    # 输出能被 PIL 重新解码
    Image.open(io.BytesIO(out)).load()


def test_falls_back_to_q85_when_q90_too_big():
    """q90 还超 target → 降级到 q85。"""
    # 构造 ~6MB 图
    huge = _make_high_entropy_jpeg(3500, 2500, quality=95)
    assert len(huge) > DEFAULT_TARGET_BYTES
    # 用 3MB 目标强制 q90 失败
    out, info = recompress_jpeg_to_target(huge, target_bytes=3 * 1024 * 1024)
    assert info["compressed"] is True
    assert info["quality"] in (85, 80)  # 至少降了一级


def test_honors_min_quality_floor():
    """quality_steps 含 < 70 的项会被 break（不可低于 q70 精度保证）。"""
    big = _make_solid_jpeg(3000, 2000, quality=95)
    out, info = recompress_jpeg_to_target(
        big, target_bytes=1, quality_steps=(90, 60, 30),
    )
    # 60 被 break，没尝试；最大压缩的就是 q90
    assert info["quality"] == 90


def test_preserves_exif_segment():
    """重压后 EXIF（含 APP1 marker 0xFF 0xE1）必须保留，Orientation=6 不变。

    这是 spec 关键约束：FocalLength 决定服务端走 EXIF 路径还是 race，
    丢 EXIF 会让解算慢 2-3 倍甚至失败。
    """
    # 用高熵 3000x2000 构造一张 > 4MB 且带 EXIF 的图
    raw = os.urandom(3000 * 2000 * 3)
    img = Image.frombytes("RGB", (3000, 2000), raw)
    zeroth = {piexif.ImageIFD.Orientation: 6}
    exif_bytes = piexif.dump({"0th": zeroth, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None})
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, exif=exif_bytes)
    big = buf.getvalue()
    assert len(big) > DEFAULT_TARGET_BYTES
    out, info = recompress_jpeg_to_target(big)
    assert info["compressed"] is True

    # 1. SOI 必须在头
    assert out[0] == 0xFF
    assert out[1] == 0xD8  # SOI
    # 2. 扫描第一个 APP1 marker (PIL 在 APP0/JFIF 之后才放 APP1/EXIF)
    app1_offset = None
    for i in range(2, min(len(out) - 1, 256)):
        if out[i] == 0xFF and out[i + 1] == 0xE1:
            app1_offset = i
            break
    assert app1_offset is not None, "APP1 marker not found"
    # 3. APP1 length + "Exif\0\0" 紧随其后
    app1_len = (out[app1_offset + 2] << 8) | out[app1_offset + 3]
    assert app1_len > 0
    assert out[app1_offset + 4:app1_offset + 10] == b"Exif\x00\x00"
    # 4. 重新 parse EXIF 能读回 Orientation=6
    parsed = piexif.load(out)
    assert parsed["0th"].get(piexif.ImageIFD.Orientation) == 6


def test_rejects_non_jpeg():
    """非 JPEG bytes 抛 ValueError（PNG、GIF、垃圾数据）。"""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with __import__("pytest").raises(ValueError, match="not a JPEG"):
        recompress_jpeg_to_target(png_bytes)


def test_rejects_corrupt_jpeg():
    """JPEG 魔数 OK 但内容损坏 → ValueError（cannot decode）。

    PIL 对裸的 0xFF 0xD8 0x00 ... 实际上**会**抛 UnidentifiedImageError
    （它需要 SOS marker 才能识别为 JPEG）。本测试覆盖两个 corruption case。

    注意：必须传 target_bytes=1，否则 2 字节 magic 走 passthrough 路径。
    """
    # 仅 2 字节 magic：PIL 无法识别（缺 SOS marker）
    with __import__("pytest").raises(ValueError, match="cannot decode"):
        recompress_jpeg_to_target(b"\xff\xd8", target_bytes=1)
    # magic + 一个额外字节，仍然缺 SOS marker
    with __import__("pytest").raises(ValueError, match="cannot decode"):
        recompress_jpeg_to_target(b"\xff\xd8\xff", target_bytes=1)


def test_warning_when_all_qualities_still_too_big():
    """q90/q85/q80 都还超 target → 返回 last_bytes + warning 字段。

    极端 case：用 1 byte 目标，任何 JPEG 都压不到。
    """
    big = _make_high_entropy_jpeg(2500, 1800, quality=95)
    assert len(big) > DEFAULT_TARGET_BYTES
    out, info = recompress_jpeg_to_target(
        big, target_bytes=1, quality_steps=(90, 85, 80),
    )
    assert info["compressed"] is True
    assert info["quality"] == 80  # 最后尝试的
    assert info["warning"] == "did_not_meet_target"
    # last_bytes 至少比原图小
    assert len(out) < len(big)


def test_default_quality_steps_match_spec():
    """锁定 API.md §1 表里的 [90, 85, 80] 默认序列，防止无意改坏 spec 行为。"""
    assert DEFAULT_QUALITY_STEPS == (90, 85, 80)
    assert MIN_QUALITY == 70
    assert DEFAULT_TARGET_BYTES == 4 * 1024 * 1024
