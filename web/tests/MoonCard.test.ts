import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MoonCard from '../src/components/index/MoonCard.vue'
import type { StargazeAstro, StargazeMoon } from '../src/types'

const moon: StargazeMoon = { phase: 3.2, illumination: 0.11, label: '蛾眉月' }
const astro: StargazeAstro = {
  sunrise: '05:41',
  sunset: '18:52',
  astro_dusk: '20:36',
  astro_dawn: '04:31',
  moonrise: '06:12',
  moonset: '19:09',
  galactic_rise: '14:46',
  galactic_set: '00:15',
}
const nextAstro: StargazeAstro = { ...astro, astro_dawn: '04:32' }

const NULL_ASTRO: StargazeAstro = {
  sunrise: null,
  sunset: null,
  astro_dusk: null,
  astro_dawn: null,
  moonrise: null,
  moonset: null,
  galactic_rise: null,
  galactic_set: null,
}

describe('MoonCard', () => {
  it('渲染月相名/月龄/照明度/月出西沉与时间 chips', () => {
    const w = mount(MoonCard, { props: { moon, astro, nextAstro } })
    expect(w.text()).toContain('蛾眉月')
    expect(w.text()).toContain('月龄 3.2')
    expect(w.text()).toContain('照明度 11%')
    expect(w.text()).toContain('06:12 月出')
    expect(w.text()).toContain('19:09 西沉')
    expect(w.text()).toContain('月落之后，深空朗澈')
    expect(w.find('path.moon-shape').exists()).toBe(true)
  })

  it('天文字段 chips：暮光结束 / 次日晨光 / 暗夜时长 / 银心升落', () => {
    const w = mount(MoonCard, { props: { moon, astro, nextAstro } })
    const chips = w.findAll('.moon-chips .chip').map((c) => c.text())
    expect(chips).toEqual([
      '天文暮光 20:36 结束',
      '次日天文晨光 04:32',
      '暗夜 7 时 56 分',
      '银河核心 14:46 升 · 次日 00:15 落（入夜即在）',
    ])
    // 「暗夜保护区」硬编码 chip 已删除
    expect(w.text()).not.toContain('暗夜保护区')
  })

  it('缺少 nextAstro 时回退当天晨光算暗夜时长', () => {
    const w = mount(MoonCard, { props: { moon, astro } })
    const chips = w.findAll('.moon-chips .chip').map((c) => c.text())
    expect(chips[1]).toBe('次日天文晨光 04:31')
    expect(chips[2]).toBe('暗夜 7 时 55 分')
  })

  it('月/日图例并列：同尺寸 52px 图标 + 各自当日时刻', () => {
    const w = mount(MoonCard, { props: { moon, astro } })
    // 并列容器里两个卡片（月 + 日）
    expect(w.findAll('.moon-sun .sky-card')).toHaveLength(2)
    const moonIco = w.find('svg.moon-ico')
    const sunIco = w.find('svg.sun-ico')
    expect(moonIco.exists()).toBe(true)
    expect(sunIco.exists()).toBe(true)
    // 图例同尺寸（同一 .sky-ico 类，52px）
    expect(moonIco.classes()).toContain('sky-ico')
    expect(sunIco.classes()).toContain('sky-ico')
    expect(w.find('path.moon-shape').exists()).toBe(true)
    expect(w.find('circle.sun-ring').exists()).toBe(true)
    // 太阳：光芒全在圆环外侧（用户手绘风格），且不越出 52 画布
    const r = Number(w.find('circle.sun-ring').attributes('r'))
    expect(w.find('circle.sun-ring').attributes('fill')).toBe('none')
    const rays = w.findAll('svg.sun-ico line')
    expect(rays).toHaveLength(8)
    for (const ray of rays) {
      const x1 = Number(ray.attributes('x1'))
      const y1 = Number(ray.attributes('y1'))
      const x2 = Number(ray.attributes('x2'))
      const y2 = Number(ray.attributes('y2'))
      expect(Math.hypot(x1 - 26, y1 - 26)).toBeGreaterThan(r) // 起点在环外
      expect(Math.hypot(x2 - 26, y2 - 26)).toBeGreaterThan(r) // 终点在环外
      expect(Math.hypot(x2 - 26, y2 - 26)).toBeLessThanOrEqual(25)
      for (const v of [x1, y1, x2, y2]) {
        expect(v).toBeGreaterThanOrEqual(0)
        expect(v).toBeLessThanOrEqual(52)
      }
    }
    // 日卡片：日出/日落 + 白昼时长
    const sun = w.find('svg.sun-ico').element.closest('.sky-card') as HTMLElement
    expect(sun.textContent).toContain('日出 05:41 · 日落 18:52')
    expect(sun.textContent).toContain('白昼 13 时 11 分')
    // 日落不在 chips 里重复；chips 全部数据驱动（无硬编码）
    const chips = w.findAll('.moon-chips .chip').map((c) => c.text())
    expect(chips.some((t) => t.includes('日落'))).toBe(false)
    expect(chips.some((t) => t.includes('银河核心 14:46 升'))).toBe(true)
  })

  it('astro 缺省时时间位显示 —', () => {
    const w = mount(MoonCard, { props: { moon } })
    expect(w.text()).toContain('日落 —')
    expect(w.text()).toContain('日出 —')
    expect(w.text()).toContain('天文暮光 — 结束')
    expect(w.text()).not.toContain('月落之后')
  })

  it('astro 全 null 时 chips 全部 — 且无月落之后行', () => {
    const w = mount(MoonCard, { props: { moon, astro: NULL_ASTRO } })
    expect(w.text()).toContain('日落 —')
    expect(w.text()).toContain('日出 —')
    expect(w.text()).toContain('天文暮光 — 结束')
    expect(w.text()).toContain('次日天文晨光 —')
    expect(w.text()).toContain('银河核心 —')
    expect(w.text()).not.toContain('月落之后')
    expect(w.find('.moon-chips .chip.gold')).not.toBeNull()
  })
})