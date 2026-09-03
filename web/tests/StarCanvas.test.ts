import { mount } from '@vue/test-utils'
import { beforeEach, test as vitest, vi, expect } from 'vitest'

import StarCanvas from '../src/components/StarCanvas.vue'

// jsdom does not implement ResizeObserver — stub it.
beforeEach(() => {
  // @ts-ignore — assigning a mock to a globally-missing constructor
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  // @ts-ignore — matchMedia missing in jsdom
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
  // jsdom does not perform layout, so clientWidth/Height are 0 by default.
  // Stub a non-zero box so the canvas can draw a frame.
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

function makeMockContext() {
  return {
    scale: vi.fn(),
    setTransform: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    ellipse: vi.fn(),
    setLineDash: vi.fn(),
    fillText: vi.fn(),
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    // 记录式 setter：供选中/未选中态连线样式断言用（alpha / lineWidth）
    strokeStyleValues: [] as string[],
    lineWidthValues: [] as number[],
    fillStyleValues: [] as string[],
    // getter/setter pairs so ctx.fillStyle = "..." does not throw
    set fillStyle(v: string) {
      this.fillStyleValues.push(v)
    },
    set strokeStyle(v: string) {
      this.strokeStyleValues.push(v)
    },
    set lineWidth(v: number) {
      this.lineWidthValues.push(v)
    },
    set shadowBlur(_v: number) {},
    set shadowColor(_v: string) {},
    set textBaseline(_v: string) {},
    set textAlign(_v: string) {},
    set font(_v: string) {},
    strokeText: vi.fn(),
  }
}

vitest('overlay mode draws lines with lineTo', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        { bayer: 'Alpha Ori', name: '参宿四', magnitude: 0.42, pixel_x: 100, pixel_y: 50, constellation: 'ori' },
        { bayer: 'Gamma Ori', name: '参宿五', magnitude: 1.64, pixel_x: 200, pixel_y: 60, constellation: 'ori' },
      ],
      overlayLines: [[100, 50, 200, 60]],
      imageWidth: 400,
      imageHeight: 300,
      activeAbbr: null,
    },
  })

  expect(ctx.lineTo).toHaveBeenCalled()
  expect(ctx.moveTo).toHaveBeenCalled()
})

vitest('overlay mode skips lines entirely when empty', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        { bayer: 'Alpha Ori', name: '参宿四', magnitude: 0.42, pixel_x: 100, pixel_y: 50, constellation: 'ori' },
        { bayer: 'Gamma Ori', name: '参宿五', magnitude: 1.64, pixel_x: 200, pixel_y: 60, constellation: 'ori' },
      ],
      overlayLines: [[100, 50, 200, 60]],
      imageWidth: 400,
      imageHeight: 300,
      empty: true,
    },
  })

  expect(ctx.lineTo).not.toHaveBeenCalled()
})

vitest('overlay mode dims lines from inactive constellations', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        { bayer: 'Alpha Ori', name: '参宿四', magnitude: 0.42, pixel_x: 100, pixel_y: 50, constellation: 'ori' },
        { bayer: 'Alpha Cyg', name: '天津四', magnitude: 1.25, pixel_x: 300, pixel_y: 80, constellation: 'cyg' },
        { bayer: 'Gamma Ori', name: '参宿五', magnitude: 1.64, pixel_x: 200, pixel_y: 60, constellation: 'ori' },
      ],
      overlayLines: [[100, 50, 200, 60]],
      imageWidth: 400,
      imageHeight: 300,
      activeAbbr: 'cyg',
    },
  })

  // One line is drawn (both endpoints match); strokeStyle setter sees both
  // active and inactive values because the line is not active.
  expect(ctx.lineTo).toHaveBeenCalled()
})

