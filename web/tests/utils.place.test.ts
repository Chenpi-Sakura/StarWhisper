import { describe, it, expect } from 'vitest'
import { nearestPlace, DEFAULT_MAX_KM } from '../src/utils/place'
import { FIXTURE_ROWS } from './fixtures/cityFile'

describe('nearestPlace', () => {
  it('resolves a district-level entry with its full province→city→district chain', () => {
    const hit = nearestPlace(FIXTURE_ROWS, 30.65, 104.08)
    expect(hit).not.toBeNull()
    expect(hit!.name).toBe('锦江区')
    expect(hit!.chain).toEqual(['四川省', '成都市', '锦江区'])
    expect(hit!.label).toBe('四川省成都市锦江区')
    expect(hit!.km).toBe(0)
  })

  it('only considers district rows (level 0), never province/city entries', () => {
    // 这组坐标正是夹具里地级市「成都市」的中心；若按层级过滤失效会返回「成都市」
    const hit = nearestPlace(FIXTURE_ROWS, 30.66, 104.06)
    expect(hit!.name).toBe('锦江区')
  })

  it('shortens the chain when the parent index is -1', () => {
    const hit = nearestPlace(FIXTURE_ROWS, 33.7, 105.7)
    expect(hit!.chain).toEqual(['成县'])
    expect(hit!.label).toBe('成县')
  })

  it('returns null beyond the max radius instead of guessing a far-away place', () => {
    // 承德一带（117.94E, 40.98N）离夹具里任何一个区县都远超 150km
    expect(nearestPlace(FIXTURE_ROWS, 40.98, 117.94)).toBeNull()
    // 海上 / 境外同理
    expect(nearestPlace(FIXTURE_ROWS, -10, 160)).toBeNull()
  })

  it('honours a custom max radius', () => {
    expect(nearestPlace(FIXTURE_ROWS, 30.75, 104.08, 5)).toBeNull()
    expect(nearestPlace(FIXTURE_ROWS, 30.75, 104.08, DEFAULT_MAX_KM)).not.toBeNull()
  })

  it('returns null for empty rows or out-of-range coordinates', () => {
    expect(nearestPlace([], 30.65, 104.08)).toBeNull()
    expect(nearestPlace(FIXTURE_ROWS, 91, 0)).toBeNull()
    expect(nearestPlace(FIXTURE_ROWS, 0, 181)).toBeNull()
    expect(nearestPlace(FIXTURE_ROWS, NaN, 104.08)).toBeNull()
  })

  it('never leaks coordinates into the result', () => {
    const hit = nearestPlace(FIXTURE_ROWS, 30.65, 104.08)!
    expect(Object.keys(hit).sort()).toEqual(['chain', 'km', 'label', 'name'])
  })
})
