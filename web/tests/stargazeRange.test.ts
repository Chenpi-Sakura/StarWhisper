import { describe, expect, it } from 'vitest'

import {
  applyRangePatch,
  currentHourOffset,
  dateHourFromOffset,
  daysBetweenIso,
  formatHourOffset,
  formatSpan,
  hourOffsetFromToday,
  isoPlusDays,
  resolveRange,
  todayIso,
  toLocalIso,
  type RangeSelection,
} from '../src/utils/stargazeRange'

const TODAY = '2026-09-10'

function sel(over: Partial<RangeSelection> = {}): RangeSelection {
  return {
    startDate: TODAY,
    startHour: 14,
    endDate: TODAY,
    endHour: 13,
    ...over,
  }
}

describe('stargazeRange 工具', () => {
  it('toLocalIso / todayIso 用本地日期而非 UTC', () => {
    expect(toLocalIso(new Date(2026, 8, 10, 23, 30))).toBe('2026-09-10')
    expect(toLocalIso(new Date(2026, 8, 10, 0, 5))).toBe('2026-09-10')
    expect(todayIso(new Date(2026, 0, 2, 3, 0))).toBe('2026-01-02')
  })

  it('currentHourOffset 取当前整点（默认区间起点 = 此刻，而非 0 点）', () => {
    expect(currentHourOffset(new Date(2026, 8, 10, 0, 0))).toBe(0)
    expect(currentHourOffset(new Date(2026, 8, 10, 14, 37))).toBe(14)
    expect(currentHourOffset(new Date(2026, 8, 10, 23, 59))).toBe(23)
  })

  it('isoPlusDays / daysBetweenIso 跨月正确', () => {
    expect(isoPlusDays('2026-09-28', 6)).toBe('2026-10-04')
    expect(daysBetweenIso('2026-09-28', '2026-10-04')).toBe(6)
    expect(daysBetweenIso('2026-09-10', '2026-09-10')).toBe(0)
  })

  it('hourOffsetFromToday / dateHourFromOffset 互为逆变换', () => {
    expect(hourOffsetFromToday('2026-09-10', 14, TODAY)).toBe(14)
    expect(hourOffsetFromToday('2026-09-11', 13, TODAY)).toBe(37)
    expect(dateHourFromOffset(37, TODAY)).toEqual({
      date: '2026-09-11',
      hour: 13,
    })
    expect(dateHourFromOffset(0, TODAY)).toEqual({ date: '2026-09-10', hour: 0 })
  })

  it('resolveRange：此刻起 24 小时 → startHour=14, hours=24（含首尾）', () => {
    expect(resolveRange(sel({ endDate: '2026-09-11', endHour: 13 }), TODAY)).toEqual({
      startHour: 14,
      hours: 24,
    })
  })

  it('resolveRange：终点早于起点收敛为 1 小时；越界 clamp 到 7 天窗口', () => {
    expect(resolveRange(sel({ endHour: 9 }), TODAY)).toEqual({ startHour: 14, hours: 1 })
    expect(resolveRange(sel({ startDate: '2026-09-20', startHour: 5 }), TODAY)).toEqual({
      startHour: 167,
      hours: 1,
    })
  })

  it('applyRangePatch：只动起点时保持原时长整体平移', () => {
    const current = sel({ endDate: '2026-09-11', endHour: 13 }) // 14 → 37（24h）
    const got = applyRangePatch(
      current,
      { startDate: '2026-09-11', startHour: 8 },
      TODAY,
    )
    expect(got).toEqual({ startHour: 32, hours: 24 }) // 09-11 08:00 → 09-12 07:00
  })

  it('applyRangePatch：起点平移越界时右端 clamp 到窗口末尾', () => {
    const current = sel({ endDate: '2026-09-11', endHour: 13 })
    const got = applyRangePatch(
      current,
      { startDate: '2026-09-16', startHour: 20 },
      TODAY,
    )
    // 起点 = 6*24+20 = 164 → 时长被压到 168-164 = 4 小时
    expect(got).toEqual({ startHour: 164, hours: 4 })
  })

  it('applyRangePatch：只动终点时保持起点', () => {
    const current = sel({ endHour: 13 })
    const got = applyRangePatch(current, { endHour: 21 }, TODAY)
    expect(got).toEqual({ startHour: 14, hours: 8 })
  })

  it('applyRangePatch：支持小时粒度（1-168 任意长度）', () => {
    const current = sel()
    const got = applyRangePatch(current, { endHour: 16 }, TODAY)
    expect(got).toEqual({ startHour: 14, hours: 3 }) // 14:00 / 15:00 / 16:00
  })

  it('formatHourOffset 给出中文日期提示（跨年补年份）', () => {
    expect(formatHourOffset(14, TODAY)).toBe('今天 14:00')
    expect(formatHourOffset(24, TODAY)).toBe('明天 00:00')
    expect(formatHourOffset(48, TODAY)).toBe('后天 00:00')
    expect(formatHourOffset(120, TODAY)).toBe('09/15 00:00')
    expect(formatHourOffset(120, '2026-12-30')).toBe('2027/01/04 00:00')
  })

  it('formatSpan：同日只给时刻', () => {
    expect(formatSpan('2026-09-10T23:00', '2026-09-10T23:00')).toBe('9月10日 23:00')
    expect(formatSpan('2026-09-10T22:00', '2026-09-10T23:00')).toBe('22:00 — 23:00')
  })

  it('formatSpan：跨日只给日 + 时刻（不再出现 04:00 — 04:00）', () => {
    expect(formatSpan('2026-09-10T22:00', '2026-09-11T04:00')).toBe(
      '10日 22:00 — 11日 04:00',
    )
  })

  it('formatSpan：跨月补月、跨年补年', () => {
    expect(formatSpan('2026-09-30T22:00', '2026-10-01T05:00')).toBe(
      '9月30日 22:00 — 10月1日 05:00',
    )
    expect(formatSpan('2026-12-31T22:00', '2027-01-01T05:00')).toBe(
      '2026年12月31日 22:00 — 2027年1月1日 05:00',
    )
  })
})
