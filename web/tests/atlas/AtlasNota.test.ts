import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import type { ConstellationAtlas } from '../../src/types'

// ============= stream mock =============

/** 仿 streamAtlasNota 行为：调用 onEvent 模拟字符级 SSE。 */
const streamAtlasNotaMock = vi.fn()
vi.mock('../../src/api/atlasNota', () => ({
  fetchAtlasNota: (...args: unknown[]) => streamAtlasNotaMock(...args),
  streamAtlasNota: (...args: unknown[]) => streamAtlasNotaMock(...args),
  ATLAS_NOTA_STREAM_TIMEOUT_MS: 60_000,
}))

/** 模拟 AI 逐字 yield：把 intro 拆成 4 字一块，依次调 onEvent('char') + onEvent('done')。 */
function makeStreamFromIntro(
  intro: string,
  meta: { ok: boolean; tradition: string; abbr: string; degraded: boolean; source: string } = {
    ok: true, tradition: 'western', abbr: 'ori', degraded: false, source: 'agentarts',
  },
) {
  return (req: unknown, onEvent: (ev: unknown) => void) => {
    for (let i = 0; i < intro.length; i += 4) {
      onEvent({ type: 'char', char: intro.slice(i, i + 4) })
    }
    onEvent({ type: 'done', meta: { ...meta, intro } })
  }
}

// ============= helpers =============

function mkConstellation(over: Partial<ConstellationAtlas> = {}): ConstellationAtlas {
  return {
    abbr: 'ori',
    name: '猎户座',
    latin: 'Orion',
    glyph: '⍺',
    hemisphere: 'B',
    season: '冬季',
    caption: '冬夜之王',
    bright_stars: 7,
    tradition: 'western',
    stars: {
      a: { x: 0, y: 0, bayer: '⍺', name: 'Betelgeuse', name_zh: '参宿四', magnitude: 0.42 },
      b: { x: 0, y: 0, bayer: 'β', name: 'Rigel', name_zh: '参宿七', magnitude: 0.13 },
      c: { x: 0, y: 0, bayer: 'γ', name: 'Bellatrix', name_zh: '参宿五', magnitude: 1.64 },
      d: { x: 0, y: 0, bayer: 'δ', name: '', name_zh: '', magnitude: 5.0 },
    },
    ...over,
  } as ConstellationAtlas
}

