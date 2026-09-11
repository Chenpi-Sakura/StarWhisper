import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import TrendBars from '../src/components/index/TrendBars.vue'
import type { HourlyPoint } from '../src/types'

function pt(h: number, score: number): HourlyPoint {
  const hh = String(h).padStart(2, '0')
  return { time: `2026-09-10T${hh}:00`, score, grade: '良', cloud: 10, precip: 0 }
}

const hourly: HourlyPoint[] = [
  pt(0, 90), pt(1, 88), pt(2, 86), pt(3, 70), pt(4, 40), pt(5, 20),
  pt(6, 10), pt(7, 15), pt(8, 30),
]

function bigHourly(n: number): HourlyPoint[] {
  const base = new Date(2026, 8, 10, 0, 0)
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(base.getTime() + i * 3600_000)
    const pad = (x: number) => String(x).padStart(2, '0')
    const time = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
    return { time, score: 70, grade: '良', cloud: 10, precip: 0 }
  })
}

/** 24 小时，19:00 前与 05:00 后为白昼（night=false）。 */
function dayNightHourly(): HourlyPoint[] {
  return Array.from({ length: 24 }, (_, h) => ({
    time: `2026-09-10T${String(h).padStart(2, '0')}:00`,
    score: 70,
    grade: '良' as const,
    cloud: 10,
    precip: 0,
    night: h >= 19 || h < 5,
  }))
}

