<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

import type { AtlasStar, ConstellationAtlas, StarCanvasMode, StarOverlay } from '../types'
import {
  computeField as computeAtlasField,
  projectStereographic,
  angularSeparation,
} from '../utils/atlasProjection'

/** 一条线 4 个数 [x1, y1, x2, y2]（显示坐标系像素，已 EXIF 变换）。 */
type Line = [number, number, number, number]

const props = defineProps<{
  mode: StarCanvasMode
  starsOverlay?: StarOverlay[]
  overlayLines?: Line[]
  imageWidth?: number
  imageHeight?: number
  activeAbbr?: string | null
  constellationData?: ConstellationAtlas | null
  empty?: boolean
  /** T7: 标注用 tradition key（默认 'western'）；Chinese tradition 用 name_zh。 */
  tradition?: string
  /** ★ 视觉调节 5：命中星座列表（ScanView 传 displayedConstellations），
   *  overlay 模式在每个星座成员星点几何中心标注星座名。 */
  hitConstellations?: Array<{ abbr: string; name: string }>
  /** ★ 视觉调节：叠层透明度（仅 overlay 模式使用）。
   *  0 = 完全透明  1 = 完全不透明。undefined 时按 1 处理，不影响其他模式。 */
  overlayOpacity?: number
}>()

