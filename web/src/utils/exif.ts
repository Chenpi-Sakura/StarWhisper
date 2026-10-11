/**
 * Minimal EXIF reader (no dependencies).
 *
 * Parses the JPEG APP1 "Exif\0\0" segment and walks IFD0 / Exif sub-IFD /
 * GPS sub-IFD to collect what the app actually uses:
 * - Orientation (0x0112) — raw-pixel vs display coordinate transform
 * - DateTimeOriginal (0x9003) — season / clock context for the AI story
 * - GPS lat+lon (0x8825 → 0x0001..0x0004) — used only transiently to resolve a
 *   district-level place name client-side; raw coordinates never leave the
 *   browser (see utils/place.ts + stores/scan.ts).
 *
 * Every offset read is clamped to the segment bounds and any malformed input
 * yields the fail-safe `{ orientation: 1 }` — the historical behaviour the
 * solver depends on.
 */
export interface ExifMeta {
  /** EXIF Orientation 1–8; 1 = normalised, no rotation. */
  orientation: number
  /** Raw EXIF ASCII timestamp, e.g. `2025-03-14 22:40:11`. */
  dateTimeOriginal?: string
  /** Decimal degrees, signed (south / west negative). */
  lat?: number
  lon?: number
}

const TAG_ORIENTATION = 0x0112
const TAG_EXIF_IFD = 0x8769
const TAG_GPS_IFD = 0x8825
const TAG_DATE_TIME_ORIGINAL = 0x9003
const TAG_GPS_LAT_REF = 0x0001
const TAG_GPS_LAT = 0x0002
const TAG_GPS_LON_REF = 0x0003
const TAG_GPS_LON = 0x0004

/** TIFF type → byte size. Types outside this map are skipped. */
const TYPE_SIZE: Record<number, number> = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8 }

/** APP1 段最长 65535 字节，真实照片常满段；256KB 切片覆盖全部 EXIF 头部。 */
const EXIF_SLICE_BYTES = 256 * 1024

export async function readExifMeta(file: File): Promise<ExifMeta> {
  try {
    const buf = await file.slice(0, EXIF_SLICE_BYTES).arrayBuffer()
    return parseExifMeta(new Uint8Array(buf))
  } catch {
    return { orientation: 1 }
  }
}

interface TiffView {
  bytes: Uint8Array
  /** Absolute TIFF start / exclusive end within `bytes`. */
  start: number
  end: number
  u16: (abs: number) => number
  u32: (abs: number) => number
}

function makeView(bytes: Uint8Array, start: number, end: number, little: boolean): TiffView {
  return {
    bytes,
    start,
    end,
    u16: (abs) =>
      little ? bytes[abs] | (bytes[abs + 1] << 8) : (bytes[abs] << 8) | bytes[abs + 1],
    u32: (abs) =>
      little
        ? (bytes[abs] | (bytes[abs + 1] << 8) | (bytes[abs + 2] << 16) | (bytes[abs + 3] << 24)) >>> 0
        : ((bytes[abs] << 24) | (bytes[abs + 1] << 16) | (bytes[abs + 2] << 8) | bytes[abs + 3]) >>> 0,
  }
}

/**
 * Visit every entry of the IFD at TIFF-relative `ifdOffset`.
 * Callback receives the tag id plus a reader bound to that entry's value field.
 */
function walkIfd(
  v: TiffView,
  ifdOffset: number,
  onEntry: (tag: number, type: number, count: number, valueField: number) => void,
): void {
  const countAt = v.start + ifdOffset
  if (ifdOffset < 0 || countAt + 2 > v.end) return
  const count = v.u16(countAt)
  for (let i = 0; i < count; i++) {
    const entry = countAt + 2 + i * 12
    if (entry + 12 > v.end) return
    const tag = v.u16(entry)
    const type = v.u16(entry + 2)
    const num = v.u32(entry + 4)
    if (!(type in TYPE_SIZE)) continue
    onEntry(tag, type, num, entry + 8)
  }
}

/** Byte offset (absolute) where a tag's payload lives: inline when it fits 4 bytes. */
function valueOffset(v: TiffView, type: number, count: number, valueField: number): number | null {
  const size = TYPE_SIZE[type] * count
  if (size <= 4) return valueField
  const off = v.u32(valueField)
  const abs = v.start + off
  return off + size > v.end - v.start ? null : abs
}

function readAscii(v: TiffView, type: number, count: number, valueField: number): string | undefined {
  if (type !== 2 || count < 2) return undefined
  const abs = valueOffset(v, type, count, valueField)
  if (abs === null) return undefined
  let out = ''
  for (let i = 0; i < count - 1 && abs + i < v.end; i++) {
    const c = v.bytes[abs + i]
    if (c === 0) break
    out += String.fromCharCode(c)
  }
  return out.length ? out : undefined
}

function readRationals(v: TiffView, count: number, valueField: number): number[] | undefined {
  const abs = valueOffset(v, 5, count, valueField)
  if (abs === null) return undefined
  const out: number[] = []
  for (let i = 0; i < count; i++) {
    const den = v.u32(abs + i * 8 + 4)
    if (den === 0) return undefined
    out.push(v.u32(abs + i * 8) / den)
  }
  return out
}

