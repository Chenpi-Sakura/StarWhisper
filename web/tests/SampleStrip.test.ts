import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import SampleStrip from '../src/components/SampleStrip.vue'
import { QUICK_SAMPLES } from '../src/data/samples'

describe('SampleStrip 样图速测条', () => {
  it('渲染全部样图卡片（3 张）', () => {
    const wrapper = mount(SampleStrip)
    expect(wrapper.find('[data-testid="sample-strip"]').exists()).toBe(true)
    for (const s of QUICK_SAMPLES) {
      expect(wrapper.find(`[data-testid="sample-card-${s.id}"]`).exists()).toBe(true)
    }
    expect(wrapper.findAll('.sample-card')).toHaveLength(2)
  })

  it('点击卡片抛出 pick 事件并带上样图对象', async () => {
    const wrapper = mount(SampleStrip)
    const card = wrapper.find('[data-testid="sample-card-test2"]')
    await card.trigger('click')
    const events = wrapper.emitted('pick')
    expect(events).toHaveLength(1)
    expect(events![0][0]).toMatchObject({ id: 'test2', src: '/samples/quick-test2.jpg' })
  })

  it('某张样图正在下载时整条禁用，点击不再抛事件', async () => {
    const wrapper = mount(SampleStrip, { props: { loadingId: 'test1' } })
    const onPick = vi.fn()
    const busy = wrapper.find('[data-testid="sample-card-test1"]')
    const other = wrapper.find('[data-testid="sample-card-test2"]')
    expect(busy.attributes('disabled')).toBeDefined()
    expect(other.attributes('disabled')).toBeDefined()
    expect(busy.classes()).toContain('busy')
    // busy 遮罩只出现在被点的那张上
    expect(busy.find('.busy-mask').exists()).toBe(true)
    expect(other.find('.busy-mask').exists()).toBe(false)
    await other.trigger('click')
    expect(onPick).not.toHaveBeenCalled()
    expect(wrapper.emitted('pick')).toBeUndefined()
  })

  it('disabled=true 时同样屏蔽点击', async () => {
    const wrapper = mount(SampleStrip, { props: { disabled: true } })
    await wrapper.find('[data-testid="sample-card-test1"]').trigger('click')
    expect(wrapper.emitted('pick')).toBeUndefined()
  })
})