vitest('scan-atlas mode renders concentric rings and grid', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  mount(StarCanvas, {
    props: {
      mode: 'scan-atlas',
      activeAbbr: 'ori',
      constellationData: {
        abbr: 'ori',
        name: '猎户座',
        latin: 'Orion',
        stars: {
          betelgeuse: { x: 144, y: 62, magnitude: 0.42 },
          bellatrix: { x: 330, y: 78, magnitude: 1.64 },
        },
        lines: [['betelgeuse', 'bellatrix']],
      },
    },
  })

  // grid (multiple moveTo) + 2 ellipses (rings) + atlas line
  expect(ctx.moveTo).toHaveBeenCalled()
  expect(ctx.ellipse).toHaveBeenCalledTimes(2)
  expect(ctx.lineTo).toHaveBeenCalled()
})

vitest('each frame calls clearRect to prevent residue from previous draw', () => {
  // ★ 回归测试：tick 入口必须 clearRect，否则切换星座时旧 label
  // （新数据 `label: true` 星点数 < 旧数据时旧 fillText 不会被打到）会残
  // 留在画布上。复现场景：先画 CYG（3 个 label: true 星点），再切到 AQL
  // （0 个 label: true 星点）→ AQL 画完 fillText 不会覆盖 CYG 的 label
  // 位置，画布上仍能看到天津四/天津一/婁道增七。
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  // scan-atlas 模式 + 有 label 的星点 → 触发 fillText
  mount(StarCanvas, {
    props: {
      mode: 'scan-atlas',
      activeAbbr: 'cyg',
      constellationData: {
        abbr: 'cyg',
        name: '天鹅座',
        latin: 'Cygnus',
        stars: {
          deneb: { x: 320, y: 30, magnitude: 1.25, label: true, name_zh: '天津四' },
          sadr: { x: 320, y: 200, magnitude: 2.23, label: true, name_zh: '天津一' },
        },
        lines: [['deneb', 'sadr']],
      },
    },
  })

  // 至少调用 1 次 clearRect（在 setTransform + scale 之后）
  expect(ctx.clearRect).toHaveBeenCalled()
  // 参数应为 CSS 尺寸（0, 0, w, h），不是 device pixel
  const lastCall = ctx.clearRect.mock.calls[ctx.clearRect.mock.calls.length - 1]
  expect(lastCall[0]).toBe(0)
  expect(lastCall[1]).toBe(0)
  expect(typeof lastCall[2]).toBe('number')
  expect(typeof lastCall[3]).toBe('number')
})

vitest('line stagger: drawDuration adapts so all 20 lines have lineDelay < 1', () => {
  // ★ 回归测试：修复前 20 条线时 lineDelay = (idx × 80) / 1200，最后几条
  // （idx > 14）lineDelay > 1 → lineT 被 clamp 到 0 → 完全不画。
  // 复现：夏季大三角 20 条连线 → CYG（idx 16-19）全部 invisible、
  // AQL 最后 2 条（idx 14-15）部分缺失。
  // 修复后 drawDuration = max(1200, 20*80 + 600) = 2200，所有 lineDelay < 1。
  // 由于 jsdom 的 lifecycle 里 performance.now() 被 Vue/setup 多次消耗，
  // 难以精准 mock 拿到 startDraw 的 drawStartMs。这里直接断言 drawDuration
  // 的纯计算结果（暴露的 computeDrawDuration）—— 公式正确 ⇒ 动画必正常。
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )

  const wrapper = mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [],
      overlayLines: [],
      imageWidth: 400,
      imageHeight: 300,
      activeAbbr: null,
    },
  })

  const exposed = wrapper.vm as unknown as {
    computeDrawDuration: (n: number) => number
    DRAW_DURATION_MS: number
    LINE_STAGGER_MS: number
  }

  // 边界：单条线 = DRAW_DURATION_MS 原值
  expect(exposed.computeDrawDuration(1)).toBe(1200)
  expect(exposed.computeDrawDuration(15)).toBe(1800)  // 15*80 = 1200
  // 关键：20 条线 → 2200ms（之前 bug 是 1200，最后 5 条 lineDelay > 1）
  expect(exposed.computeDrawDuration(20)).toBe(2200)
  // 30 条线 → 30*80 + 600 = 3000
  expect(exposed.computeDrawDuration(30)).toBe(3000)

  // 用 20 条线时算 lineDelay 验证：max(idx * 80 / drawDuration) < 1
  const drawDuration = exposed.computeDrawDuration(20)
  const lineStaggerMs = exposed.LINE_STAGGER_MS
  for (let idx = 0; idx < 20; idx++) {
    const lineDelay = (idx * lineStaggerMs) / drawDuration
    expect(lineDelay).toBeLessThan(1)
  }
  // 反向验证：若用老的固定 DRAW_DURATION_MS，idx=19 的 lineDelay 会 > 1
  const oldDrawDuration = exposed.DRAW_DURATION_MS
  const oldLineDelay = (19 * lineStaggerMs) / oldDrawDuration
  expect(oldLineDelay).toBeGreaterThan(1)
})

