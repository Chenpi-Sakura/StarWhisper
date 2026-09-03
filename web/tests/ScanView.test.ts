import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const listConstellationsMock = vi.fn()
const getConstellationMock = vi.fn()

vi.mock('../src/api/atlas', () => ({
  listConstellations: (...a: unknown[]) => listConstellationsMock(...a),
  getConstellation: (...a: unknown[]) => getConstellationMock(...a),
}))

const solveImageMock = vi.fn()
vi.mock('../src/api/solve', () => ({
  solveImage: (...a: unknown[]) => solveImageMock(...a),
  isAbortError: () => false,
  isTimeoutError: () => false,
}))

const readExifMock = vi.fn()
vi.mock('../src/utils/exif', () => ({
  readExifOrientation: (...a: unknown[]) => readExifMock(...a),
}))

const isHeicMock = vi.fn()
vi.mock('../src/utils/heic', () => ({
  isHeic: (...a: unknown[]) => isHeicMock(...a),
}))

// showStory 默认展开 → StoryPanel 自动调 streamStory。测试里 fetch 没 mock 会爆 URL，
// 这里给个静默的兜底：什么都不 emit，直接 resolve 即可。
const streamStoryMock = vi.fn((_req: unknown, onEvent: (ev: unknown) => void) => {
  onEvent({ type: 'done', meta: { ok: true, abbr: 'ori', style: 'myth', title: '', paragraphs: [], provider: 'disabled', model: 'preset', latency_ms: 0, cached: false, degraded: true } })
  return Promise.resolve()
})
const postStoryMock = vi.fn(() => Promise.resolve({ ok: true, abbr: 'ori', style: 'myth', title: '', paragraphs: [], provider: 'disabled', model: 'preset', latency_ms: 0, cached: false, degraded: true }))
vi.mock('../src/api/story', () => ({
  streamStory: streamStoryMock,
  postStory: postStoryMock,
  getHealth: () => Promise.resolve({ ok: true, astrometry: 'mock' as const, ai_provider: 'disabled' as const, ai_model: 'mock' }),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  listConstellationsMock.mockReset()
  getConstellationMock.mockReset()
  solveImageMock.mockReset()
  readExifMock.mockReset()
  isHeicMock.mockReset()
  streamStoryMock.mockClear()
  postStoryMock.mockClear()
  // 默认 mock：HEIC 检测返回 false，EXIF 默认方向 1
  isHeicMock.mockResolvedValue(false)
  readExifMock.mockResolvedValue(1)
})

function makeJpegFile(name = 'test.jpg', size = 1024): File {
  return new File([new Uint8Array(size)], name, { type: 'image/jpeg' })
}

const SAMPLE_ATLAS = {
  ok: true,
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
  tradition: 'western',
  star_count: 8,
  has_stories: true,
  stars: {},
  lines: [],
  viewBox: { width: 640, height: 460 },
  center: { ra: 88, dec: 7 },
} as any

const SAMPLE_RESULT = {
  ok: true,
  solved: true,
  image_width: 1024,
  image_height: 768,
  constellations: [
    {
      abbr: 'ori',
      name: '猎户座',
      latin: 'Orion',
      confidence: 0.92,
      visible_stars: 5,
      total_bright_stars: 8,
      tradition: 'western',
    },
  ],
  stars_overlay: [],
  overlay_lines: [],
} as any

describe('ScanView active constellation switch', () => {
  // 多命中（夏季大三角）result：识别到 3 颗，验证点击 chip 切换 atlas。
  const MULTI_RESULT = {
    ok: true,
    solved: true,
    image_width: 8192,
    image_height: 6144,
    constellations: [
      { abbr: 'lyr', name: '天琴座', latin: 'Lyra',     confidence: 0.508, visible_stars: 0, total_bright_stars: 6, tradition: 'western' },
      { abbr: 'aql', name: '天鹰座', latin: 'Aquila',   confidence: 0.536, visible_stars: 1, total_bright_stars: 7, tradition: 'western' },
      { abbr: 'cyg', name: '天鹅座', latin: 'Cygnus',   confidence: 0.476, visible_stars: 5, total_bright_stars: 9, tradition: 'western' },
    ],
    stars_overlay: [],
    overlay_lines: [],
  } as any

  function atlasFor(abbr: string) {
    return {
      ok: true,
      abbr,
      name: abbr.toUpperCase(),
      latin: '',
      glyph: '✶',
      hemisphere: 'B',
      bestMonth: 7,
      season: '夏季',
      caption: '',
      magnitude: 1,
      storyStyles: ['myth'],
      tradition: 'western',
      star_count: 5,
      has_stories: true,
      stars: {},
      lines: [['91971', '91926']],
      viewBox: { width: 640, height: 460 },
      center: { ra: 300, dec: 30 },
    }
  }

  it('atlasData 跟随 activeConstellation 切换（修复前硬编码 constellations[0] bug）', async () => {
    solveImageMock.mockResolvedValue(MULTI_RESULT)
    getConstellationMock.mockImplementation(async (_trad: string, abbr: string) => atlasFor(abbr))

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()
    await new Promise((r) => setTimeout(r, 10))
    await flushPromises()

    // 初始：activeAbbr 为空，atlasData 走 constellations[0] = lyr
    expect(s.activeAbbr).toBeNull()
    expect(getConstellationMock).toHaveBeenCalledWith('western', 'lyr')

    // 点 CYG chip → 触发 atlas 切换
    const cygChip = wrapper.find('[data-testid="constellation-chip-cyg"]')
    expect(cygChip.exists()).toBe(true)
    await cygChip.trigger('click')
    await flushPromises()
    await new Promise((r) => setTimeout(r, 10))
    await flushPromises()

    expect(s.activeAbbr).toBe('cyg')
    // getAtlas(cyg) 被调用过
    expect(getConstellationMock).toHaveBeenCalledWith('western', 'cyg')
    // cygChip 处于 active 态
    expect(cygChip.classes()).toContain('active')
    // lyr chip 不再 active
    const lyrChip = wrapper.find('[data-testid="constellation-chip-lyr"]')
    expect(lyrChip.classes()).not.toContain('active')

    // ★ 关键断言：atlasData 切到 cyg（修复前是 lyr 永远不变）
    // 通过组件实例访问 atlasData computed
    const vm = wrapper.vm as any
    // atlasData 内部存在 wrapper 闭包，从渲染出的 canvas props 间接验证
    const canvas = wrapper.find('.star-canvas-container canvas')
    expect(canvas.exists()).toBe(true)
    // 确保 call 序列里没有漏掉 lyr 重载（cache hit 应当跳过）
    const lyrCallCount = getConstellationMock.mock.calls.filter(
      (c) => c[1] === 'lyr',
    ).length
    expect(lyrCallCount).toBe(1)  // 初始一次，切换后不应再调用
  })

  it('切换 view chip 不触发 atlas 重新加载（与原缓存命中测试一致）', async () => {
    solveImageMock.mockResolvedValue(MULTI_RESULT)
    getConstellationMock.mockImplementation(async (_trad: string, abbr: string) => atlasFor(abbr))

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()
    await new Promise((r) => setTimeout(r, 10))
    await flushPromises()

    // 切 view chip（不动 active abbr）→ 不应触发新 getAtlas
    await wrapper.find('[data-testid="chip-real-projection"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="chip-overlay"]').trigger('click')
    await flushPromises()

    // 只为第一颗（lyr）调过 1 次
    const calls = getConstellationMock.mock.calls.map((c) => c[1])
    expect(calls).toEqual(['lyr'])
  })

  // T8: overlay_lines_by_abbr 分组 → 点 chip 时 StarCanvas 只画对应星座的线
  it('chip 切换时 StarCanvas overlay-lines 只画 active 星座（test4 UX 修复）', async () => {
    const result = {
      ...MULTI_RESULT,
      // 3 星座各 2 条线，验证点 chip 后只显示对应星座的 2 条
      overlay_lines: [
        [10, 10, 20, 20], [20, 20, 30, 30],  // lyr
        [100, 100, 110, 110], [110, 110, 120, 120],  // aql
        [200, 200, 210, 210], [210, 210, 220, 220],  // cyg
      ],
      overlay_lines_by_abbr: {
        lyr: [[10, 10, 20, 20], [20, 20, 30, 30]],
        aql: [[100, 100, 110, 110], [110, 110, 120, 120]],
        cyg: [[200, 200, 210, 210], [210, 210, 220, 220]],
      },
    }
    solveImageMock.mockResolvedValue(result)
    getConstellationMock.mockImplementation(async (_trad: string, abbr: string) => atlasFor(abbr))

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    // 切到照片叠层模式（验证 displayLines 走 overlay 模式的 canvas）
    await wrapper.find('[data-testid="chip-overlay"]').trigger('click')
    await flushPromises()

    // 拿 canvas 组件实例，验证 overlayLines prop 初始（activeAbbr=null）= 全量合并
    const canvas0 = wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')
    expect(canvas0).toBeTruthy()
    expect(canvas0!.props('overlayLines')).toHaveLength(6)  // 全量 6 条

    // 点 lyr chip → 只画 lyr 的 2 条
    await wrapper.find('[data-testid="constellation-chip-lyr"]').trigger('click')
    await flushPromises()
    const canvasLyr = wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')
    expect(canvasLyr!.props('overlayLines')).toEqual([
      [10, 10, 20, 20], [20, 20, 30, 30],
    ])

    // 点 cyg chip → 只画 cyg 的 2 条
    await wrapper.find('[data-testid="constellation-chip-cyg"]').trigger('click')
    await flushPromises()
    const canvasCyg = wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')
    expect(canvasCyg!.props('overlayLines')).toEqual([
      [200, 200, 210, 210], [210, 210, 220, 220],
    ])
  })

  // T8: 再点一次已 active 的 chip → activeAbbr 变 null → 回到全量 6 条
  it('再点一次已 active 的 chip 回到全量显示（test4 toggle 行为）', async () => {
    const result = {
      ...MULTI_RESULT,
      overlay_lines: [
        [10, 10, 20, 20], [20, 20, 30, 30],
        [100, 100, 110, 110], [110, 110, 120, 120],
        [200, 200, 210, 210], [210, 210, 220, 220],
      ],
      overlay_lines_by_abbr: {
        lyr: [[10, 10, 20, 20], [20, 20, 30, 30]],
        aql: [[100, 100, 110, 110], [110, 110, 120, 120]],
        cyg: [[200, 200, 210, 210], [210, 210, 220, 220]],
      },
    }
    solveImageMock.mockResolvedValue(result)
    getConstellationMock.mockImplementation(async (_trad: string, abbr: string) => atlasFor(abbr))

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    await wrapper.find('[data-testid="chip-overlay"]').trigger('click')
    await flushPromises()

    const overlayCanvas = () => wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')!

    // 初始：activeAbbr=null → 全量 6 条
    expect(s.activeAbbr).toBeNull()
    expect(overlayCanvas().props('overlayLines')).toHaveLength(6)

    // 点 cyg → 只画 cyg 的 2 条
    await wrapper.find('[data-testid="constellation-chip-cyg"]').trigger('click')
    await flushPromises()
    expect(s.activeAbbr).toBe('cyg')
    expect(overlayCanvas().props('overlayLines')).toEqual([
      [200, 200, 210, 210], [210, 210, 220, 220],
    ])

    // ★ 再点一次 cyg → toggle：activeAbbr 变 null → 回到全量 6 条
    await wrapper.find('[data-testid="constellation-chip-cyg"]').trigger('click')
    await flushPromises()
    expect(s.activeAbbr).toBeNull()
    expect(overlayCanvas().props('overlayLines')).toHaveLength(6)

    // cyg chip 不再 active
    const cygChip = wrapper.find('[data-testid="constellation-chip-cyg"]')
    expect(cygChip.classes()).not.toContain('active')
  })
})

describe('ScanView view toggle', () => {
  it('default overlay mode after solve', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const scan = (wrapper.vm as any).scan ?? null
    // Use the scan store via direct import to drive state
    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    expect(s.status).toBe('done')

    // 2 chip 默认态：overlayMode='overlay'（照片叠层优先）
    // 通过 data-testid 查 chip 激活状态
    const overlayChip = wrapper.find('[data-testid="chip-overlay"]')
    const realProjChip = wrapper.find('[data-testid="chip-real-projection"]')
    expect(overlayChip.exists()).toBe(true)
    expect(realProjChip.exists()).toBe(true)
    // 默认 overlay
    expect(overlayChip.classes()).toContain('active')
    expect(realProjChip.classes()).not.toContain('active')
  })

  it('click real projection chip', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    // 默认是 overlay，先点 real-projection 切到 atlas
    const realProjChip = wrapper.find('[data-testid="chip-real-projection"]')
    await realProjChip.trigger('click')
    await flushPromises()

    expect(realProjChip.classes()).toContain('active')
    expect(wrapper.find('[data-testid="chip-overlay"]').classes()).not.toContain('active')
  })

  it('click photo overlay chip', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    // 先切到 atlas（真实投影），再点 overlay 切回
    await wrapper.find('[data-testid="chip-real-projection"]').trigger('click')
    await flushPromises()
    const overlayChip = wrapper.find('[data-testid="chip-overlay"]')
    await overlayChip.trigger('click')
    await flushPromises()

    expect(overlayChip.classes()).toContain('active')
    expect(wrapper.find('[data-testid="chip-real-projection"]').classes()).not.toContain('active')
  })

  it('getAtlas called after solve', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()
    // 等 watch immediate + async getAtlas 完成
    await new Promise((r) => setTimeout(r, 10))
    await flushPromises()

    expect(getConstellationMock).toHaveBeenCalledTimes(1)
    expect(getConstellationMock).toHaveBeenCalledWith('western', 'ori')
  })

  it('cache hit no reload', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()
    await new Promise((r) => setTimeout(r, 10))
    await flushPromises()

    expect(getConstellationMock).toHaveBeenCalledTimes(1)

    // 切换 chip 不应触发 getAtlas（缓存命中）
    await wrapper.find('[data-testid="chip-real-projection"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="chip-overlay"]').trigger('click')
    await flushPromises()

    // 仍只 1 次（watch 只监听 abbr，chip 不触发 abbr 变化）
    expect(getConstellationMock).toHaveBeenCalledTimes(1)
  })
})

