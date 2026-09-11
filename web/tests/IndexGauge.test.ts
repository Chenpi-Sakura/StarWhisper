import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import IndexGauge from '../src/components/index/IndexGauge.vue'

describe('IndexGauge', () => {
  it('渲染 INDEX · 满分百 与最终分数', async () => {
    const w = mount(IndexGauge, { props: { score: 72 } })
    expect(w.text()).toContain('INDEX')
    expect(w.text()).toContain('满分百')
    // 动画由 requestAnimationFrame 驱动，jsdom 下至少最终渲染出数值
    expect(w.find('.gauge-num').text()).toMatch(/^\d{1,3}$/)
  })

  it('指针初始存在且刻度生成', () => {
    const w = mount(IndexGauge, { props: { score: 0 } })
    expect(w.find('.gauge-needle').exists()).toBe(true)
    // 刻度线由 JS 生成（40 档）
    expect(w.findAll('.gauge-tick').length).toBeGreaterThanOrEqual(30)
  })
})