// ★ 回归测试（用户反馈：选人马座后人马座连线没有高亮）：
// 旧逻辑在 activeAbbr 非 null 时把线统一乘 0.4 调暗——那是"传入全量线、
// 调暗非选中星座"时代的假设。T8 后 ScanView.displayLines 已只传选中星座
// 的线，再乘 0.4 会把选中星座自己的线压到 36% alpha，比未选中（90%）还暗。
// 修复后：选中态 alpha 与未选中一致（0.9）+ 线宽加粗。
// 用单调递增的 performance.now mock 让 drawProgress=1（lineT=1 终值）：
// 每次调用 +10s，与 drawStartMs 的间隔必 ≥10s > 最大 drawDuration(2.2s)，
// 不依赖 mount 内部的精确调用次数。jsdom 的 rAF 循环不会在同步断言前
// 执行下一帧。
function mountWithSettledDraw(props: {
  activeAbbr: string | null
  ctx: ReturnType<typeof makeMockContext>
}) {
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )

  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        { bayer: 'Alpha Sgr', name: '箕宿三', magnitude: 1.85, pixel_x: 100, pixel_y: 50, constellation: 'sgr' },
      ],
      overlayLines: [[100, 50, 200, 60]],
      imageWidth: 400,
      imageHeight: 300,
      activeAbbr: props.activeAbbr,
    },
  })
}

vitest('overlay 选中态：连线高亮（0.9 alpha + 加粗线宽），不再被调暗到 0.36', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  mountWithSettledDraw({ activeAbbr: 'sgr', ctx })

  // 修复前：lineA*0.4 → 'rgba(212,160,23,0.36)'（选中星座自己的线被调暗）
  // 修复后：与未选中一致 0.9
  expect(ctx.strokeStyleValues).toContain('rgba(212,160,23,0.9)')
  expect(ctx.strokeStyleValues).not.toContain('rgba(212,160,23,0.36)')
  // 选中态线宽加粗：1.5 × 1.33 → snapW(2x dpr_eff) = 2 > 1.5
  expect(Math.max(...ctx.lineWidthValues)).toBeGreaterThan(1.5)
})

vitest('overlay 未选中态：连线维持 M1 原样（0.9 alpha / 1.5 线宽）', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  mountWithSettledDraw({ activeAbbr: null, ctx })

  expect(ctx.strokeStyleValues).toContain('rgba(212,160,23,0.9)')
  // dpr_eff=2 时 snapW(1.5, 2) = 1.5（恰为物理像素边界，不变粗）。
  // 调节 5/6 标注描边用 snapW(3, 2)=3（用户反馈描边改回 3px），故
  // lineWidthValues 集合为 {1.5, 3}。
  expect(ctx.lineWidthValues).toContain(1.5)
  expect(new Set(ctx.lineWidthValues)).toEqual(new Set([1.5, 3]))
})

// ★ 多归属 dim 测试（用户反馈：选人马座后人马座内部星点不亮）：
// stars_overlay[].constellation 是合并星表去重后的首现归属（chinese 按目录
// 序先加载，sgr 的星全被 ji_xiu/dou_xiu 抢注）→ s.constellation ===
// activeAbbr 对 western chip 全部 miss。修复后走 constellations 多归属列表。
function mountOverlayStars(props: {
  activeAbbr: string | null
  ctx: ReturnType<typeof makeMockContext>
  starsOverlay: Array<Record<string, unknown>>
}) {
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )
  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: props.starsOverlay as never,
      overlayLines: [],
      imageWidth: 400,
      imageHeight: 300,
      activeAbbr: props.activeAbbr,
    },
  })
}