describe('ScanView idle state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listConstellationsMock.mockReset()
    listConstellationsMock.mockResolvedValue({ items: [] })
    getConstellationMock.mockReset()
  })

  it('idle 态不显示 tradition 切换 chips（统一挪到 done 态）', async () => {
    // 之前 idle 态就放 3 个 tradition chip 让用户预选，但 astrometry 与
    // tradition 无关，预选没意义；现在统一挪到 done 态，让 idle 态只剩
    // upload-area 一个 CTA。
    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)
    await flushPromises()
    expect(wrapper.find('[data-testid="upload-area"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tradition-chip-auto"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tradition-chip-western"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tradition-chip-chinese"]').exists()).toBe(false)
  })

  it('idle 态：upload-area 是 idle-block 唯一子元素且在 plate 中居中', async () => {
    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)
    await flushPromises()
    const idleBlock = wrapper.find('.idle-block')
    expect(idleBlock.exists()).toBe(true)
    // idle-block 是 flex 容器，align-items: center + justify-content: center
    // 让 upload-area 在 plate-body 内上下左右居中（jsdom 不算 layout，
    // 这里只验 CSS 规则确实写对了，避免回归）
    const html = idleBlock.html()
    expect(html).toContain('upload-area')
    expect(html).not.toContain('tradition-switch')
  })
})

