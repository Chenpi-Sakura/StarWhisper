/**
 * atlasProjection 单测（TS 端）。
 *
 * 与 Python `server/scripts/atlas_projection.py` 1:1 对齐。
 * 验证：北斗 7 星 golden value + 中心 guard + 方向断言 + Python 交叉验证。
 */
import { describe, it, expect } from 'vitest'
import {
  computeCenter,
  angularSeparation,
  computeField,
  projectStereographic,
  type StarCoord,
  type Viewbox,
} from '../src/utils/atlasProjection'

const VIEWBOX: Viewbox = { w: 700, h: 700 }
const PADDING = 30

// 北斗 7 星 (RA°, Dec°) — 与 Python 测试同组
const BEIDOU: StarCoord[] = [
  { ra: 165.932, dec: 61.751 },  // 天枢 Dubhe
  { ra: 165.460, dec: 56.382 },  // 天璇 Merak
  { ra: 178.458, dec: 53.695 },  // 天玑 Phecda
  { ra: 183.857, dec: 57.033 },  // 天权 Megrez
  { ra: 193.507, dec: 55.960 },  // 玉衡 Alioth
  { ra: 200.981, dec: 54.925 },  // 开阳 Mizar
  { ra: 206.885, dec: 49.313 },  // 摇光 Alkaid
]

describe('computeCenter', () => {
  it('北斗 7 星 → (186.04, 56.55) ±0.05°', () => {
    const { ra, dec } = computeCenter(BEIDOU)
    expect(ra).toBeCloseTo(186.04, 1)
    expect(dec).toBeCloseTo(56.55, 1)
  })

  it('空数组 → (0, 0)', () => {
    expect(computeCenter([])).toEqual({ ra: 0, dec: 0 })
  })
})

describe('angularSeparation', () => {
  it('同一点 → 0', () => {
    expect(angularSeparation(100, 30, 100, 30)).toBeCloseTo(0, 9)
  })

  it('Vega–Altair ≈ 34.2°（教科书值）', () => {
    const sep = angularSeparation(279.23, 38.78, 297.70, 8.87)
    expect(sep).toBeGreaterThan(33.7)
    expect(sep).toBeLessThan(34.7)
  })
})

describe('projectStereographic', () => {
  it('中心点 → 画布中心（误差 < 1e-6 px）', () => {
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    const { x, y } = projectStereographic(
      field.center.ra, field.center.dec,
      field.center.ra, field.center.dec,
      field.scale, VIEWBOX
    )
    expect(Math.abs(x - VIEWBOX.w / 2)).toBeLessThan(1e-6)
    expect(Math.abs(y - VIEWBOX.h / 2)).toBeLessThan(1e-6)
  })

  it('东=右、北=上', () => {
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    for (const s of BEIDOU) {
      const { x, y } = projectStereographic(
        s.ra, s.dec,
        field.center.ra, field.center.dec,
        field.scale, VIEWBOX
      )
      if (s.ra > field.center.ra) expect(x).toBeGreaterThan(VIEWBOX.w / 2)
      if (s.dec > field.center.dec) expect(y).toBeLessThan(VIEWBOX.h / 2)
    }
  })

  it('跟 Python 同输入输出误差 < 0.01 px（3 个验证点）', () => {
    // 验证点：Python ground truth 输出（center=(185.99, 56.51)，scale=1263.98）
    // 与 TS Stereographic 公式应完全一致
    const field = computeField(BEIDOU, VIEWBOX, PADDING)
    const cases: Array<[StarCoord, [number, number]]> = [
      [{ ra: 165.932, dec: 61.751 }, [142.7399, 202.8970]],  // 天枢 Dubhe
      [{ ra: 206.885, dec: 49.313 }, [648.5968, 465.0651]],  // 摇光 Alkaid
      [{ ra: 193.507, dec: 55.960 }, [442.6808, 357.1650]],  // 玉衡 Alioth
    ]
    for (const [star, [exX, exY]] of cases) {
      const { x, y } = projectStereographic(
        star.ra, star.dec,
        field.center.ra, field.center.dec,
        field.scale, VIEWBOX
      )
      expect(Math.abs(x - exX)).toBeLessThan(0.01)
      expect(Math.abs(y - exY)).toBeLessThan(0.01)
    }
  })
})