// T7: 标注用函数 + 常量
// ★ Batch H（用户反馈："处女座同时出现 4 种命名：中文译名 / 复合名 / 希腊 / 西文名"）：
// 数据里 vir/com/ser/her/dra/oph 等西方传统条目把"太微左垣四 东次将"这种
// enclosure+wall+position+name 的复合中文名直接放进了 name / name_zh。
// 原回退链（name → name_zh → bayer）会把整串复合名直接画出来，混着
// 角宿一（期望的"中文译名"） + τ/ν（希腊编号） + Apami-Atsa（无中名的西文）
// 一起展示，用户体感是"4 种命名同时出现"。
//
// 修复：
// 1. clean() 拆复合名（取空格后最后一段）+ 剥方括号
// 2. Western 视图 name_zh 优先；name 兜底但**只接受含中文**（隐藏 Apami-Atsa）
// 3. bayer 不再回退（避免希腊编号出现在中文体系下）
// 4. 全空时返回 ''，draw 层 if (!name) continue 跳过（dot 仍可见）
function displayNameFor(star: any, trad: string): string {
  // 拆复合名 + 剥方括号 + 去空白
  const clean = (s: any): string => {
    let raw = ((s ?? '').toString() || '').trim()
    if (!raw) return ''
    // 0) HIP catalog ID（无任何传统名时的最后兜底）——保留全名 "HIP 58225"
    if (/^HIP\s/i.test(raw)) return raw
    // 1) 拆 "太微左垣四 东次将" → "东次将"（复合名：取最后一段）
    if (/\s/.test(raw)) {
      const parts = raw.split(/\s+/)
      raw = parts[parts.length - 1]
    }
    // 2) 剥 "三公二[太微垣]" / "天田增一[角宿]" → 取 [ 之前的部分
    const m = raw.match(/^([^\[【\(]+)/)
    if (m) raw = m[1]
    return raw.trim()
  }
  // 是否含中文（CJK）
  const isChinese = (s: string): boolean => /[㐀-鿿]/.test(s)

  if (trad === 'chinese') {
    return clean(star.name_zh) || clean(star.name)
  }
  // western: name_zh 优先（用户期望的"中文译名"如 角宿一），name 兜底但
  // 只接受含中文（避免 Apami-Atsa 等纯西文名漏出）。bayer 不再回退——
  // 希腊编号对中文用户是噪音。HIP 编号在 clean() 步骤 0 已保留。
  const fromZh = clean(star.name_zh)
  if (fromZh) return fromZh
  const fromName = clean(star.name)
  if (fromName && isChinese(fromName)) return fromName
  return clean(star.name)  // HIP fallback（步骤 0 已保 full）
}
// ★ Batch E/F：字号底抬到 10px、量级 1.5→2——人眼在 187% Win11 缩放下对
// 8px 文字感到吃力；亮星 16px、暗星 10px 是 compromise。
function fontSize(mag: number): number {
  return 10 + Math.max(0, (4 - mag)) * 2
}

/**
 * 星等 → 半径（像素）。6 档分档：1/2/3/4/5/6 等 → 8.5/6.5/5/4/3/2.2 px。
 * 整体比原 6.5/5/4/3/2.2/1.6 放大 ~30%；本轮按用户反馈"都有点大"再
 * 缩 25%（SCALE_FACTOR=0.75），回到原版 M1 附近，仍保留 1.875× DPR
 * 下 ≥ 3.3 物理像素（暗星 1.65 CSS px × 2）以保证不再亚像素糊点。
 */
const STAR_SCALE = 0.75
function magnitudeToRadius(mag: number | undefined): number {
  const m = mag ?? 4
  if (m <= 1) return 8.5 * STAR_SCALE   // ≈ 6.4
  if (m <= 2) return 6.5 * STAR_SCALE   // ≈ 4.9
  if (m <= 3) return 5.0 * STAR_SCALE   // ≈ 3.75
  if (m <= 4) return 4.0 * STAR_SCALE   // 3.0
  if (m <= 5) return 3.0 * STAR_SCALE   // ≈ 2.25
  return 2.2 * STAR_SCALE               // ≈ 1.65
}

/**
 * 把 CSS lineWidth snap 到「最近向上取整的物理像素边界」。
 *
 * 为什么：在 1.25× DPR 下，lineWidth=1.5 CSS px = 1.875 物理 px，浏览器必须
 * 亚像素抗锯齿渲成 1 个灰像素 + 邻像素 87.5% 透明度——视觉上"糊"。snap 后
 * lineWidth=1.5 → 2 物理 px = 1.6 CSS px，边缘干净。
 *
 * 用 `ceil` 而非 `round`：宁可稍粗不要稍细（粗线 1px 之差肉眼不可见，细线
 * 亚像素会很糊）。
 */
function snapW(cssW: number, dpr: number): number {
  if (dpr <= 1) return cssW
  return Math.max(cssW, Math.ceil(cssW * dpr) / dpr)
}

// ── T6: real-projection 辅助 ────────────────────────────────────

// 自动计算视场尺寸（度）+ 调新 Stereographic 公式
function computeField(
  stars: Record<string, AtlasStar>,
  viewbox: { width: number; height: number },
): {
  width: number; height: number; scale: number; centerRa: number; centerDec: number
} {
  const starCoords = Object.values(stars)
    .map((s: any) => ({ ra: s.ra, dec: s.dec }))
    .filter((s) => Number.isFinite(s.ra) && Number.isFinite(s.dec))
  if (starCoords.length === 0) {
    return { width: 120, height: 90, scale: 1, centerRa: 0, centerDec: 0 }
  }
  const field = computeAtlasField(
    starCoords,
    { w: viewbox.width, h: viewbox.height },
    30,
  )
  // 推天空范围（度）用于 grid spacing：取最大球面角距 × 2 当直径。
  let maxC = 0
  for (const s of starCoords) {
    const c = angularSeparation(s.ra, s.dec, field.center.ra, field.center.dec)
    if (c > maxC) maxC = c
  }
  const cosDec = Math.cos((field.center.dec * Math.PI) / 180)
  const widthDeg = maxC * 2 * Math.max(cosDec, 0.1) * 1.5
  const heightDeg = maxC * 2 * 1.5
  if (widthDeg > 120 || heightDeg > 90) {
    console.warn(
      `computeField: 星座星过散，视场被裁剪 (raw=${widthDeg.toFixed(1)}×${heightDeg.toFixed(1)}°)`,
    )
  }
  return {
    width: Math.min(Math.max(widthDeg, 10), 120),
    height: Math.min(Math.max(heightDeg, 8), 90),
    scale: field.scale,
    centerRa: field.center.ra,
    centerDec: field.center.dec,
  }
}

// Azimuthal Stereographic 投影（中心点 guard 已内建在 atlasProjection）。
// 屏幕物理坐标约定：X 轴向右为 RA 增大方向（东为正）；Y 轴向下为 Dec 减小方向
// （北为正，但 canvas 原点在左上故翻转）。—— 与项目统一约定一致。
function worldToPixelEquirect(
  ra: number,
  dec: number,
  _center: { ra: number; dec: number },
  field: { scale: number; centerRa: number; centerDec: number },
  viewbox: { width: number; height: number },
): { x: number; y: number } {
  return projectStereographic(
    ra,
    dec,
    field.centerRa,
    field.centerDec,
    field.scale,
    { w: viewbox.width, h: viewbox.height },
  )
}

// 网格步长（接近 5° 整数倍，且 ≤ fieldExtent / 3）
function gridStep(fieldExtent: number): number {
  const ideal = fieldExtent / 6
  return Math.max(5, Math.round(ideal / 5) * 5)
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

// ── 性能与状态 ─────────────────────────────────────────────────
const DRAW_DURATION_MS = 1200         // spec §6.1 描出 1.2s
const TWINKLE_PERIOD_MS = 1600        // spec §6.1 闪烁 1.6s
const ATLAS_ROT_AMP = (2 * Math.PI) / 180  // spec §6.2 ±2°
const ATLAS_ROT_PERIOD_MS = 12000     // spec §6.2 12s/周
const LINE_STAGGER_MS = 80            // spec §6.1 每条线错峰 80ms

// 导出供单测：line 数 → drawDuration（自适应） / lineDelay
// 返回 null 表示"无错峰需求"（单条线时退化为 0）。
// ★ 修复前固定用 DRAW_DURATION_MS，lines.length > 15 时最后几条 line
// （idx > 14）lineDelay > 1 → lineT = 0 → 完全不画（CYG/AQL 末几条缺失）。
// 修复后 drawDuration = max(1200, n*80 + 600)，所有 lineDelay < 1。
function computeDrawDuration(linesLength: number): number {
  if (linesLength <= 1) return DRAW_DURATION_MS
  const totalStaggerTime = linesLength * LINE_STAGGER_MS
  return Math.max(DRAW_DURATION_MS, totalStaggerTime + DRAW_DURATION_MS * 0.5)
}

let resizeObserver: ResizeObserver | null = null
let intersectionObserver: IntersectionObserver | null = null
let rafId: number | null = null
let drawStartMs = 0
let twinklePhase = 0
let atlasRotRad = 0
let isVisible = true  // IntersectionObserver / visibilitychange
let currentDpr = 1     // tick() 每帧从 window.devicePixelRatio 刷一遍；draw 函数拿来 snap lineWidth

const prefersReducedMotion =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

// ── 工具 ────────────────────────────────────────────────────────
function getCssSize() {
  const c = containerRef.value
  return c ? { w: c.clientWidth, h: c.clientHeight } : { w: 0, h: 0 }
}

function computeMapping(contentW: number, contentH: number) {
  const iw = props.imageWidth ?? 1
  const ih = props.imageHeight ?? 1
  const scale = Math.min(contentW / iw, contentH / ih)
  return {
    scale,
    offsetX: (contentW - iw * scale) / 2,
    offsetY: (contentH - ih * scale) / 2,
  }
}

// ── 描出 + 闪烁（overlay 模式，spec §6.1） ─────────────────────

// ★ 视觉调节 4：Liang-Barsky 线段矩形裁剪。返回裁剪后的两端点（CSS 像素坐标），
// 完全在矩形外返回 null。任一端点连线跨越照片边界时截断到边界。
function clipLineSegment(
  ax: number, ay: number, bx: number, by: number,
  xmin: number, ymin: number, xmax: number, ymax: number,
): [number, number, number, number] | null {
  let t1 = 0, t2 = 1
  const dx = bx - ax, dy = by - ay
  const clip = (p: number, q: number): boolean => {
    if (p === 0) return q >= 0
    const r = q / p
    if (p < 0) {
      if (r > t2) return false
      if (r > t1) t1 = r
    } else {
      if (r < t1) return false
      if (r < t2) t2 = r
    }
    return true
  }
  if (!clip(-dx, ax - xmin)) return null
  if (!clip( dx, xmax - ax)) return null
  if (!clip(-dy, ay - ymin)) return null
  if (!clip( dy, ymax - ay)) return null
  return [ax + t1 * dx, ay + t1 * dy, ax + t2 * dx, ay + t2 * dy]
}

function drawOverlay(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const { scale, offsetX, offsetY } = computeMapping(w, h)
  const stars = props.starsOverlay ?? []
  const lines = props.overlayLines ?? []
  const isEmpty = props.empty === true
  // ★ 视觉调节：叠层透明度。undefined 视为 1（向后兼容）。
  // 线性乘到所有 4 个 alpha 通道（连线/星点/亮星名/命中星座中心名），
  // 描出动画 (lineT) 与 dim 逻辑 (active/inactive) 之上额外作用一层。
  const op = props.overlayOpacity ?? 1

  // ★ 视觉调节 4（用户反馈：连到外面的连线要显示但截断到边界，不是整条跳过）：
  // 旧实现按 canvas 容器尺寸铺开连线——竖图限高后两侧纸色空白仍画了延伸
  // 出去的连线段。改为：连线两端裁剪到照片 contain 矩形内（完全在外才
  // 跳过；跨界画裁断后的可见段；都在内画原线段）。某些星座主线延伸到
  // 画布外（夏季大三角部分成员）时，截断可见段比整条跳过更符合直觉。
  const iw = props.imageWidth ?? 1
  const ih = props.imageHeight ?? 1
  const imgLeft = offsetX
  const imgTop = offsetY
  const imgRight = offsetX + iw * scale
  const imgBottom = offsetY + ih * scale

  // ★ 总描出时长：包含所有线的错峰时间。lines.length × LINE_STAGGER_MS
  // 是最后一条线"启动"的时间点；为让最后一条线有足够时间画完，再加
  // DRAW_DURATION_MS（单线描出时长）。否则 lines.length > 15 时
  // lineDelay = (idx × 80) / 1200 > 1 → lineT 被 clamp 到 0，
  // 最后几条线永远画不出来。复现：夏季大三角 20 条连线 → CYG（idx 16-19）
  // 全部 invisible、AQL 最后 2 条（idx 14-15）部分缺失。
  const drawDuration = computeDrawDuration(lines.length)

  // 描出进度：done / empty / reduce-motion → 立即 1
  let drawProgress = 1
  if (!isEmpty && !prefersReducedMotion) {
    const elapsed = performance.now() - drawStartMs
    const raw = Math.min(1, Math.max(0, elapsed / drawDuration))
    drawProgress = 1 - Math.pow(1 - raw, 3)  // easeOutCubic
  }

  // 1. 描出连线（empty 时整段跳过，spec §6.1）
  // 连线是服务端投好的像素坐标 [x1, y1, x2, y2]，已与 stars_overlay 同坐标系，
  // 不再需要 bayer 字符串查找。暗星座（Vul / Sge / Equ）端点 bayer 为空也能画。
  if (!isEmpty) {
    lines.forEach(([x1, y1, x2, y2], idx) => {
      // lineDelay 用 drawDuration（不是 DRAW_DURATION_MS）归一化，
      // 保证最后一条线的 delay < 1、能被 lineT 公式正常推进。
      const lineDelay = (idx * LINE_STAGGER_MS) / drawDuration
      const denom = Math.max(1 - lineDelay, 0.001)
      const lineT = Math.min(1, Math.max(0, (drawProgress - lineDelay) / denom))
      const lineW = lineT * 1.5        // 0 → 1.5（M1 原始值；Batch E/F 加粗到 3
                                    // 是 symptom fix，用户最终判定保留字号/星点
                                    // 即可，线宽回 M1）
      const lineA = lineT * 0.9 * op   // 0 → 0.9，叠层透明度线性折减
      const isActive = props.activeAbbr == null
      // ★ 修复（用户反馈：选中人马座后人马座连线没有高亮）：
      // 旧逻辑在 activeAbbr 非 null 时把线统一乘 0.4——那是"传入全量线、
      // 调暗非选中星座"时代的假设。T8 后 ScanView.displayLines 已只传选中
      // 星座的线（overlay_lines_by_abbr[abbr]），再乘 0.4 会把选中星座自己
      // 的线压到 36% alpha，比未选中（90%）还暗，用户看到"连线不亮反而变暗"。
      // 现行为：选中态高亮（alpha 不打折 + 线宽 ×1.33 加粗突出反馈），
      // 未选中态维持 M1 原样（0.9 alpha / 1.5 线宽）。
      ctx.strokeStyle = `rgba(212,160,23,${lineA})`
      ctx.lineWidth = snapW(isActive ? lineW : lineW * 1.33, currentDpr)
      const ax = x1 * scale + offsetX
      const ay = y1 * scale + offsetY
      const bx = x2 * scale + offsetX
      const by = y2 * scale + offsetY
      // ★ 调节 4：Liang-Barsky 裁剪到照片 contain 矩形。完全在外才跳过；
      // 跨界画裁断后的可见段；都在内画原线段。
      const clipped = clipLineSegment(ax, ay, bx, by, imgLeft, imgTop, imgRight, imgBottom)
      if (!clipped) return
      const [cax, cay, cbx, cby] = clipped
      const px = cax + (cbx - cax) * lineT
      const py = cay + (cby - cay) * lineT
      ctx.beginPath()
      ctx.moveTo(cax, cay)
      ctx.lineTo(px, py)
      ctx.stroke()
    })
  }

  // 2. 星点 + 闪烁（spec §6.1）：shadowBlur = 6 + 4 * sin(2π t / 1600)
  //    empty / reduce-motion → shadowBlur = 0（不闪烁）
  for (const s of stars) {
    const cx = s.pixel_x * scale + offsetX
    const cy = s.pixel_y * scale + offsetY
    // ★ 调节 4：星点中心落在照片 contain 矩形外 → 跳过（不画、不闪烁、
    // 不参与 dim 高亮判断）。竖图两侧纸色空白区不再有"幽灵星点"。
    if (cx < imgLeft || cx > imgRight || cy < imgTop || cy > imgBottom) continue
    const r = magnitudeToRadius(s.magnitude)
    // T8: 拉大 active/inactive 区分度（0.5 → 0.15），让点 chip 时其他
    // 星座的星点几乎消失。修复 test4 反馈：3 星座同框时 active 切换
    // 视觉反馈太弱。
    // ★ 多归属修复（用户反馈：选人马座后人马座内部星点不亮）：
    // stars_overlay[].constellation 是合并星表去重后的首现归属（chinese
    // 按目录序先加载，sgr 的 25 颗星全被 ji_xiu/dou_xiu 抢注）→
    // s.constellation === activeAbbr 对 western chip 全部 miss → dim 0.15
    // 几乎隐没。改为优先按 constellations 多归属列表判断；旧 fixture /
    // 老后端无该字段时回退 constellation 单字段。
    const hitActive =
      props.activeAbbr != null &&
      (Array.isArray(s.constellations)
        ? s.constellations.includes(props.activeAbbr)
        : s.constellation === props.activeAbbr)
    const dim = (isEmpty
      ? 0.2
      : props.activeAbbr == null || hitActive
        ? 1
        : 0.15) * op

    if (!isEmpty && !prefersReducedMotion) {
      const blur = 6 + 4 * Math.sin(2 * Math.PI * twinklePhase)
      ctx.shadowBlur = blur
      ctx.shadowColor = 'gold'
    } else {
      ctx.shadowBlur = 0
    }

    ctx.fillStyle = `rgba(212,160,23,${dim})`
    ctx.beginPath()
    ctx.arc(
      s.pixel_x * scale + offsetX,
      s.pixel_y * scale + offsetY,
      r,
      0,
      Math.PI * 2,
    )
    ctx.fill()
    ctx.shadowBlur = 0
  }

  // 3. ★ 视觉调节 5（用户需求，修订：20% → 10%）：overlay 画板标注
  //    3a. 星等最亮前 10% 的星星 → 星点右上方标星名
  //    3b. 每个命中星座 → 其成员星点几何中心标星座名（金色）
  //    两者都只在照片 contain 矩形内渲染（与调节 4 裁剪一致）。
  if (!isEmpty) {
    const inRect = (px: number, py: number): boolean =>
      px >= imgLeft && px <= imgRight && py >= imgTop && py <= imgBottom

    // 3a. 亮星 top 10%（magnitude 升序 = 越小越亮；至少 1 颗）
    const visibleStars = stars.filter((s) =>
      inRect(s.pixel_x * scale + offsetX, s.pixel_y * scale + offsetY),
    )
    const topCount = Math.max(1, Math.ceil(visibleStars.length * 0.1))
    const topStars = [...visibleStars]
      .sort((a, b) => a.magnitude - b.magnitude)
      .slice(0, topCount)
    ctx.textBaseline = 'bottom'
    ctx.textAlign = 'left'
    for (const s of topStars) {
      const name = displayNameFor(s, 'western')
      if (!name) continue
      // ★ 调节 6（用户反馈：选中 chip 时非当前星座的内容淡出 0.4）：
      // 亮星名与中心名同节奏——active 1.0 / 非 active 0.4。星点 dim 仍
      // 走 0.15（T8 既定，加深暗/亮区分度，不动）。
      const belongsToActive =
        props.activeAbbr == null ||
        (Array.isArray(s.constellations)
          ? s.constellations.includes(props.activeAbbr)
          : s.constellation === props.activeAbbr)
      const labelAlpha = (belongsToActive ? 1 : 0.4) * op
      const lx = s.pixel_x * scale + offsetX + 8
      const ly = s.pixel_y * scale + offsetY - 8
      // 深色描边垫底保证亮/暗背景都可读（用户反馈：描边调细 3 → 1.5 → 改回 3）
      ctx.lineWidth = snapW(3, currentDpr)
      ctx.strokeStyle = `rgba(0,0,0,${0.55 * labelAlpha})`
      ctx.strokeText(name, lx, ly)
      ctx.fillStyle = `rgba(245,240,230,${0.92 * labelAlpha})`
      ctx.fillText(name, lx, ly)
    }

    // 3b. 命中星座中心标注（成员星点算术平均；中心出照片矩形则不画）
    for (const c of props.hitConstellations ?? []) {
      const members = stars.filter((s) => {
        const belongs = Array.isArray(s.constellations)
          ? s.constellations.includes(c.abbr)
          : s.constellation === c.abbr
        if (!belongs) return false
        return inRect(s.pixel_x * scale + offsetX, s.pixel_y * scale + offsetY)
      })
      if (members.length === 0) continue
      const cx =
        members.reduce((sum, s) => sum + s.pixel_x, 0) / members.length
      const cy =
        members.reduce((sum, s) => sum + s.pixel_y, 0) / members.length
      const px = cx * scale + offsetX
      const py = cy * scale + offsetY
      if (!inRect(px, py)) continue
      // 选中态联动：未选中全亮；选中其他星座时本星座中心名淡出
      const dimLabel =
        (props.activeAbbr == null || props.activeAbbr === c.abbr ? 1 : 0.4) * op
      ctx.font = '700 13px "Cormorant Garamond", "Noto Serif SC", serif'
      ctx.textBaseline = 'middle'
      ctx.textAlign = 'center'
      // 用户反馈：描边调细 3 → 1.5
      ctx.lineWidth = snapW(1.5, currentDpr)
      ctx.strokeStyle = `rgba(0,0,0,${0.6 * dimLabel})`
      ctx.strokeText(c.name, px, py)
      ctx.fillStyle = `rgba(212,160,23,${0.95 * dimLabel})`
      ctx.fillText(c.name, px, py)
      // 恢复默认状态，避免污染后续 draw 帧 / 其他绘制段
      ctx.textAlign = 'left'
      ctx.textBaseline = 'alphabetic'
    }
  }
}

// ── atlas 缓回旋（scan-atlas 模式，spec §6.2 + §16.2.1） ────────
function drawScanAtlas(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const data = props.constellationData
  if (!data) return

  ctx.save()
  if (!prefersReducedMotion) {
    ctx.translate(w / 2, h / 2)
    ctx.rotate(atlasRotRad)
    ctx.translate(-w / 2, -h / 2)
  }

  // atlas 视图坐标系（M1 沿用 640×460，可由 data.viewBox 覆盖）
  const vbW = data.viewBox?.width ?? 640
  const vbH = data.viewBox?.height ?? 460
  const sx = w / vbW
  const sy = h / vbH

  // 网格
  ctx.strokeStyle = 'rgba(184,134,11,0.15)'
  ctx.lineWidth = snapW(1, currentDpr)
  for (let i = 0; i <= vbW; i += 52) {
    ctx.beginPath()
    ctx.moveTo(i * sx, 0)
    ctx.lineTo(i * sx, h)
    ctx.stroke()
  }
  for (let j = 0; j <= vbH; j += 52) {
    ctx.beginPath()
    ctx.moveTo(0, j * sy)
    ctx.lineTo(w, j * sy)
    ctx.stroke()
  }

  // 同心圆（虚线）
  ctx.setLineDash([4, 4])
  ctx.strokeStyle = 'rgba(184,134,11,0.25)'
  ctx.beginPath()
  ctx.ellipse(
    (vbW / 2) * sx,
    (vbH / 2) * sy,
    200 * sx,
    180 * sy,
    0,
    0,
    Math.PI * 2,
  )
  ctx.stroke()
  ctx.beginPath()
  ctx.ellipse(
    (vbW / 2) * sx,
    (vbH / 2) * sy,
    120 * sx,
    100 * sy,
    0,
    0,
    Math.PI * 2,
  )
  ctx.stroke()
  ctx.setLineDash([])

  // 连线
  for (const [a, b] of data.lines ?? []) {
    const sa = data.stars?.[a]
    const sb = data.stars?.[b]
    if (!sa || !sb) continue
    ctx.strokeStyle = 'rgba(212,160,23,0.85)'
    ctx.lineWidth = snapW(1.5, currentDpr)  // M1 原始值
    ctx.beginPath()
    ctx.moveTo(sa.x * sx, sa.y * sy)
    ctx.lineTo(sb.x * sx, sb.y * sy)
    ctx.stroke()
  }

  // 主星（atlas 模式自带金色光晕 M1 行为，spec §6.1）
  for (const s of Object.values(data.stars ?? {})) {
    const r = magnitudeToRadius(s.magnitude)
    ctx.fillStyle = 'rgba(212,160,23,1)'
    ctx.shadowBlur = 6
    ctx.shadowColor = 'gold'
    ctx.beginPath()
    ctx.arc(s.x * sx, s.y * sy, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
  }

  // T7: 常驻标注（label=true 的星点，位置星点右上方 8px 偏移）
  // 颜色：西方 'var(--ink)'、中国 'var(--seal)'（热红色调区分体系）
  // ★ Batch F：name 为空（starnames.csv 没收录的暗星）→ skip label，dot 仍可见
  const trad = props.tradition ?? 'western'
  ctx.font = '600 14px "Cormorant Garamond", "Noto Serif SC", serif'
  ctx.textBaseline = 'bottom'
  for (const s of Object.values(data.stars ?? {})) {
    if (!(s as any).label) continue
    const name = displayNameFor(s, trad)
    if (!name) continue  // 兜底链全空（无 name/无 zh/无 bayer）→ 不画
    const lx = s.x * sx + 8
    const ly = s.y * sy - 8
    ctx.fillStyle = trad === 'chinese' ? '#8b2e2e' : '#1f1a14'
    ctx.font = `600 ${fontSize(s.magnitude)}px "Cormorant Garamond", "Noto Serif SC", serif`
    ctx.fillText(name, lx, ly)
  }

  ctx.restore()
}

// ── real-projection 模式（spec v4 任务 6） ────────────────────────
// 以 (center.ra, center.dec) 为中心的 Azimuthal Stereographic 投影。
// 输出顺序：边框 → 网格 → 中心十字 → 连线 → 主星 → 标注。
function drawRealProjection(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const data = props.constellationData
  if (!data || !data.center) return

  const stars = (data.stars ?? {}) as Record<string, AtlasStar>
  const viewbox = { width: w, height: h }
  const field = computeField(stars, viewbox)
  const center = { ra: field.centerRa, dec: field.centerDec }

  // 1. 视场边框
  ctx.strokeStyle = 'rgba(184,134,11,0.4)'
  ctx.lineWidth = snapW(1, currentDpr)
  ctx.strokeRect(2, 2, w - 4, h - 4)

  // 2. 网格（赤经圈 + 赤纬圈，虚线）
  const stepRa = gridStep(field.width)
  const stepDec = gridStep(field.height)
  ctx.strokeStyle = 'rgba(184,134,11,0.15)'
  ctx.lineWidth = snapW(1, currentDpr)
  ctx.setLineDash([2, 4])

  // 垂直线（赤经圈）：从 center.ra - width/2 往上推一个 step 的整数倍
  const raStart = Math.ceil((center.ra - field.width / 2) / stepRa) * stepRa
  const raEnd = center.ra + field.width / 2
  for (let ra = raStart; ra < raEnd; ra += stepRa) {
    const { x } = worldToPixelEquirect(ra, center.dec, center, field, viewbox)
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
    ctx.stroke()
  }

  // 水平线（赤纬圈）
  const decStart = Math.ceil((center.dec - field.height / 2) / stepDec) * stepDec
  const decEnd = center.dec + field.height / 2
  for (let dec = decStart; dec < decEnd; dec += stepDec) {
    const { y } = worldToPixelEquirect(center.ra, dec, center, field, viewbox)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }
  ctx.setLineDash([])

  // 3. 中心十字（中心 RA/Dec 对应的像素位置）
  const centerPx = worldToPixelEquirect(
    center.ra,
    center.dec,
    center,
    field,
    viewbox,
  )
  const cx = centerPx.x
  const cy = centerPx.y
  ctx.strokeStyle = 'rgba(201,162,74,0.85)'
  ctx.lineWidth = snapW(1.5, currentDpr)  // M1 原始值
  ctx.beginPath()
  ctx.moveTo(cx - 12, cy)
  ctx.lineTo(cx + 12, cy)
  ctx.moveTo(cx, cy - 12)
  ctx.lineTo(cx, cy + 12)
  ctx.stroke()

  // 4. 连线
  for (const [a, b] of data.lines ?? []) {
    const sa = stars[a]
    const sb = stars[b]
    if (!sa || !sa.ra || !sb || !sb.ra) continue
    const pa = worldToPixelEquirect(
      sa.ra,
      sa.dec ?? 0,
      center,
      field,
      viewbox,
    )
    const pb = worldToPixelEquirect(
      sb.ra,
      sb.dec ?? 0,
      center,
      field,
      viewbox,
    )
    ctx.strokeStyle = 'rgba(212,160,23,0.85)'
    ctx.lineWidth = snapW(1.5, currentDpr)  // M1 原始值
    ctx.beginPath()
    ctx.moveTo(pa.x, pa.y)
    ctx.lineTo(pb.x, pb.y)
    ctx.stroke()
  }

  // 5. 主星
  for (const s of Object.values(stars)) {
    if (!s.ra || s.dec === undefined) continue
    const { x, y } = worldToPixelEquirect(s.ra, s.dec, center, field, viewbox)
    const r = magnitudeToRadius(s.magnitude)
    ctx.fillStyle = 'rgba(212,160,23,1)'
    ctx.shadowBlur = 6
    ctx.shadowColor = 'gold'
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
  }

  // 6. 标注（复用 T7 displayNameFor + fontSize）
  const trad = props.tradition ?? 'western'
  for (const s of Object.values(stars)) {
    if (!s.label || !s.ra || s.dec === undefined) continue
    const { x, y } = worldToPixelEquirect(s.ra, s.dec, center, field, viewbox)
    const name = displayNameFor(s, trad)
    if (!name) continue  // 兜底链全空（无 name/无 zh/无 bayer）→ 不画
    ctx.font = `600 ${fontSize(s.magnitude ?? 0)}px "Cormorant Garamond", "Noto Serif SC", serif`
    ctx.textBaseline = 'bottom'
    ctx.fillStyle = trad === 'chinese' ? '#8b2e2e' : '#1f1a14'
    ctx.fillText(name, x + 8, y - 8)
  }
}

// ── 主循环（spec §6.4：离屏/隐藏停 rAF；mode 切换清理旧 rafId） ─
function tick(now: number) {
  const { w, h } = getCssSize()
  if (w === 0 || h === 0) {
    if (isVisible) rafId = requestAnimationFrame(tick)
    return
  }

  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  // ★ 根因修复：Win11 187% 分数缩放下 canvas 始终发糊的真正成因——
  // 浏览器 compositor 必须做 2× → 1.875× 的非整数 downscale（53% 缩放），
  // 这个过程 bilinear 过滤把线/字边缘融合成"软"。整数化 DPR（1.875→2）
  // 只解决了上半场，下半场 2× → 1.875× 仍然 fractional。
  //
  // 真正稳的方案：把渲染分辨率拔到 4× CSS 像素（2× super-sample on top of
  // integer-DPR），让 1.875× display 拿到的 downscale 是 4× → 1.875×。
  // 优势是 4× 内部画布上 10px 字体 = 40px 渲染，再 bilinear down 到 18.75px
  // display = 拿到 sub-pixel AA 的"额外锐度"；同时分数 downscale 的
  // 模糊比例从 6.7%（2×→1.875×）稀释到 53%（4×→1.875×）但因起点像素密度
  // 高 4×，最终视觉反而更利。
  //
  // 性能：800×700 CSS 画布 = 3200×2800 物理像素 = 9M px/帧。60fps = 540M
  // px/s，现代 GPU 无压力。线/字 stroke 路径数 50 左右，draw call < 100。
  const dpr_eff = Math.max(1, Math.round(dpr)) * 2
  currentDpr = dpr_eff  // 让 draw 函数拿到有效 DPR 用来 snap lineWidth
  if (
    canvas.width !== Math.round(w * dpr_eff) ||
    canvas.height !== Math.round(h * dpr_eff)
  ) {
    canvas.width = Math.round(w * dpr_eff)
    canvas.height = Math.round(h * dpr_eff)
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr_eff, dpr_eff)
  // HiDPI：画星点/连线/文字时 imageSmoothingEnabled 默认 true 即可平滑
  // 抗锯齿，避免亚像素（1 CSS px 在 1.25× DPR 下=1.25 物理像素）的毛糙感。
  // 不关 false——会让线/字出现锯齿。
  ctx.imageSmoothingEnabled = true
  // ★ 每帧前清空画布：drawScanAtlas / drawOverlay / drawRealProjection 都
  // 是叠加式绘制（fillText + arc + stroke），新一帧如果不 clear，上一帧
  // 的 label / 线 / 网格都会残留在画布上。常见触发：切换星座时新数据
  // `label: true` 星点数 < 旧数据 → 旧 label 位置未被新内容覆盖。
  // clearRect 必须在 setTransform/scale 之后调用，使其按当前矩阵清空
  // 整张物理画布。
  ctx.clearRect(0, 0, w, h)

  // 持续动画相位（spec §6.1 / §6.2）
  if (!prefersReducedMotion) {
    twinklePhase = (now / TWINKLE_PERIOD_MS) % 1
    atlasRotRad =
      ATLAS_ROT_AMP * Math.sin((2 * Math.PI * now) / ATLAS_ROT_PERIOD_MS)
  } else {
    twinklePhase = 0
    atlasRotRad = 0
  }

  if (props.mode === 'overlay') {
    drawOverlay(ctx, w, h)
  } else if (props.mode === 'real-projection') {
    drawRealProjection(ctx, w, h)
  } else {
    drawScanAtlas(ctx, w, h)
  }

  if (isVisible) {
    rafId = requestAnimationFrame(tick)
  }
}

function startDraw() {
  drawStartMs = performance.now()
  // 同步 tick 一帧：首屏立即可见，并兼容 mount 后同步断言的旧测试。
  // tick 内部末尾会通过 requestAnimationFrame(tick) 注册下一帧，循环自动继续。
  if (isVisible && rafId === null) {
    tick(performance.now())
  }
}

function cancelOldLoop() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    cancelOldLoop()
  } else if (isVisible && rafId === null) {
    rafId = requestAnimationFrame(tick)
  }
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      // 容器尺寸变化时若未在跑则重新调度（spec §6.4）
      if (rafId === null && isVisible) {
        drawStartMs = performance.now()
        rafId = requestAnimationFrame(tick)
      }
    })
    resizeObserver.observe(containerRef.value)
  }

  if (typeof IntersectionObserver !== 'undefined' && containerRef.value) {
    intersectionObserver = new IntersectionObserver(
      (entries) => {
        isVisible = entries[0]?.isIntersecting ?? true
        if (isVisible && rafId === null) {
          drawStartMs = performance.now()
          rafId = requestAnimationFrame(tick)
        } else if (!isVisible) {
          cancelOldLoop()
        }
      },
      { threshold: 0 },
    )
    intersectionObserver.observe(containerRef.value)
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  startDraw()
})

