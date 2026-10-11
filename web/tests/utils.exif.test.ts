import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { readExifMeta, dmsToDecimal } from '../src/utils/exif'

/**
 * Build a minimal JPEG with an APP1 EXIF segment carrying an Orientation tag.
 * - bytes[0..1] = FF D8 (SOI)
 * - FF E1 <lenHi> <lenLo> "Exif\0\0" <tiffHeader>
 * - TIFF header: "II" 2A 00 <ifd0Offset LE32>
 * - IFD0: <count LE16> + entries (12 bytes each)
 * - Orientation entry: tag 0x0112, type 3 (SHORT), count 1, value (LE16)
 */
function makeJpegWithOrientation(orientation: number): Uint8Array {
  const tiff =
    // "II" + magic + IFD0 offset (IFD0 starts at offset 8)
    new Uint8Array([
      0x49, 0x49,             // little endian
      0x2a, 0x00,             // magic
      0x08, 0x00, 0x00, 0x00, // IFD0 offset = 8
      // IFD0: count = 1
      0x01, 0x00,
      // Entry: Orientation
      0x12, 0x01,             // tag 0x0112
      0x03, 0x00,             // type SHORT
      0x01, 0x00, 0x00, 0x00, // count = 1
      orientation & 0xff, (orientation >> 8) & 0xff, 0x00, 0x00,
      // next IFD offset = 0
      0x00, 0x00, 0x00, 0x00,
    ])
  const exifPayload = new Uint8Array(6 + tiff.length)
  exifPayload.set([0x45, 0x78, 0x69, 0x66, 0x00, 0x00], 0) // "Exif\0\0"
  exifPayload.set(tiff, 6)

  // APP1 length includes its 2 length bytes but NOT the marker bytes
  const segLen = exifPayload.length + 2
  // layout: SOI(2) + APP1 marker(2) + length(2) + exifPayload(N) = N+6
  const out = new Uint8Array(exifPayload.length + 6)
  out.set([0xff, 0xd8, 0xff, 0xe1], 0) // SOI + APP1 marker
  out[4] = (segLen >> 8) & 0xff
  out[5] = segLen & 0xff
  out.set(exifPayload, 6)
  return out
}

function jpegFile(bytes: Uint8Array, name = 'x.jpg'): File {
  return new File([bytes], name, { type: 'image/jpeg' })
}

/**
 * 真实 EXIF 样本（orientation=6、DateTimeOriginal=2025:03:14 22:40:11、
 * GPS 30.6N/114.3E），由 piexif 写入；重生成命令见文件末尾注释。
 */
const REAL_EXIF_JPEG = new Uint8Array(
  readFileSync(resolve(__dirname, 'fixtures', 'exif_sample.jpg')),
)

describe('readExifMeta · orientation', () => {
  it('returns 1 for empty input', async () => {
    expect((await readExifMeta(jpegFile(new Uint8Array([])))).orientation).toBe(1)
  })

  it('returns 1 for non-JPEG input', async () => {
    expect((await readExifMeta(jpegFile(new Uint8Array([0x89, 0x50, 0x4e, 0x47])))).orientation).toBe(1)
  })

  it('returns 1 for JPEG without EXIF segment', async () => {
    const f = jpegFile(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]))
    expect((await readExifMeta(f)).orientation).toBe(1)
  })

  it.each([1, 3, 6, 8])('parses Orientation=%i', async (orient) => {
    const f = jpegFile(makeJpegWithOrientation(orient))
    expect((await readExifMeta(f)).orientation).toBe(orient)
  })

  it('returns 1 when EXIF segment is truncated', async () => {
    // Only SOI + APP1 marker + length header + partial "Exif" magic
    const f = jpegFile(new Uint8Array([0xff, 0xd8, 0xff, 0xe1, 0x10, 0x00, 0x45, 0x78]))
    expect((await readExifMeta(f)).orientation).toBe(1)
  })

  it('parses Orientation from a full-size (~64KB) APP1 EXIF segment', async () => {
    // Regression: a real EXIF APP1 segment can fill its 65535-byte slot.
    // The previous 64KB slice + strict `offset + segLen > bytes.length` bail-out
    // returned 1 for these files (causing server to receive orientation=1 and
    // return raw pixel coordinates that mismatched the EXIF-rotated <img>).
    const orient = 8
    const tiff = new Uint8Array([
      0x49, 0x49,             // little endian
      0x2a, 0x00,             // magic
      0x08, 0x00, 0x00, 0x00, // IFD0 offset = 8
      0x01, 0x00,             // count = 1
      // Orientation entry
      0x12, 0x01, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00,
      orient & 0xff, (orient >> 8) & 0xff, 0x00, 0x00,
      0x00, 0x00, 0x00, 0x00, // next IFD offset = 0
    ])
    const exifPayload = new Uint8Array(6 + tiff.length)
    exifPayload.set([0x45, 0x78, 0x69, 0x66, 0x00, 0x00], 0)
    exifPayload.set(tiff, 6)
    // Pad to a near-max APP1 segment: segLen ≈ 65534
    const targetPayloadLen = 65534 - 2 // segLen includes its 2 length bytes
    const padded = new Uint8Array(targetPayloadLen)
    padded.set(exifPayload, 0)
    const segLen = padded.length + 2
    const out = new Uint8Array(padded.length + 6)
    out.set([0xff, 0xd8, 0xff, 0xe1], 0)
    out[4] = (segLen >> 8) & 0xff
    out[5] = segLen & 0xff
    out.set(padded, 6)
    expect((await readExifMeta(jpegFile(out, 'big.jpg'))).orientation).toBe(orient)
  })
})

