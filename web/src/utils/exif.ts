/**
 * Minimal EXIF Orientation reader (no dependencies).
 *
 * Only parses JPEG APP1 / TIFF IFD0 to extract the Orientation tag (0x0112).
 * - PNG / WebP / HEIC without TIFF EXIF segment → returns 1.
 * - Malformed EXIF → returns 1 (default to no rotation, fail safe).
 *
 * Browser <img> auto-applies EXIF Orientation when decoding, so the canvas
 * shows the rotated image but downstream solvers (e.g. astrometry.net) that
 * consume raw bytes work in raw coordinates. We send orientation to the
 * server so it can transform raw pixel coords → display coords before
 * handing them to the canvas.
 */
export async function readExifOrientation(file: File): Promise<number> {
  try {
    // 读前 256KB — 覆盖 JPEG APP1 EXIF 的全段大小（含 64KB+ 的大 EXIF、RAW、
    // 连拍堆栈等）。APP1 段最长 65535 字节（含 length 字段本身），高分辨率
    // 照片常满段；之前 64KB 切片 + 严格越界检查会让真实照片全部 fallback 到 1。
    const slice = file.slice(0, 256 * 1024)
    const buf = await slice.arrayBuffer()
    return parseExifOrientation(new Uint8Array(buf))
  } catch {
    return 1
  }
}

function parseExifOrientation(bytes: Uint8Array): number {
  // JPEG SOI
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return 1

  let offset = 2
  while (offset < bytes.length - 1) {
    if (bytes[offset] !== 0xff) return 1
    const marker = bytes[offset + 1]
    offset += 2

    if (marker === 0xd9 || marker === 0xda) return 1 // EOI / SOS

    if (marker === 0x00 || (marker >= 0xd0 && marker <= 0xd7)) continue

    const segLen = (bytes[offset] << 8) | bytes[offset + 1]
    if (segLen < 2) return 1 // malformed segment length
    // 段尾可能被切片截断：clamp 到切片边界而非放弃，让前部仍可解析
    // （orientation tag 几乎总在 TIFF 起始处附近）。
    const effectiveEnd = Math.min(offset + segLen, bytes.length)

    // APP1 (0xE1) with "Exif\0\0" identifier
    if (marker === 0xe1) {
      // "Exif\0\0" is 6 bytes; TIFF header follows
      if (
        offset + 8 < bytes.length &&
        bytes[offset + 2] === 0x45 && // E
        bytes[offset + 3] === 0x78 && // x
        bytes[offset + 4] === 0x69 && // i
        bytes[offset + 5] === 0x66 && // f
        bytes[offset + 6] === 0x00 &&
        bytes[offset + 7] === 0x00
      ) {
        const orient = parseTiffOrientation(bytes, offset + 8, effectiveEnd - (offset + 8))
        if (orient !== null) return orient
      }
    }

    offset = effectiveEnd
  }
  return 1
}

function parseTiffOrientation(
  bytes: Uint8Array,
  tiffStart: number,
  tiffLen: number,
): number | null {
  if (tiffLen < 8) return null
  const little = bytes[tiffStart] === 0x49 && bytes[tiffStart + 1] === 0x49
  const big = bytes[tiffStart] === 0x4d && bytes[tiffStart + 1] === 0x4d
  if (!little && !big) return null
  const read16 = (o: number): number =>
    little ? bytes[o] | (bytes[o + 1] << 8) : (bytes[o] << 8) | bytes[o + 1]
  const read32 = (o: number): number => {
    if (little) {
      return (
        (bytes[o] |
          (bytes[o + 1] << 8) |
          (bytes[o + 2] << 16) |
          (bytes[o + 3] << 24)) >>>
        0
      )
    }
    return (
      ((bytes[o] << 24) |
        (bytes[o + 1] << 16) |
        (bytes[o + 2] << 8) |
        bytes[o + 3]) >>>
      0
    )
  }

  // Magic 0x002A
  if (read16(tiffStart + 2) !== 0x002a) return null

  // IFD0 offset
  const ifdOffset = read32(tiffStart + 4)
  if (tiffStart + ifdOffset + 2 > bytes.length) return null

  const numEntries = read16(tiffStart + ifdOffset)
  for (let i = 0; i < numEntries; i++) {
    const entryOffset = tiffStart + ifdOffset + 2 + i * 12
    if (entryOffset + 12 > bytes.length) return null
    const tag = read16(entryOffset)
    if (tag === 0x0112) {
      // Orientation: SHORT (type=3), count=1, value in first 2 bytes of value field
      return read16(entryOffset + 8)
    }
  }
  return null
}