onUnmounted(() => {
  cancelOldLoop()
  resizeObserver?.disconnect()
  intersectionObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

// mode / activeAbbr / 数据变化 → 取消旧 rafId + 重新启动（spec §6.4）
watch(
  () =>
    [
      props.mode,
      props.activeAbbr,
      props.starsOverlay,
      props.overlayLines,
      props.empty,
      props.constellationData,
    ] as const,
  () => {
    cancelOldLoop()
    startDraw()
  },
  { deep: true },
)

// 暴露 reduced-motion 标志 + drawDuration 计算 + 星等半径映射 + DPR snap，便于测试 / 调试
defineExpose({
  prefersReducedMotion,
  computeDrawDuration,
  magnitudeToRadius,
  fontSize,
  snapW,
  DRAW_DURATION_MS,
  LINE_STAGGER_MS,
})
</script>

<template>
  <div ref="containerRef" class="star-canvas-container">
    <canvas ref="canvasRef" />
  </div>
</template>

<style scoped>
.star-canvas-container {
  width: 100%;
  height: 100%;
  position: relative;
}
canvas {
  width: 100%;
  height: 100%;
  display: block;
  /* HiDPI：物理像素 canvas.width/height = CSS × devicePixelRatio × SUPER_SAMPLE
     （见 tick() 注释），image-rendering: auto 让浏览器用平滑缩放回 CSS 尺寸。
     不设 crisp-edges/pixelated——会在线和文字上产生锯齿。 */
  image-rendering: auto;
}
</style>