describe('readExifMeta · DateTimeOriginal + GPS', () => {
  it('reads timestamp and coordinates from a real EXIF block', async () => {
    const meta = await readExifMeta(jpegFile(REAL_EXIF_JPEG, 'exif_sample.jpg'))
    expect(meta.orientation).toBe(6)
    // 原样返回 EXIF ASCII（日期用冒号分隔）；归一化是 formatExifDateTime 的职责
    expect(meta.dateTimeOriginal).toBe('2025:03:14 22:40:11')
    expect(meta.lat).toBeCloseTo(30.6, 4)
    expect(meta.lon).toBeCloseTo(114.3, 4)
  })

  it('leaves date and coords undefined when EXIF only carries orientation', async () => {
    const meta = await readExifMeta(jpegFile(makeJpegWithOrientation(3)))
    expect(meta.orientation).toBe(3)
    expect(meta.dateTimeOriginal).toBeUndefined()
    expect(meta.lat).toBeUndefined()
    expect(meta.lon).toBeUndefined()
  })
})

describe('dmsToDecimal', () => {
  it('converts DMS + N/E refs to positive decimals', () => {
    expect(dmsToDecimal([30, 36, 0], 'N')).toBeCloseTo(30.6, 6)
    expect(dmsToDecimal([114, 18, 0], 'E')).toBeCloseTo(114.3, 6)
  })

  it('negates for S / W refs', () => {
    expect(dmsToDecimal([33, 52, 0], 'S')).toBeCloseTo(-33.8667, 3)
    expect(dmsToDecimal([70, 30, 0], 'W')).toBeCloseTo(-70.5, 6)
  })

  it('rejects unknown refs, missing components and out-of-range degrees', () => {
    expect(dmsToDecimal([30, 36, 0], 'X')).toBeUndefined()
    expect(dmsToDecimal([30, 36], 'N')).toBeUndefined()
    expect(dmsToDecimal([200, 0, 0], 'N')).toBeUndefined()
  })

  it('rejects NaN components', () => {
    expect(dmsToDecimal([30, NaN, 0], 'N')).toBeUndefined()
  })
})

/*
 * fixtures/exif_sample.jpg 重生成（需 piexif，server/.venv 已装）：
 *
 *   from PIL import Image
 *   import io, piexif
 *   buf = io.BytesIO()
 *   Image.new("RGB", (16, 16), (8, 12, 40)).save(buf, "JPEG", quality=90)
 *   open("_tmp.jpg", "wb").write(buf.getvalue())
 *   exif = {
 *     "0th": {piexif.ImageIFD.Orientation: 6},
 *     "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2025:03:14 22:40:11"},
 *     "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N",
 *             piexif.GPSIFD.GPSLatitude: [(30, 1), (36, 1), (0, 1)],
 *             piexif.GPSIFD.GPSLongitudeRef: b"E",
 *             piexif.GPSIFD.GPSLongitude: [(114, 1), (18, 1), (0, 1)]},
 *     "1st": {}, "thumbnail": None,
 *   }
 *   piexif.insert(piexif.dump(exif), "_tmp.jpg", "web/tests/fixtures/exif_sample.jpg")
 */
