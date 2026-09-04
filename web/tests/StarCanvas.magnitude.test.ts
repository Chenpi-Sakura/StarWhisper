import { mount } from '@vue/test-utils'
import { beforeEach, test, vi, expect } from 'vitest'

import StarCanvas from '../src/components/StarCanvas.vue'

beforeEach(() => {
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
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
})

test('magnitudeToRadius: 6 档分档覆盖人眼对数感知', () => {
  const w = mount(StarCanvas, { props: { mode: 'overlay' } })
  const { magnitudeToRadius } = w.vm as unknown as {
    magnitudeToRadius: (m: number | undefined) => number
  }

  // 1 等及以上（最亮）→ 8.5 × 0.75 ≈ 6.4
  expect(magnitudeToRadius(-1.5)).toBeCloseTo(6.4, 1)   // 天狼星
  expect(magnitudeToRadius(0)).toBeCloseTo(6.4, 1)      // 织女星
  expect(magnitudeToRadius(1)).toBeCloseTo(6.4, 1)      // 牛郎星

  // 2 等 → 6.5 × 0.75 ≈ 4.9
  expect(magnitudeToRadius(1.5)).toBeCloseTo(4.9, 1)
  expect(magnitudeToRadius(2)).toBeCloseTo(4.9, 1)

  // 3 等 → 5 × 0.75 ≈ 3.75
  expect(magnitudeToRadius(2.5)).toBeCloseTo(3.75, 1)
  expect(magnitudeToRadius(3)).toBeCloseTo(3.75, 1)

  // 4 等 → 4 × 0.75 = 3.0（北方星等肉眼可见下限附近）
  expect(magnitudeToRadius(4)).toBeCloseTo(3.0, 1)

  // 5 等 → 3 × 0.75 ≈ 2.25
  expect(magnitudeToRadius(5)).toBeCloseTo(2.25, 1)

  // 6 等及以上（极限）→ 2.2 × 0.75 ≈ 1.65
  expect(magnitudeToRadius(6)).toBeCloseTo(1.65, 1)
  expect(magnitudeToRadius(6.5)).toBeCloseTo(1.65, 1)
})

test('magnitudeToRadius: undefined mag 走中等等级（4 等）', () => {
  const w = mount(StarCanvas, { props: { mode: 'overlay' } })
  const { magnitudeToRadius } = w.vm as unknown as {
    magnitudeToRadius: (m: number | undefined) => number
  }
  // 缺省 4 等 → r=3.0
  expect(magnitudeToRadius(undefined)).toBeCloseTo(3.0, 1)
  expect(magnitudeToRadius(undefined)).toBe(magnitudeToRadius(4))
})

test('magnitudeToRadius: 亮星与暗星区分度明显', () => {
  const w = mount(StarCanvas, { props: { mode: 'overlay' } })
  const { magnitudeToRadius } = w.vm as unknown as {
    magnitudeToRadius: (m: number | undefined) => number
  }
  // 1 等 vs 6.5 等：半径比 6.4/1.65 ≈ 3.88×（SCALE_FACTOR=0.75 整体缩小后
  // 仍保留强区分度）。本测试确保 1 等半径 > 5 等半径（最常见对比）。
  expect(magnitudeToRadius(1)).toBeGreaterThan(magnitudeToRadius(5))
  expect(magnitudeToRadius(2)).toBeGreaterThan(magnitudeToRadius(4))
  expect(magnitudeToRadius(3)).toBeGreaterThan(magnitudeToRadius(6))
})