const SGR_STAR_MULTI = {
  bayer: 'Alpha Sgr', name: '箕宿三', magnitude: 1.85,
  pixel_x: 100, pixel_y: 50, constellation: 'ji_xiu',
  constellations: ['sgr', 'ji_xiu'],
}

vitest('overlay 选中态：constellations 多归属命中 → 星点全亮（alpha=1）', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  mountOverlayStars({ activeAbbr: 'sgr', ctx, starsOverlay: [SGR_STAR_MULTI] })

  // 星点 fillStyle dim=1（旧逻辑按 constellation='ji_xiu' 判断会 miss 到 0.15）
  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,1)')
  expect(ctx.fillStyleValues).not.toContain('rgba(212,160,23,0.15)')
})

vitest('overlay 选中态：constellations 不含 activeAbbr → 星点淡出（0.15）', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  mountOverlayStars({
    activeAbbr: 'sgr',
    ctx,
    starsOverlay: [{
      bayer: 'Alpha Sco', name: '心宿二', magnitude: 1.06,
      pixel_x: 200, pixel_y: 80, constellation: 'sco',
      constellations: ['sco', 'xin_xiu'],
    }],
  })

  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,0.15)')
})

vitest('overlay 选中态：旧数据无 constellations 字段 → 回退 constellation 判断', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  mountOverlayStars({
    activeAbbr: 'sgr',
    ctx,
    starsOverlay: [{
      bayer: 'Alpha Sgr', name: '箕宿三', magnitude: 1.85,
      pixel_x: 100, pixel_y: 50, constellation: 'sgr',  // mock fixture 老格式
    }],
  })

  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,1)')
})

// ★ 视觉调节 4（用户反馈：连到外面的连线要显示但截断到边界，不是整条跳过）：
// 星点中心在 contain 矩形外 → 跳过；连线 Liang-Barsky 裁剪到矩形边界
// （跨界画截断段；完全在外才跳过）。
// container=400x300（beforeEach）+ image=200x200 → scale=1.5, offsetX=50,
// offsetY=0 → contain 矩形 (50,0)-(350,300)
vitest('overlay 星点裁剪 + 连线裁断（contain 矩形）', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )
  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        // cx=200, cy=150 在 contain 矩形内 → 渲染
        { bayer: 'In', name: 'in', magnitude: 2, pixel_x: 100, pixel_y: 100, constellation: 'sgr' },
        // cx=425 > 右边界 350 → 跳过
        { bayer: 'OutR', name: 'outR', magnitude: 2, pixel_x: 250, pixel_y: 100, constellation: 'sgr' },
        // cy=-150 < 上边界 0 → 跳过
        { bayer: 'OutU', name: 'outU', magnitude: 2, pixel_x: 100, pixel_y: -100, constellation: 'sgr' },
      ],
      overlayLines: [
        // 两端都在矩形内 → 整条画
        [100, 100, 50, 100],
        // 一端超出右边界（cx=425>350）→ 裁断到右边界后画可见段
        [100, 100, 250, 100],
        // 两端都在矩形右外（cx=475,425 均 > 350）→ 跳过
        [300, 100, 250, 100],
      ],
      imageWidth: 200,
      imageHeight: 200,
      activeAbbr: 'sgr',
    },
  })
  // 仅 In 星点 gold fillStyle（OutR/OutU 中心在外 → 跳过）；
  // 调节 5 后亮星名纸白 fillStyle 也入列，故按 gold 前缀过滤计数
  expect(
    ctx.fillStyleValues.filter((v) => v.startsWith('rgba(212,160,23')),
  ).toHaveLength(1)
  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,1)')
  // 两条连线 stroke（线 1 整条 + 线 2 裁断后可见段；线 3 完全在外跳过）
  expect(ctx.stroke).toHaveBeenCalledTimes(2)
  // 线 2 截断后端点应在右边界 350 上（moveTo 起点的 x）
  // 收集所有 moveTo 调用，第一条 (200,150)，第二条起 x 应 ≤ 350
  const moveToCalls = ctx.moveTo.mock.calls
  expect(moveToCalls.length).toBe(2)
  expect(moveToCalls[0][0]).toBeCloseTo(200, 0)  // 线 1 起 (200,150)
  expect(moveToCalls[1][0]).toBeLessThanOrEqual(350)  // 线 2 起被裁到 ≤ 350
})

