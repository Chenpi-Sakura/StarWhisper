import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import type { ConstellationAtlas } from '../../src/types'

// ============= canvas / image stubs =============

let mockImageShouldFail = false
const FAKE_BLOB = new Blob(['fake-png-bytes'], { type: 'image/png' })

class MockImage {
  private _src = ''
  public onload: (() => void) | null = null
  public onerror: ((e: Event) => void) | null = null
  public width = 100
  public height = 100
  set src(v: string) {
    this._src = v
    queueMicrotask(() => {
      if (mockImageShouldFail) {
        this.onerror?.(new Event('error'))
      } else {
        this.onload?.()
      }
    })
  }
  get src() { return this._src }
}

const fakeCtx = {
  fillRect: vi.fn(),
  fillText: vi.fn(),
  fill: vi.fn(),  // drawStarMap 亮星晕圈 + 点本身
  strokeRect: vi.fn(),
  stroke: vi.fn(),
  beginPath: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  drawImage: vi.fn(),
  measureText: vi.fn().mockReturnValue({ width: 50 }),
  arc: vi.fn(),
  globalAlpha: 1,
  fillStyle: '',
  strokeStyle: '',
  font: '',
  textAlign: '',
  textBaseline: '',
  lineWidth: 0,
  lineCap: '',
} as unknown as CanvasRenderingContext2D

beforeEach(() => {
  mockImageShouldFail = false
  vi.stubGlobal('Image', MockImage as unknown as typeof Image)

  // jsdom 25 HTMLCanvasElement.getContext() returns null；toBlob 不存在。
  // stub 出 fake context + fake toBlob，使组件能跑完 generateBlob。
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(fakeCtx)
  HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation(
    (cb: (b: Blob | null) => void) => { cb(FAKE_BLOB) },
  )
})

function mkConstellation(): ConstellationAtlas {
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
    },
  } as ConstellationAtlas
}

async function mountCard(over: { showShareCard?: boolean; intro?: string; constellation?: ConstellationAtlas } = {}) {
  const AtlasShareCard = (await import('../../src/components/atlas/AtlasShareCard.vue')).default
  return mount(AtlasShareCard, {
    props: {
      constellation: over.constellation ?? mkConstellation(),
      intro: over.intro ?? '猎户座是冬季星空的主宰。',
      showShareCard: over.showShareCard ?? false,
    },
  })
}

// ============= 测试 =============

describe('AtlasShareCard · 离屏渲染器', () => {
  it('showShareCard false→true 触发下载流程', async () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL')

    const w = await mountCard({ showShareCard: false })
    await w.setProps({ showShareCard: true })
    await flushPromises()

    // URL.createObjectURL 被调，revokeObjectURL 在 setTimeout(1000) 后被调
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
    expect(createObjectURLSpy.mock.calls[0][0]).toBe(FAKE_BLOB)

    // revokeObjectURL 不立刻执行（setTimeout 1000ms）；测试不强制验证
    void revokeSpy
  })

  it('下载文件名 = {tradition}-{abbr}-nota.png', async () => {
    let capturedDownload = ''
    const originalCreate = document.createElement.bind(document)
    const createSpy = vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = originalCreate(tag)
      if (tag === 'a') {
        Object.defineProperty(el, 'download', {
          set(v: string) { capturedDownload = v },
          get() { return capturedDownload },
        })
      }
      return el
    }) as typeof document.createElement)

    const w = await mountCard()
    await w.setProps({ showShareCard: true })
    await flushPromises()

    expect(capturedDownload).toBe('western-ori-nota.png')
    createSpy.mockRestore()
  })

  it('canvas 尺寸 800×1300 ±5px（commit K：字号加大、高度从 1100 增到 1300）', async () => {
    let capturedW = 0
    let capturedH = 0
    // 通过 spy on canvas 创建
    const originalCreate = document.createElement.bind(document)
    const createSpy = vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = originalCreate(tag)
      if (tag === 'canvas') {
        Object.defineProperty(el, 'width', { set(v: number) { capturedW = v }, get() { return capturedW } })
        Object.defineProperty(el, 'height', { set(v: number) { capturedH = v }, get() { return capturedH } })
      }
      return el
    }) as typeof document.createElement)

    const w = await mountCard()
    await w.setProps({ showShareCard: true })
    await flushPromises()

    expect(capturedW).toBeGreaterThanOrEqual(795)
    expect(capturedW).toBeLessThanOrEqual(805)
    expect(capturedH).toBeGreaterThanOrEqual(1295)
    expect(capturedH).toBeLessThanOrEqual(1305)

    createSpy.mockRestore()
  })

  it('intro 为空 → 仍能生成 Blob，不抛错', async () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL')
    const w = await mountCard({ intro: '' })
    await w.setProps({ showShareCard: true })
    await flushPromises()

    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
    expect(createObjectURLSpy.mock.calls[0][0]).toBe(FAKE_BLOB)
  })

  it('QR 加载失败 → 仍能下载（占位块代替）', async () => {
    mockImageShouldFail = true
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL')
    const fillTextSpy = vi.spyOn(fakeCtx, 'fillText')

    const w = await mountCard()
    await w.setProps({ showShareCard: true })
    await flushPromises()

    // 仍下载
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
    // 在 canvas 上画了「（二维码暂不可用）」
    const hasUnavailable = fillTextSpy.mock.calls.some(
      (call) => typeof call[0] === 'string' && call[0].includes('二维码暂不可用'),
    )
    expect(hasUnavailable).toBe(true)
  })

  it('完成后 emit done 事件', async () => {
    const w = await mountCard()
    await w.setProps({ showShareCard: true })
    await flushPromises()
    expect(w.emitted('done')).toBeTruthy()
    expect(w.emitted('done')!.length).toBeGreaterThanOrEqual(1)
  })

  it('toBlob 返回 null 时 emit error', async () => {
    // 临时把 toBlob 改成返回 null
    const originalToBlob = HTMLCanvasElement.prototype.toBlob
    HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation(
      (cb: (b: Blob | null) => void) => { cb(null) },
    ) as typeof HTMLCanvasElement.prototype.toBlob

    const w = await mountCard()
    await w.setProps({ showShareCard: true })
    await flushPromises()

    expect(w.emitted('error')).toBeTruthy()
    expect((w.emitted('error')![0] as string[])[0]).toContain('toBlob')

    HTMLCanvasElement.prototype.toBlob = originalToBlob
  })

  it('showShareCard 初始 true 时仍触发下载（immediate watch 修复）', async () => {
    // 原需求是 v-if+watch 场景下不丢下载：AtlasNota 用 v-if="showShareCard" 挂载，组件 mount 时
    // props.showShareCard 已是 true。仅看 transition 不会 fire，所以加 immediate:true。
    // 本测试仅校验 immediate 场景下的下载被触发；AtlasNota 集成场景见 AtlasNota.test.ts。
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake')
    const w = await mountCard({ showShareCard: true })
    await flushPromises()
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
  })
})