describe('TrendBars', () => {
  it('渲染每点一根柱', () => {
    const w = mount(TrendBars, { props: { hourly } })
    expect(w.findAll('.cbar')).toHaveLength(hourly.length)
  })

  it('标记最佳观测窗（连续高分段）与当前时刻', () => {
    const w = mount(TrendBars, { props: { hourly, nowTime: '2026-09-10T05:00' } })
    expect(w.findAll('.cbar.best').length).toBe(4) // 00-03 时
    expect(w.findAll('.cbar.now').length).toBe(1)
    expect(w.text()).toContain('最佳观测窗')
    expect(w.text()).toContain('00:00')
  })

  it('空数据渲染占位文案', () => {
    const w = mount(TrendBars, { props: { hourly: [] } })
    expect(w.text()).toContain('暂不可用')
  })

  it('纵坐标给出指数说明（观星指数 0—100）与 5 档刻度', () => {
    const w = mount(TrendBars, { props: { hourly } })
    expect(w.find('.chart-ylab').exists()).toBe(true)
    expect(w.find('.chart-ylab').text()).toContain('观星指数')
    expect(w.find('.chart-ylab').text()).toContain('0—100')
    expect(w.findAll('.chart-yticks i').map((i) => i.text())).toEqual([
      '100', '75', '50', '25', '0',
    ])
  })

  it('≤24 点：x 轴每 4 小时一格且标签取自真实时刻（起点不必是 0 点）', () => {
    const w = mount(TrendBars, { props: { hourly } })
    const labels = w
      .findAll('.chart-axis .axis-slot')
      .map((s) => s.text())
      .filter((t) => t !== '')
    expect(labels).toEqual(['00', '04', '08'])
    expect(w.find('.chart-bars').classes()).not.toContain('dense')
  })

  it('≤24 点且起点非 0 点：轴标签跟随区间真实小时（非 00..24）', () => {
    const shifted: HourlyPoint[] = Array.from({ length: 24 }, (_, i) => {
      const abs = 14 + i // 14:00 起 24 小时
      const day = 10 + Math.floor(abs / 24)
      const hh = String(abs % 24).padStart(2, '0')
      return {
        time: `2026-09-${day}T${hh}:00`,
        score: 70,
        grade: '良',
        cloud: 10,
        precip: 0,
      }
    })
    const w = mount(TrendBars, { props: { hourly: shifted } })
    expect(w.findAll('.cbar')).toHaveLength(24)
    const labels = w
      .findAll('.chart-axis .axis-slot')
      .map((s) => s.text())
      .filter((t) => t !== '')
    // 每 4 小时一格 + 末点：14,18,22,02,06,10,13
    expect(labels).toEqual(['14', '18', '22', '02', '06', '10', '13'])
    expect(w.find('.chart-axis').text()).not.toContain('24')
  })

  it('168 点：渲染 168 根柱，轴标签按天派生（非 00/24）', () => {
    const w = mount(TrendBars, { props: { hourly: bigHourly(168) } })
    expect(w.findAll('.cbar')).toHaveLength(168)
    const ticks = w.findAll('.chart-axis span')
    expect(ticks).toHaveLength(8)
    expect(ticks[0].text()).toBe('+0d')
    expect(ticks[7].text()).toBe('+7d')
    expect(w.find('.chart-axis').text()).not.toContain('24')
    expect(w.find('.chart-bars').classes()).toContain('dense')
  })

  it('昼夜标注：白昼柱压淡 + 昼夜带 + 图例（night=false）', () => {
    const w = mount(TrendBars, { props: { hourly: dayNightHourly() } })
    // 19:00-23:00 与 00:00-04:00 共 10 个夜间小时
    expect(w.findAll('.cbar.day')).toHaveLength(14)
    expect(w.findAll('.night-band .nb')).toHaveLength(24)
    expect(w.findAll('.night-band .nb.day')).toHaveLength(14)
    expect(w.text()).toContain('夜间可观测')
    expect(w.text()).toContain('白昼 / 暮光')
  })

  it('无 night 字段（旧数据）不画昼夜带，兼容旧行为', () => {
    const w = mount(TrendBars, { props: { hourly } })
    expect(w.find('.night-band').exists()).toBe(false)
    expect(w.findAll('.cbar.day')).toHaveLength(0)
  })

  it('最佳观测窗只取夜间小时：白昼高分不算窗口', () => {
    const pts: HourlyPoint[] = Array.from({ length: 24 }, (_, h) => ({
      time: `2026-09-10T${String(h).padStart(2, '0')}:00`,
      score: h === 12 ? 99 : h === 21 || h === 22 ? 80 : 30,
      grade: '良' as const,
      cloud: 10,
      precip: 0,
      night: h >= 19 || h < 5,
    }))
    const w = mount(TrendBars, { props: { hourly: pts } })
    // 12:00 分数最高但为白昼 → 窗口应落在 21:00-22:00
    expect(w.findAll('.cbar.best')).toHaveLength(2)
    expect(w.findAll('.cbar.best.day')).toHaveLength(0)
    expect(w.text()).toContain('21:00 — 22:00')
  })

  it('最佳观测窗跨日时补上日期（不再出现 04:00 — 04:00 式歧义）', () => {
    const pts: HourlyPoint[] = [
      { time: '2026-09-10T23:00', score: 90, grade: '优', cloud: 5, precip: 0, night: true },
      { time: '2026-09-11T00:00', score: 88, grade: '优', cloud: 5, precip: 0, night: true },
      { time: '2026-09-11T04:00', score: 85, grade: '优', cloud: 5, precip: 0, night: true },
    ]
    const w = mount(TrendBars, { props: { hourly: pts } })
    expect(w.text()).toContain('10日 23:00 — 11日 04:00')
  })

  it('单一小时窗口只给一个时刻（M月D日 HH:MM）', () => {
    const pts: HourlyPoint[] = [
      { time: '2026-09-10T23:00', score: 90, grade: '优', cloud: 5, precip: 0, night: true },
      { time: '2026-09-11T00:00', score: 20, grade: '差', cloud: 5, precip: 0, night: true },
    ]
    const w = mount(TrendBars, { props: { hourly: pts } })
    expect(w.text()).toContain('9月10日 23:00')
    expect(w.text()).not.toContain('23:00 — 23:00')
  })

  it('整段白昼 → 明说无观测窗', () => {
    const pts: HourlyPoint[] = Array.from({ length: 3 }, (_, i) => ({
      time: `2026-09-10T1${i}:00`,
      score: 90,
      grade: '优' as const,
      cloud: 5,
      precip: 0,
      night: false,
    }))
    const w = mount(TrendBars, { props: { hourly: pts } })
    expect(w.text()).toContain('整段皆为白昼')
    expect(w.findAll('.cbar.best')).toHaveLength(0)
  })
})