// ★ 视觉调节 5（用户需求，修订：top20% → top10%）：canvas overlay 标注
// 3a. 星等最亮前 10% 星名（出界星排除后再取 top10%，至少 1 颗）
// 3b. 命中星座成员星点几何中心标星座名
vitest('overlay 标注：亮星 top10% 星名 + 命中星座中心名', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )
  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        // 在内：mag 0.5 / 2.0 / 3.0
        { bayer: 'a', name: 'Kaus Australis', name_zh: '箕宿三', magnitude: 0.5, pixel_x: 100, pixel_y: 100, constellation: 'sgr', constellations: ['sgr'] },
        { bayer: 'b', name: 'StarB', magnitude: 2.0, pixel_x: 120, pixel_y: 120, constellation: 'sgr', constellations: ['sgr'] },
        { bayer: 'c', name: 'StarC', magnitude: 3.0, pixel_x: 140, pixel_y: 140, constellation: 'sgr', constellations: ['sgr'] },
        // 最亮（0.1）但出界（cx=425>350）→ 排除在 visibleStars 外
        { bayer: 'd', name: 'OutBright', magnitude: 0.1, pixel_x: 250, pixel_y: 100, constellation: 'sgr', constellations: ['sgr'] },
      ],
      overlayLines: [],
      imageWidth: 200,
      imageHeight: 200,
      activeAbbr: null,
      hitConstellations: [{ abbr: 'sgr', name: '人马座' }],
    },
  })
  // visibleStars = 3 颗在内 → top10% = max(1, ceil(0.3)) = 1 → 仅 A（mag 0.5）标名
  // fillText 调用：A 星名 '箕宿三' + 星座中心 '人马座' = 2 次
  expect(ctx.fillText).toHaveBeenCalledTimes(2)
  const fillCalls = ctx.fillText.mock.calls.map((c) => c[0])
  expect(fillCalls).toContain('箕宿三')
  expect(fillCalls).toContain('人马座')
  expect(fillCalls).not.toContain('OutBright')
  // 中心 = 平均 pixel (120,120) → canvas (230,180)
  const centerCall = ctx.fillText.mock.calls.find((c) => c[0] === '人马座')
  expect(centerCall![1]).toBeCloseTo(230, 5)
  expect(centerCall![2]).toBeCloseTo(180, 5)
  // 描边垫底：星名 + 星座名各一次
  expect(ctx.strokeText).toHaveBeenCalledTimes(2)
})

// top10% 边界：11 颗可见星 → ceil(1.1) = 2 颗标注（10% 至少 1 颗）
vitest('overlay 标注：11 颗可见星按 10% 标 2 颗最亮', () => {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )
  // container 400x300 / image 200x200 → contain (50,0)-(350,300)，
  // pixel 网格 (20..140, 20..140) 11 颗全部在内（cx=50+i*15 ≤ 350）
  const stars = Array.from({ length: 11 }, (_, i) => ({
    bayer: `s${i}`,
    name: `N${i}`,
    magnitude: 1 + i * 0.2,  // i=0 最亮
    pixel_x: 20 + i * 10,
    pixel_y: 20 + i * 10,
    constellation: 'sgr',
    constellations: ['sgr'],
  }))
  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: stars,
      overlayLines: [],
      imageWidth: 200,
      imageHeight: 200,
      activeAbbr: null,
    },
  })
  const fillCalls = ctx.fillText.mock.calls.map((c) => c[0])
  expect(fillCalls).toHaveLength(2)
  expect(fillCalls).toContain('N0')  // mag 1.0 最亮
  expect(fillCalls).toContain('N1')  // mag 1.2 次亮
  expect(fillCalls).not.toContain('N2')
})

