import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'

import type { StargazeIndex } from '../src/types'

const fetchMock = vi.fn()
vi.mock('../src/api/stargaze', () => ({
  fetchStargazeIndex: (...a: unknown[]) => fetchMock(...a),
}))

import IndexView from '../src/views/IndexView.vue'

function sampleIndex(over: Partial<StargazeIndex> = {}): StargazeIndex {
  return {
    ok: true,
    city: '北京',
    province: '北京',
    lat: 39.9,
    lon: 116.4,
    timezone: 'Asia/Shanghai',
    bortle: 8,
    bortle_label: '城市',
    score: 72,
    grade: '良',
    moon: { phase: 13.4, illumination: 0.99, label: '满月' },
    now: { time: '2026-08-27T00:00', cloud: 10, precip: 0, wind: 5, temp: 20 },
    components: { cloud: 90, precip: 100, windtemp: 80, moon: 1, bortle: 5 },
    hourly: [
      { time: '2026-08-27T00:00', score: 72, grade: '良', cloud: 10, precip: 0 },
      { time: '2026-08-27T03:00', score: 40, grade: '一般', cloud: 50, precip: 20 },
      { time: '2026-08-27T06:00', score: 30, grade: '差', cloud: 90, precip: 60 },
    ],
    ...over,
  }
}

function mountView() {
  return mount(IndexView, { global: { plugins: [createPinia()] } })
}

beforeEach(() => {
  fetchMock.mockReset()
  // @ts-expect-error 清理 geolocation，让 locate 走默认城市回退
  delete navigator.geolocation
})

describe('IndexView', () => {
  it('onMounted 触发加载，成功后渲染仪表数据', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="stargaze-ready"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('北京')
    expect(wrapper.text()).toContain('72')
    expect(wrapper.text()).toContain('满月')
  })

  it('加载失败时渲染错误态', async () => {
    fetchMock.mockRejectedValue(new Error('down'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="stargaze-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('天象未明')
  })

  it('请求挂起时渲染 loading 态', async () => {
    fetchMock.mockReturnValue(new Promise(() => {}))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('[data-testid="stargaze-loading"]').exists()).toBe(true)
  })

  it('ready 态渲染曲线 svg 与横轴标签', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('svg.curve').exists()).toBe(true)
    const labels = wrapper.find('.curve-xlabels')
    expect(labels.exists()).toBe(true)
    expect(labels.text()).toContain('08/27')
  })
})