async function mountNota(c: ConstellationAtlas) {
  const AtlasNota = (await import('../../src/components/atlas/AtlasNota.vue')).default
  const wrapper = mount(AtlasNota, { props: { constellation: c } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  streamAtlasNotaMock.mockReset()
  // 默认：按"猎户座..."全文逐字 yield + done
  streamAtlasNotaMock.mockImplementation(
    makeStreamFromIntro('猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道。'),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ============= § 渲染与数据绑定 =============

describe('AtlasNota · 渲染', () => {
  it('渲染 3 段（你是谁 + 怎么找你 + 星座简介）', async () => {
    const w = await mountNota(mkConstellation())
    expect(w.text()).toContain('你是谁')
    expect(w.text()).toContain('怎么找你')
    expect(w.text()).toContain('星座简介')
    expect(w.text()).toContain('猎户座')
    expect(w.text()).toContain('Orion')
  })

  it('你是谁 chip 缺字段时降级（season 缺失则不显）', async () => {
    const c = mkConstellation({ season: undefined })
    const w = await mountNota(c)
    expect(w.text()).not.toContain('当令')
    // 但其他 chip 仍在（mkConstellation 默认 hemisphere='B' → 跨天球）
    expect(w.text()).toContain('拜耳')
    expect(w.text()).toContain('跨天球')
    expect(w.text()).toContain('最亮')
  })

  it('你是谁 chip 全字段缺失时不渲染 chip 区', async () => {
    const c = mkConstellation({
      season: undefined,
      hemisphere: undefined,
      glyph: undefined,
      bright_stars: undefined,
    })
    const w = await mountNota(c)
    expect(w.findAll('.nota-chips')).toHaveLength(0)
    expect(w.text()).toContain('该星座信息暂未补全')
  })

  it('怎么找你按 magnitude 升序截前 3 颗', async () => {
    const w = await mountNota(mkConstellation())
    const items = w.findAll('.nota-list li')
    // 3 颗亮星 + 中西对照 = 4
    expect(items.length).toBeGreaterThanOrEqual(3)
    // 第 1 颗应是 Rigel (0.13ᵐ)
    expect(items[0].text()).toContain('Rigel')
    expect(items[0].text()).toContain('0.1ᵐ')
    // 第 2 颗 Betelgeuse (0.42ᵐ)
    expect(items[1].text()).toContain('Betelgeuse')
    // 第 3 颗 Bellatrix (1.64ᵐ)
    expect(items[2].text()).toContain('Bellatrix')
    // 第 4 颗 stars.d（magnitude 5）不在前 3
    expect(w.text()).not.toContain('星等 5.0')
  })

  it('中西对照仅在有差异的 name_zh 时显示', async () => {
    // 全部 stars 的 name_zh === name → 不显中西对照
    const c = mkConstellation({
      stars: {
        a: { x: 0, y: 0, name: 'Foo', name_zh: 'Foo', magnitude: 1 },
        b: { x: 0, y: 0, name: 'Bar', name_zh: 'Bar', magnitude: 2 },
      },
    })
    const w = await mountNota(c)
    expect(w.text()).not.toContain('中西对照')
  })

  it('中西对照去重收集不同 name_zh', async () => {
    // 2 颗星 name_zh 都是「参宿」 → 只出现一次
    const c = mkConstellation({
      stars: {
        a: { x: 0, y: 0, name: 'Betelgeuse', name_zh: '参宿四', magnitude: 1 },
        b: { x: 0, y: 0, name: 'Rigel', name_zh: '参宿七', magnitude: 2 },
      },
    })
    const w = await mountNota(c)
    const items = w.findAll('.nota-list li')
    const refLine = items.find((li) => li.text().includes('中西对照'))
    expect(refLine).toBeTruthy()
    // 参宿四 和 参宿七 都出现一次
    expect(refLine!.text()).toContain('参宿四')
    expect(refLine!.text()).toContain('参宿七')
  })

  it('怎么找你字段全空显兜底文案', async () => {
    const c = mkConstellation({ stars: {} })
    const w = await mountNota(c)
    expect(w.text()).toContain('请打开夜空')
    expect(w.findAll('.nota-list')).toHaveLength(0)
  })
})

// ============= § 星座简介 · 状态机 =============

describe('AtlasNota · 星座简介 状态机', () => {
  it('idle 态显示「✦ 讲讲这个星座」按钮（无「点一下」提示文案）', async () => {
    const w = await mountNota(mkConstellation())
    expect(w.find('[data-testid="nota-btn-generate"]').exists()).toBe(true)
    // commit L 删除了“点一下，让 AgentArts 给你讲讲 …”的提示文案
    expect(w.text()).not.toContain('点一下')
  })

  it('点击按钮 → loading → ready（stream 逐字流入）', async () => {
    // 主动控制何时调 onEvent，方便断言 loading 阶段
    let fireNext!: (ev: unknown) => void
    streamAtlasNotaMock.mockImplementation((_req: unknown, onEvent: (ev: unknown) => void) => {
      fireNext = onEvent
    })

    const w = await mountNota(mkConstellation())
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await nextTick()
    // loading 态：原按钮被「✦ 正在讲述…」替代
    expect(w.text()).toContain('正在讲述')
    expect(w.find('[data-testid="nota-btn-generate"]').exists()).toBe(false)

    // 逐字推入 4 段 char
    for (const ch of ['猎户座', '，', '冬季', '星空的主宰。']) {
      fireNext({ type: 'char', char: ch })
    }
    await flushPromises()
    // streaming 时应能看到部分字符（data-testid="nota-intro-streaming"）
    expect(w.find('[data-testid="nota-intro-streaming"]').exists()).toBe(true)
    expect(w.find('[data-testid="nota-intro-streaming"]').text()).toContain('冬季')

    // 发 done
    fireNext({ type: 'done', meta: {
      ok: true, tradition: 'western', abbr: 'ori',
      intro: '猎户座，冬季星空的主宰。', degraded: false, source: 'agentarts',
    } })
    await flushPromises()
    expect(w.find('[data-testid="nota-intro-body"]').text()).toContain('冬季星空的主宰')
    expect(w.text()).toContain('Agent Arts')
    expect(w.find('[data-testid="nota-relink"]').exists()).toBe(true)
  })

  it('AI 失败 → error 态显降级文字 + 重试按钮', async () => {
    streamAtlasNotaMock.mockImplementation(() => { throw new Error('HTTP 500') })
    const w = await mountNota(mkConstellation())
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('暂无法访问 AI')
    // 重试按钮（StarBtn ghost variant）
    const retryBtns = w.findAll('button')
    const retry = retryBtns.find((b) => b.text().includes('重试'))
    expect(retry).toBeTruthy()
  })

  it('degraded:true 时署名显示「AI 暂不可用，降级」', async () => {
    streamAtlasNotaMock.mockImplementation((_req: unknown, onEvent: (ev: unknown) => void) => {
      onEvent({ type: 'char', char: '冬夜之王。' })
      onEvent({ type: 'done', meta: {
        ok: true, tradition: 'western', abbr: 'ori',
        intro: '冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。',
        degraded: true, source: 'preset',
      } })
    })
    const w = await mountNota(mkConstellation())
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('AI 暂不可用，降级')
    expect(w.text()).not.toContain('Agent Arts')
  })

  it('「重新讲述」chip 在 ready 态点击会重发', async () => {
    streamAtlasNotaMock.mockImplementation(makeStreamFromIntro('初稿。'))
    const w = await mountNota(mkConstellation())
    // 触发第一次
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()
    expect(streamAtlasNotaMock).toHaveBeenCalledTimes(1)

    // 点重新讲述 chip
    const retellChip = w.findAll('button').find((b) => b.text().includes('重新讲述'))!
    expect(retellChip).toBeTruthy()
    await retellChip.trigger('click')
    await flushPromises()
    expect(streamAtlasNotaMock).toHaveBeenCalledTimes(2)
  })

  it('「重新讲述」chip 在 idle 态等价于讲讲按钮（也能触发）', async () => {
    const w = await mountNota(mkConstellation())
    expect(streamAtlasNotaMock).not.toHaveBeenCalled()
    const retellChip = w.findAll('button').find((b) => b.text().includes('重新讲述'))!
    await retellChip.trigger('click')
    await flushPromises()
    expect(streamAtlasNotaMock).toHaveBeenCalledTimes(1)
  })
})

// ============= § 底部 chip =============

describe('AtlasNota · 底部 chip 接线', () => {
  it('生成分享卡 chip 点击 → 触发下载流程（createObjectURL + <a>.click）', async () => {
    // jsdom 不提供 Canvas 2D + Image() 真实实现；stub 出伪造版本，让 AtlasShareCard 能跑完 download。
    // 修复背景：原 AtlasShareCard watch 只监听 false→true 变化，但 v-if="showShareCard" 是在值
    // 变 true 后才 mount 子组件——mount 时 props.showShareCard 已是 true，watch 不 fire，下载永远不触发。
    // 本测试在 AtlasShareCard 加 immediate watch 后才能走通：点击 chip → 挂载 → 立即调 download() →
    // createObjectURL 被调、<a>.click() 被调 → emit('done') → 组件随后卸载。
    const FAKE_BLOB = new Blob(['fake'], { type: 'image/png' })
    class FakeImg {
      private _src = ''
      public onload: (() => void) | null = null
      public onerror: (() => void) | null = null
      public width = 100; public height = 100
      set src(v: string) { this._src = v; queueMicrotask(() => this.onload?.()) }
      get src() { return this._src }
    }
    const fakeCtx = {
      fillRect: vi.fn(), fillText: vi.fn(), strokeRect: vi.fn(),
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      drawImage: vi.fn(), measureText: vi.fn().mockReturnValue({ width: 50 }),
      arc: vi.fn(), globalAlpha: 1,  // drawStarMap 亮星晕圈 + 点本身
      fill: vi.fn(),                // drawStarMap fill()
      fillStyle: '', strokeStyle: '', font: '', textAlign: '', textBaseline: '', lineWidth: 0, lineCap: '',
    } as unknown as CanvasRenderingContext2D
    vi.stubGlobal('Image', FakeImg as unknown as typeof Image)
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(fakeCtx)
    HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation(
      (cb: (b: Blob | null) => void) => { cb(FAKE_BLOB) },
    )
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake')
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    const w = await mountNota(mkConstellation())
    expect(w.find('[data-testid="atlas-share-card"]').exists()).toBe(false)
    const chip = w.findAll('button').find((b) => b.text().includes('生成分享卡'))!
    await chip.trigger('click')
    await flushPromises()

    // 下载被触发（关键断言）：createObjectURL 被调、<a>.click() 被调
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
    expect(createObjectURLSpy.mock.calls[0][0]).toBe(FAKE_BLOB)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    // 下载完成后 emit('done') → showShareCard=false → 组件卸载
    expect(w.find('[data-testid="atlas-share-card"]').exists()).toBe(false)
  })
})

// ============= § watch 行为 =============

describe('AtlasNota · 选中星座切换重置', () => {
  it('constellation prop 变化 → introState 自动重置为 idle', async () => {
    streamAtlasNotaMock.mockImplementation(makeStreamFromIntro('猎户座是冬季星空的主宰。'))
    const w = await mountNota(mkConstellation())
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="nota-intro-body"]').exists()).toBe(true)

    // 切换星座
    await w.setProps({ constellation: mkConstellation({ abbr: 'cyg', name: '天鹅座', latin: 'Cygnus' }) })
    await flushPromises()

    expect(w.find('[data-testid="nota-intro-body"]').exists()).toBe(false)
    expect(w.find('[data-testid="nota-btn-generate"]').exists()).toBe(true)
    // 不应有「猎户」文案（intro 已重置）
    expect(w.text()).not.toContain('冬季星空的主宰')
  })

  it('constellation.tradition 变化 → 也重置为 idle', async () => {
    streamAtlasNotaMock.mockImplementation(makeStreamFromIntro('Western 视角。'))
    const w = await mountNota(mkConstellation())
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()

    // 仅切换 tradition（不切换 abbr）
    await w.setProps({ constellation: mkConstellation({ tradition: 'chinese' }) })
    await flushPromises()
    expect(w.find('[data-testid="nota-btn-generate"]').exists()).toBe(true)
  })

  it('点击讲讲按钮时按 (abbr, tradition) 正确传入 streamAtlasNota', async () => {
    const w = await mountNota(mkConstellation({ abbr: 'cyg', tradition: 'western' }))
    await w.find('[data-testid="nota-btn-generate"]').trigger('click')
    await flushPromises()
    expect(streamAtlasNotaMock).toHaveBeenCalledWith(
      expect.objectContaining({ abbr: 'cyg', tradition: 'western', lang: 'zh' }),
      expect.any(Function),
      expect.anything(),
    )
  })
})