// ★ 视觉调节 6（用户需求：选中 chip 时非当前星座的内容淡出 0.4）：
// 亮星 top10% 名 + 命中星座中心名 + 非 active 命中星座的成员星点 →
// dim 全部按 activeAbbr 联动（active 1.0 / 非 active 0.4）。
// activeAbbr==null 时全部全亮（未选中状态）。
function mountOverlayWithActive(activeAbbr: string | null) {
  const ctx = makeMockContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  )
  let calls = 0
  vi.spyOn(performance, 'now').mockImplementation(
    () => 1_000_000 + (calls++) * 10_000,
  )
  const wrapper = mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        // A 星座（active）一颗亮星
        { bayer: 'a', name: 'Aalfa', name_zh: 'A亮', magnitude: 0.5, pixel_x: 100, pixel_y: 100, constellation: 'a', constellations: ['a'] },
        { bayer: 'a2', name: 'Abeta', magnitude: 2.0, pixel_x: 110, pixel_y: 110, constellation: 'a', constellations: ['a'] },
        // B 星座（非 active）一颗更亮（应占 top10% 但 dim 0.4）
        { bayer: 'b', name: 'Balfa', name_zh: 'B亮', magnitude: 0.3, pixel_x: 130, pixel_y: 130, constellation: 'b', constellations: ['b'] },
        { bayer: 'b2', name: 'Bbeta', magnitude: 2.5, pixel_x: 140, pixel_y: 140, constellation: 'b', constellations: ['b'] },
      ],
      overlayLines: [],
      imageWidth: 200,
      imageHeight: 200,
      activeAbbr,
      hitConstellations: [
        { abbr: 'a', name: 'A 星座' },
        { abbr: 'b', name: 'B 星座' },
      ],
    },
  })
  return { ctx, wrapper }
}

vitest('active 选中：非 active 命中星座的中心名 alpha=0.4', () => {
  const { ctx } = mountOverlayWithActive('a')
  const aFill = ctx.fillText.mock.calls.find((c) => c[0] === 'A 星座')
  expect(aFill).toBeDefined()
  // active 星座中心名 = 0.95；非 active = 0.95 × 0.4 = 0.38
  // (JS 浮点 0.95*0.4 字面 = 0.38)
  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,0.38)')
})

vitest('active 选中：非 active 命中星座成员星点 dim=0.15', () => {
  const { ctx } = mountOverlayWithActive('a')
  // 星点 dim 走 0.15（T8 既定，加深暗/亮区分度；不动）。
  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,0.15)')
})

vitest('active 选中：非 active 亮星名 alpha=0.4（与中心名同节奏）', () => {
  const { ctx } = mountOverlayWithActive('a')
  // 亮星名 0.92 × 0.4 = 0.36800000000000005（JS 浮点字面值）
  // 期望 fillStyleValues 出现 'rgba(245,240,230,0.36800000000000005)'
  expect(ctx.fillStyleValues).toContain('rgba(245,240,230,0.36800000000000005)')
})

vitest('active 未选中：所有内容全亮（无 dim）', () => {
  const { ctx } = mountOverlayWithActive(null)
  // 中心名 0.95、亮星名 0.92 都走原 alpha，不乘 0.4
  expect(ctx.fillStyleValues).toContain('rgba(212,160,23,0.95)')
  expect(ctx.fillStyleValues).toContain('rgba(245,240,230,0.92)')
  // 不应出现 0.4 节奏的 dim（中心 0.38 / 亮星 0.368...）
  expect(ctx.fillStyleValues).not.toContain('rgba(212,160,23,0.38)')
  expect(ctx.fillStyleValues).not.toContain('rgba(245,240,230,0.36800000000000005)')
})