function readShort(v: TiffView, valueField: number): number {
  return v.u16(valueField)
}

function readLong(v: TiffView, valueField: number): number {
  return v.u32(valueField)
}

/** EXIF GPS DMS (`[deg, min, sec]` as rationals) + N/S/E/W ref → signed decimal degrees. */
export function dmsToDecimal(dms: number[], ref: string): number | undefined {
  if (dms.length < 3 || !Number.isFinite(dms[0]) || !Number.isFinite(dms[1]) || !Number.isFinite(dms[2])) {
    return undefined
  }
  const deg = dms[0] + dms[1] / 60 + dms[2] / 3600
  if (deg > 180) return undefined
  const r = ref.toUpperCase()
  if (r !== 'N' && r !== 'S' && r !== 'E' && r !== 'W') return undefined
  return r === 'S' || r === 'W' ? -deg : deg
}

function parseTiffMeta(bytes: Uint8Array, start: number, end: number): ExifMeta {
  if (end - start < 8) return { orientation: 1 }
  const b0 = bytes[start]
  const b1 = bytes[start + 1]
  const little = b0 === 0x49 && b1 === 0x49
  const big = b0 === 0x4d && b1 === 0x4d
  if (!little && !big) return { orientation: 1 }
  const v = makeView(bytes, start, end, little)
  if (v.u16(start + 2) !== 0x002a) return { orientation: 1 }

  const meta: ExifMeta = { orientation: 1 }
  let exifIfd = -1
  let gpsIfd = -1
  let ifd0DateTime: string | undefined

  walkIfd(v, v.u32(start + 4), (tag, type, count, valueField) => {
    if (tag === TAG_ORIENTATION) meta.orientation = readShort(v, valueField) || 1
    else if (tag === TAG_EXIF_IFD && type === 4) exifIfd = readLong(v, valueField)
    else if (tag === TAG_GPS_IFD && type === 4) gpsIfd = readLong(v, valueField)
    else if (tag === 0x0132) ifd0DateTime = readAscii(v, type, count, valueField) // DateTime
  })

  // DateTimeOriginal (0x9003) lives in the Exif sub-IFD, not IFD0.
  if (exifIfd >= 0) {
    walkIfd(v, exifIfd, (tag, type, count, valueField) => {
      if (tag === TAG_DATE_TIME_ORIGINAL) meta.dateTimeOriginal = readAscii(v, type, count, valueField)
    })
  }
  if (!meta.dateTimeOriginal) meta.dateTimeOriginal = ifd0DateTime

  if (gpsIfd >= 0) {
    let latRef = ''
    let lonRef = ''
    let latDms: number[] | undefined
    let lonDms: number[] | undefined
    walkIfd(v, gpsIfd, (tag, type, count, valueField) => {
      if (tag === TAG_GPS_LAT_REF) latRef = readAscii(v, type, count, valueField) ?? ''
      else if (tag === TAG_GPS_LON_REF) lonRef = readAscii(v, type, count, valueField) ?? ''
      else if (tag === TAG_GPS_LAT && type === 5) latDms = readRationals(v, count, valueField)
      else if (tag === TAG_GPS_LON && type === 5) lonDms = readRationals(v, count, valueField)
    })
    if (latDms && latRef) meta.lat = dmsToDecimal(latDms, latRef)
    if (lonDms && lonRef) meta.lon = dmsToDecimal(lonDms, lonRef)
  }

  if (meta.lat !== undefined && (meta.lat < -90 || meta.lat > 90)) delete meta.lat
  if (meta.lon !== undefined && (meta.lon < -180 || meta.lon > 180)) delete meta.lon
  return meta
}

function parseExifMeta(bytes: Uint8Array): ExifMeta {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return { orientation: 1 }

  let offset = 2
  while (offset < bytes.length - 1) {
    if (bytes[offset] !== 0xff) return { orientation: 1 }
    const marker = bytes[offset + 1]
    offset += 2

    if (marker === 0xd9 || marker === 0xda) return { orientation: 1 } // EOI / SOS
    if (marker === 0x00 || (marker >= 0xd0 && marker <= 0xd7)) continue

    const segLen = (bytes[offset] << 8) | bytes[offset + 1]
    if (segLen < 2) return { orientation: 1 }
    // 段尾可能被切片截断：clamp 到切片边界而非放弃（orientation 几乎总在 TIFF 起始处附近）
    const segEnd = Math.min(offset + segLen, bytes.length)

    if (
      marker === 0xe1 &&
      segEnd - offset > 8 &&
      bytes[offset + 2] === 0x45 && // E
      bytes[offset + 3] === 0x78 && // x
      bytes[offset + 4] === 0x69 && // i
      bytes[offset + 5] === 0x66 && // f
      bytes[offset + 6] === 0x00 &&
      bytes[offset + 7] === 0x00
    ) {
      return parseTiffMeta(bytes, offset + 8, segEnd)
    }

    offset = segEnd
  }
  return { orientation: 1 }
}
