<script setup lang="ts">
/**
 * 图鉴页 · 生成分享卡（PNG）—— 离屏 Canvas 2D 渲染器
 *
 * 设计要点（见 docs/plans/2026-09-16-atlas-nota-ai.md §8）：
 * - 不渲染到视口（display: none），只持有逻辑状态；canvas 通过
 *   document.createElement 构造，用完即弃（toBlob 后可 GC）
 * - 不引第三方库（无 html2canvas / html-to-image），纯浏览器原生 Canvas 2D
 * - QR 图通过 new Image() 加载到内存再 drawImage，绝不显示在页面 DOM
 * - 配色与字体取全局 CSS 变量 + 字体 fallback 链（与页面视觉一致）
 * - 失败优雅降级：QR 加载失败 → footer 区画「（二维码暂不可用）」+ URL；toBlob null → emit 'error'
 *
 * Props/Emits：
 * - props.showShareCard  false→true  触发下载，完成后 emit('done')
 * - 失败时 emit('error', message)；调用方应监听并在 done/error 后将 showShareCard 重置回 false
 */

import { watch } from 'vue'
import type { ConstellationAtlas, Hemisphere } from '../../types'
import { wrapText } from '../../utils/textWrap'

const props = defineProps<{
  constellation: ConstellationAtlas
  intro: string
  showShareCard: boolean
}>()

const emit = defineEmits<{
  (e: 'done'): void
  (e: 'error', message: string): void
}>()

// ============= 配置 =============

const W = 800
const H = 1300
const QR_SIZE = 120
const QR_URL_TEXT = 'starwhisper.caipiischenpi.top'

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`image load failed: ${src}`))
    img.src = src
  })
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function hemisphereLabel(h?: Hemisphere): string | null {
  if (h === 'N') return '北天'
  if (h === 'S') return '南天'
  if (h === 'B') return '跨天球'
  return null
}

/** § 你是谁 文本行集合（含 chips 串成单行） */
function buildYouWhoLines(c: ConstellationAtlas): string[] {
  const parts: string[] = []
  if (c.season) parts.push(`当令 ${c.season}`)
  const hem = hemisphereLabel(c.hemisphere)
  if (hem) parts.push(hem)
  if (c.glyph) parts.push(`拜耳 ${c.glyph}`)
  if (c.bright_stars != null) parts.push(`最亮 ${c.bright_stars} 颗`)
  return parts.length ? [parts.join(' · ')] : []
}

/** § 怎么找你 文本行集合——旧实现，已由 drawStarMap Canvas 星图替代，函数已删除。 */