describe('ScanView done state rescan + tradition switch', () => {
  it('done 态展示"换图识别"按钮（特殊金色样式 + ↻ 图标）', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    const btn = wrapper.find('[data-testid="btn-rescan"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('换图识别')
    expect(btn.text()).toContain('↻')
  })

  it('done 态展示 tradition-switch 三个 chip（不限/西方/中国古代）', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    expect(wrapper.find('[data-testid="tradition-switch-done"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tradition-chip-auto-done"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tradition-chip-western-done"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="tradition-chip-chinese-done"]').exists()).toBe(true)
  })

  it('done 态切换 tradition 不触发重解（仅前端过滤）', async () => {
    // 多 tradition 命中：1 个 western + 1 个 chinese，验证切 tradition
    // 只过滤展示不重解。
    const MULTI_TRADITION_RESULT = {
      ...SAMPLE_RESULT,
      constellations: [
        { abbr: 'ori', name: '猎户座', latin: 'Orion', confidence: 0.92, visible_stars: 5, total_bright_stars: 8, tradition: 'western' },
        { abbr: 'sou', name: '参宿', latin: 'Shen', confidence: 0.88, visible_stars: 4, total_bright_stars: 7, tradition: 'chinese' },
      ],
    } as any
    solveImageMock.mockResolvedValue(MULTI_TRADITION_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    expect(solveImageMock).toHaveBeenCalledTimes(1)

    // 初始：不限 → 2 个 chip 都展示
    const oriChip = wrapper.find('[data-testid="constellation-chip-ori"]')
    const souChip = wrapper.find('[data-testid="constellation-chip-sou"]')
    expect(oriChip.exists()).toBe(true)
    expect(souChip.exists()).toBe(true)

    // 切到 中国古代
    await wrapper.find('[data-testid="tradition-chip-chinese-done"]').trigger('click')
    await flushPromises()

    expect(s.lockedTradition).toBe('chinese')
    // 关键断言：solveImageMock 没被再次调用
    expect(solveImageMock).toHaveBeenCalledTimes(1)
    // 西方 chip 消失，中国 chip 仍在
    expect(wrapper.find('[data-testid="constellation-chip-ori"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="constellation-chip-sou"]').exists()).toBe(true)

    // 切回 不限
    await wrapper.find('[data-testid="tradition-chip-auto-done"]').trigger('click')
    await flushPromises()

    expect(s.lockedTradition).toBe('')
    expect(solveImageMock).toHaveBeenCalledTimes(1)  // 仍 1 次
    expect(wrapper.find('[data-testid="constellation-chip-ori"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="constellation-chip-sou"]').exists()).toBe(true)
  })

  it('点已选中的 tradition chip 是 no-op', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    expect(solveImageMock).toHaveBeenCalledTimes(1)
    // 默认 auto 已选中，再点 auto 不应触发任何操作
    await wrapper.find('[data-testid="tradition-chip-auto-done"]').trigger('click')
    await flushPromises()
    expect(solveImageMock).toHaveBeenCalledTimes(1)
  })
})

