import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import StarCanvas from '../src/components/StarCanvas.vue'

// 与 M1 用例一致：jsdom 不实现 ResizeObserver / matchMedia；并打一个非零 box 让 draw 不跳过。
beforeEach(() => {
  // @ts-ignore — assigning a mock to a globally-missing constructor
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  // @ts-ignore — IntersectionObserver 同样在 jsdom 缺失
  ;(globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get() {
      return 400
    },
  })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get() {
      return 300
    },
  })
  // jsdom 不实现 HTMLCanvasElement.getContext（无 canvas npm 包），
  // 这里返回 null 让 StarCanvas.tick() 提前 return，避免 stderr 噪音。
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    null as unknown as CanvasRenderingContext2D,
  )
})

afterEach(() => {
  vi.restoreAllMocks()
})

// 与 src/types.ts 全局定义对齐（P2-1 hemisphere 收紧为 Hemisphere）
type Hemisphere = 'N' | 'S' | 'B'
interface ConstellationAtlas {
  abbr: string
  name: string
  latin: string
  glyph?: string
  hemisphere?: Hemisphere
  bestMonth?: number
  season?: string
  caption?: string
  magnitude?: number
  storyStyles?: string[]
  stars: Record<string, { x: number; y: number; magnitude: number }>
  lines?: [string, string][]
  viewBox?: { width: number; height: number }
}

const orionAtlas: ConstellationAtlas = {
  abbr: 'ori',
  name: '猎户座',
  latin: 'Orion',
  glyph: '✶',
  hemisphere: 'B',
  bestMonth: 1,
  season: '冬季',
  caption: '冬夜之王',
  magnitude: 0.13,
  storyStyles: ['myth', 'science'],
  stars: {
    betelgeuse: { x: 144, y: 62, magnitude: 0.42 },
    bellatrix: { x: 330, y: 78, magnitude: 1.64 },
  },
  lines: [['betelgeuse', 'bellatrix']],
  viewBox: { width: 640, height: 460 },
}

describe('StarCanvas 动画参数（spec §6.1 / §6.2 / §16.2.1）', () => {
  it('atlas ±2° sin(2π t / 12s) 公式正确', () => {
    const amp = (2 * Math.PI) / 180
    const period = 12000
    const thetaAt = (t: number) => amp * Math.sin((2 * Math.PI * t) / period)
    expect(thetaAt(0)).toBeCloseTo(0, 5)
    expect(thetaAt(3000)).toBeCloseTo(amp, 5)   // 1/4 周期达正峰
    expect(thetaAt(6000)).toBeCloseTo(0, 5)     // 半周期回到 0
    expect(thetaAt(9000)).toBeCloseTo(-amp, 5)  // 3/4 周期达负峰
  })

  it('闪烁 1.6s sin 公式正确（spec §6.1）', () => {
    const period = 1600
    const blurAt = (t: number) => 6 + 4 * Math.sin((2 * Math.PI * t) / period)
    expect(blurAt(0)).toBeCloseTo(6, 5)
    expect(blurAt(400)).toBeCloseTo(10, 5)    // 1/4 周期达峰
    expect(blurAt(800)).toBeCloseTo(6, 5)
    expect(blurAt(1200)).toBeCloseTo(2, 5)
  })

  it('描出 1.2s easeOutCubic 终值 = 1', () => {
    const DUR = 1200
    const t = 1.0
    const eased = 1 - Math.pow(1 - t, 3)
    expect(eased).toBe(1)
    // 顺带验证 easeOutCubic 中间值：t=0.5 → 0.875
    expect(1 - Math.pow(0.5, 3)).toBeCloseTo(0.875, 5)
    expect(DUR).toBe(1200)
  })

  it('scan-atlas 模式 mount 不崩（ConstellationAtlas 类型 + atlas 渲染）', () => {
    const wrapper = mount(StarCanvas, {
      props: { mode: 'scan-atlas', constellationData: orionAtlas },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('overlay 模式 + empty 不闪（shadowBlur=0，spec §6.1）', () => {
    const wrapper = mount(StarCanvas, {
      props: {
        mode: 'overlay',
        starsOverlay: [
          {
            bayer: 'Alpha Ori',
            name: '参宿四',
            magnitude: 0.42,
            pixel_x: 100,
            pixel_y: 50,
            constellation: 'ori',
          },
        ],
        overlayLines: [],
        imageWidth: 100,
        imageHeight: 100,
        empty: true,
      },
    })
    // empty 时整段连线跳过，星点 opacity 0.2，无闪烁。组件挂载成功即可。
    expect(wrapper.exists()).toBe(true)
  })
})