function drawSectionHeader(ctx: CanvasRenderingContext2D, label: string, y: number): void {
  const fontFamily = `'Source Han Serif SC', 'Noto Serif CJK SC', 'Songti SC', serif`
  const inkSoft = cssVar('--ink-soft', '#5c4b32')
  const gold = cssVar('--gold', '#a97e2f')
  const lineSoft = cssVar('--line-soft', 'rgba(46, 36, 23, 0.18)')

  ctx.font = `bold 18px ${fontFamily}`
  ctx.fillStyle = gold
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText(`— ${label} —`, 60, y)

  const tx = ctx.measureText(`— ${label} —`)
  ctx.strokeStyle = lineSoft
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(60 + tx.width + 16, y + 9)
  ctx.lineTo(W - 60, y + 9)
  ctx.stroke()

  // 用 inkSoft 保持 lint quiet
  void inkSoft
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** § 怎么找你 · Canvas 星图：连线 + 点大小随星等 + 亮星金色光晕。
 *
 *  复用 selected.stars / selected.lines / selected.viewBox 原始坐标——
 *  与 page 上的 StarCanvas “asterism” 模式逻辑一致。缩放为最贴合区域，保留纵横比。
 */
function drawStarMap(
  ctx: CanvasRenderingContext2D,
  c: ConstellationAtlas,
  areaX: number,
  areaY: number,
  areaW: number,
  areaH: number,
): void {
  const stars = Object.values(c.stars || {})
  if (stars.length === 0) {
    ctx.fillStyle = cssVar('--ink-soft', '#5c4b32')
    ctx.font = `italic 16px 'Source Han Serif SC', serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('该星座星图未补全', areaX + areaW / 2, areaY + areaH / 2)
    return
  }

  // 预留 8px 内边距（避免点画到边界外）
  const padX = 8
  const padY = 8
  const vbW = c.viewBox?.width ?? 700
  const vbH = c.viewBox?.height ?? 700
  const scale = Math.min(
    (areaW - padX * 2) / vbW,
    (areaH - padY * 2) / vbH,
  )
  const offsetX = areaX + (areaW - vbW * scale) / 2
  const offsetY = areaY + (areaH - vbH * scale) / 2

  const ink = cssVar('--ink', '#2e2417')
  const inkSoft = cssVar('--ink-soft', '#5c4b32')
  const gold = cssVar('--gold', '#a97e2f')
  const lineSoft = cssVar('--line-soft', 'rgba(46, 36, 23, 0.5)')

  // ---- 连线：先于点画，让点覆盖线的端点 ----
  if (c.lines && c.lines.length > 0) {
    ctx.strokeStyle = lineSoft
    ctx.lineWidth = 1.5
    ctx.lineCap = 'round'
    for (const [from, to] of c.lines) {
      const s1 = c.stars?.[from]
      const s2 = c.stars?.[to]
      if (!s1 || !s2) continue
      const x1 = offsetX + s1.x * scale
      const y1 = offsetY + s1.y * scale
      const x2 = offsetX + s2.x * scale
      const y2 = offsetY + s2.y * scale
      ctx.beginPath()
      ctx.moveTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.stroke()
    }
  }

  // ---- 点：半径 ∝ 亮度（magnitude 小→亮→大）----
  for (const s of stars) {
    if (!Number.isFinite(s.x) || !Number.isFinite(s.y)) continue
    const px = offsetX + s.x * scale
    const py = offsetY + s.y * scale
    // 亮星光晕（magnitude < 2.0）：金色软圈
    if (s.magnitude < 2.0) {
      ctx.fillStyle = gold
      ctx.globalAlpha = 0.25
      ctx.beginPath()
      ctx.arc(px, py, 9, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1.0
    }
    // 点本身
    const r = Math.max(2, 7.5 - s.magnitude * 1.3)
    ctx.fillStyle = s.magnitude < 2.5 ? ink : inkSoft
    ctx.beginPath()
    ctx.arc(px, py, r, 0, Math.PI * 2)
    ctx.fill()
  }
}

async function generateBlob(): Promise<Blob | null> {

  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  const fontFamily = `'Source Han Serif SC', 'Noto Serif CJK SC', 'Songti SC', serif`
  const paper = cssVar('--paper-hi', '#f4ecd4')
  const ink = cssVar('--ink', '#2e2417')
  const inkSoft = cssVar('--ink-soft', '#5c4b32')
  const gold = cssVar('--gold', '#a97e2f')
  const lineSoft = cssVar('--line-soft', 'rgba(46, 36, 23, 0.18)')

  // ---- 背景 ----
  ctx.fillStyle = paper
  ctx.fillRect(0, 0, W, H)

  // ---- 双线金框 ----
  ctx.strokeStyle = gold
  ctx.lineWidth = 2
  ctx.strokeRect(20, 20, W - 40, H - 40)
  ctx.strokeStyle = lineSoft
  ctx.lineWidth = 1
  ctx.strokeRect(34, 34, W - 68, H - 68)

  // ---- 标题块：name + latin ----
  ctx.fillStyle = ink
  ctx.font = `900 56px ${fontFamily}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText(props.constellation.name, 60, 80)

  ctx.font = `500 22px 'Cinzel', ${fontFamily}`
  ctx.fillStyle = gold
  ctx.fillText(props.constellation.latin, 60, 156)

  // 标题下细线
  ctx.strokeStyle = lineSoft
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(60, 200)
  ctx.lineTo(W - 60, 200)
  ctx.stroke()

  // ---- § 你是谁 ----
  let y = 220
  const whoLines = buildYouWhoLines(props.constellation)
  ctx.font = `22px ${fontFamily}`
  ctx.fillStyle = inkSoft
  if (whoLines.length === 0) {
    ctx.fillText('该星座信息暂未补全。', 60, y)
    y += 32
  } else {
    for (const line of whoLines) {
      const wrapped = wrapText(ctx, line, W - 120)
      for (const w of wrapped) {
        ctx.fillText(w, 60, y)
        y += 32
      }
    }
  }
  y += 20

  // ---- § 怎么找你（Canvas 星图）----
  drawSectionHeader(ctx, '怎么找你', y)
  y += 38
  const mapH = 360
  drawStarMap(ctx, props.constellation, 60, y, W - 120, mapH)
  y += mapH + 16

  // ---- § 星座简介 ----
  drawSectionHeader(ctx, '星座简介', y)
  y += 38
  ctx.font = `20px ${fontFamily}`
  ctx.fillStyle = ink
  const introText = (props.intro && props.intro.trim())
    ? props.intro
    : '（暂无简介，请打开「识读小笺」点击「讲讲这个星座」）'
  const introLines = wrapText(ctx, introText, W - 120)
  for (const line of introLines) {
    if (y > H - QR_SIZE - 80) break
    ctx.fillText(line, 60, y)
    y += 30
  }

  // ---- Footer: QR + URL ----
  const qrX = W - QR_SIZE - 60
  const qrY = H - QR_SIZE - 100

  try {
    const qr = await loadImage(
      `${import.meta.env.BASE_URL}qr/starwhisper-qr.png`,
    )
    ctx.drawImage(qr, qrX, qrY, QR_SIZE, QR_SIZE)
    // QR 边框
    ctx.strokeStyle = gold
    ctx.lineWidth = 1
    ctx.strokeRect(qrX - 1, qrY - 1, QR_SIZE + 2, QR_SIZE + 2)
  } catch {
    // QR 加载失败 → 灰底占位 + 「（二维码暂不可用）」文字
    ctx.fillStyle = cssVar('--paper-lo', '#ddc99e')
    ctx.fillRect(qrX, qrY, QR_SIZE, QR_SIZE)
    ctx.strokeStyle = gold
    ctx.lineWidth = 1
    ctx.strokeRect(qrX, qrY, QR_SIZE, QR_SIZE)
    ctx.fillStyle = inkSoft
    ctx.font = `14px ${fontFamily}`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('（二维码暂不可用）', qrX + QR_SIZE / 2, qrY + QR_SIZE / 2)
  }

  // URL 文字（QR 下方）
  ctx.fillStyle = inkSoft
  ctx.font = `14px ${fontFamily}`
  ctx.textAlign = 'right'
  ctx.textBaseline = 'top'
  ctx.fillText(
    `扫码访问 · ${QR_URL_TEXT}`,
    W - 60,
    qrY + QR_SIZE + 16,
  )

  // 左下角签名
  ctx.textAlign = 'left'
  ctx.fillStyle = inkSoft
  ctx.font = `13px ${fontFamily}`
  ctx.fillText('StarWhisper · 图鉴', 60, H - 56)

  // ---- toBlob ----
  return new Promise<Blob | null>((resolve) => {
    canvas.toBlob((blob) => resolve(blob), 'image/png')
  })
}

async function download(): Promise<void> {
  let blob: Blob | null
  try {
    blob = await generateBlob()
  } catch (err) {
    emit('error', err instanceof Error ? err.message : String(err))
    return
  }
  if (!blob) {
    emit('error', 'toBlob returned null')
    return
  }
  const filename = `${props.constellation.tradition ?? 'western'}-${props.constellation.abbr}-nota.png`
  triggerDownload(blob, filename)
}

// 修复：原 watch 只在 props.showShareCard 由 false→true 变化时才触发。
// 但 AtlasNota 用 v-if="showShareCard" 控制挂载——点击 chip 后，组件 mount 时
// props.showShareCard 已是 true，没有 transition，watch 永远不会跑、download() 不触发。
// immediate:true 让 mount 时也跑一次，后续重复点击 chip (true→false→true) 也跑。
watch(
  () => props.showShareCard,
  async (now) => {
    if (now) {
      try {
        await download()
        emit('done')
      } catch (err) {
        emit('error', err instanceof Error ? err.message : String(err))
      }
    }
  },
  { immediate: true },
)
</script>

<template>
  <!-- 离屏：仅作为逻辑容器，不显示在视口 -->
  <div class="atlas-share-card" data-testid="atlas-share-card" style="display: none;" />
</template>

<style scoped>
.atlas-share-card {
  display: none !important;
}
</style>