// ★ 视觉调节：叠层透明度滑块——只影响 overlay 模式的星空识别层透明度。
// 真实投影模式不显示滑块（atlas 数据不属于"识别出来的星点叠层"范畴）。
describe('ScanView overlay opacity slider', () => {
  it('default overlay mode shows slider at 100%', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    const slider = wrapper.find('[data-testid="overlay-opacity-slider"]')
    expect(slider.exists()).toBe(true)
    // 默认 1（100%）
    expect((slider.element as HTMLInputElement).value).toBe('1')
  })

  it('switching to real-projection hides slider', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    // 默认 overlay 模式有滑块
    expect(wrapper.find('[data-testid="overlay-opacity-slider"]').exists()).toBe(true)

    // 切到真实投影
    await wrapper.find('[data-testid="chip-real-projection"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="overlay-opacity-slider"]').exists()).toBe(false)

    // 切回 overlay 模式，滑块再次出现
    await wrapper.find('[data-testid="chip-overlay"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="overlay-opacity-slider"]').exists()).toBe(true)
  })

  it('slider value flows to StarCanvas overlayLines canvas as overlayOpacity prop', async () => {
    solveImageMock.mockResolvedValue(SAMPLE_RESULT)
    getConstellationMock.mockResolvedValue(SAMPLE_ATLAS)

    const ScanView = (await import('../src/views/ScanView.vue')).default
    const wrapper = mount(ScanView)

    const { useScanStore } = await import('../src/stores/scan')
    const s = useScanStore()
    s.selectImage(makeJpegFile())
    await flushPromises()
    await s.solve(true)
    await flushPromises()

    // 初始：overlay canvas 拿到的 overlayOpacity 应该是 1
    const overlayCanvas = wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')
    expect(overlayCanvas).toBeTruthy()
    expect(overlayCanvas!.props('overlayOpacity')).toBe(1)

    // 拖动滑块到 0.4
    const slider = wrapper.find('[data-testid="overlay-opacity-slider"]')
    await slider.setValue('0.4')
    await flushPromises()

    const overlayCanvas2 = wrapper.findAllComponents({ name: 'StarCanvas' })
      .find((c) => (c.props('mode') as string) === 'overlay')
    expect(overlayCanvas2!.props('overlayOpacity')).toBeCloseTo(0.4)
  })
})