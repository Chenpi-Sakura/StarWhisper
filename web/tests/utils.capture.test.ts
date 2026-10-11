import { describe, it, expect } from 'vitest'
import { formatExifDateTime, buildCapture } from '../src/utils/capture'
import { FIXTURE_ROWS } from './fixtures/cityFile'

describe('formatExifDateTime', () => {
  it('normalises the EXIF colon date form and drops seconds', () => {
    expect(formatExifDateTime('2025:03:14 22:40:11')).toBe('2025-03-14 22:40')
  })

  it('accepts ISO-ish separators and the T form', () => {
    expect(formatExifDateTime('2025-03-14T22:40:11')).toBe('2025-03-14 22:40')
    expect(formatExifDateTime('  2025:03:14 22:40:11  ')).toBe('2025-03-14 22:40')
  })

  it('returns undefined for missing or malformed input', () => {
    expect(formatExifDateTime(undefined)).toBeUndefined()
    expect(formatExifDateTime('')).toBeUndefined()
    expect(formatExifDateTime('昨天傍晚')).toBeUndefined()
    expect(formatExifDateTime('2025:03:14')).toBeUndefined()
  })

  it('rejects impossible calendar values instead of passing them through', () => {
    expect(formatExifDateTime('2025:13:40 22:40:11')).toBeUndefined() // 月 13
    expect(formatExifDateTime('2025:03:00 22:40:11')).toBeUndefined() // 日 0
    expect(formatExifDateTime('2025:03:14 25:40:11')).toBeUndefined() // 时 25
    expect(formatExifDateTime('2025:03:14 22:99:11')).toBeUndefined() // 分 99
  })
})

describe('buildCapture', () => {
  it('carries the normalised timestamp', () => {
    expect(buildCapture({ orientation: 1, dateTimeOriginal: '2025:03:14 22:40:11' }, []))
      .toEqual({ captured_at: '2025-03-14 22:40' })
  })

  it('resolves place only when coordinates are present', () => {
    const withGps = buildCapture({ orientation: 1, lat: 30.65, lon: 104.08 }, FIXTURE_ROWS)
    expect(withGps.place).toBe('四川省成都市锦江区')
    const noGps = buildCapture({ orientation: 1, dateTimeOriginal: '2025:03:14 22:40:11' }, FIXTURE_ROWS)
    expect(noGps.place).toBeUndefined()
  })

  it('skips the place when city rows were never loaded', () => {
    const c = buildCapture({ orientation: 1, lat: 30.65, lon: 104.08 }, [])
    expect(c.place).toBeUndefined()
  })

  it('returns an empty object for a photo with no usable EXIF', () => {
    expect(buildCapture({ orientation: 1 }, FIXTURE_ROWS)).toEqual({})
  })

  it('never emits raw coordinates (privacy invariant for the story prompt)', () => {
    const c = buildCapture(
      { orientation: 6, dateTimeOriginal: '2025:03:14 22:40:11', lat: 30.65, lon: 104.08 },
      FIXTURE_ROWS,
    )
    expect(Object.keys(c).sort()).toEqual(['captured_at', 'place'])
    expect(JSON.stringify(c)).not.toMatch(/30\.65|104\.08/)
  })
})
