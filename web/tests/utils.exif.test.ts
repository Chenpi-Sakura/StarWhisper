import { describe, it, expect } from 'vitest'
import { readExifOrientation } from '../src/utils/exif'

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

describe('readExifOrientation', () => {
  it('returns 1 for empty / non-JPEG input', async () => {
    const empty = new File([new Uint8Array([])], 'x.jpg', { type: 'image/jpeg' })
    expect(await readExifOrientation(empty)).toBe(1)
  })

  it('returns 1 for JPEG without EXIF segment', async () => {
    const f = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], 'x.jpg', { type: 'image/jpeg' })
    expect(await readExifOrientation(f)).toBe(1)
  })

  it.each([1, 3, 6, 8])('parses Orientation=%i', async (orient) => {
    const bytes = makeJpegWithOrientation(orient)
    const f = new File([bytes], 'x.jpg', { type: 'image/jpeg' })
    expect(await readExifOrientation(f)).toBe(orient)
  })

  it('returns 1 when EXIF segment is truncated', async () => {
    // Only SOI + APP1 marker + length header + partial "Exif" magic
    const f = new File(
      [new Uint8Array([0xff, 0xd8, 0xff, 0xe1, 0x10, 0x00, 0x45, 0x78])],
      'x.jpg',
      { type: 'image/jpeg' },
    )
    expect(await readExifOrientation(f)).toBe(1)
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
    const f = new File([out], 'big.jpg', { type: 'image/jpeg' })
    expect(await readExifOrientation(f)).toBe(orient)
  })
})
