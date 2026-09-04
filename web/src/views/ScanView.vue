<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { useScanStore } from '../stores/scan'
import { useAtlasStore } from '../stores/atlas'
import { isHeic } from '../utils/heic'
import StarCanvas from '../components/StarCanvas.vue'
import StoryPanel from '../components/StoryPanel.vue'
import PlateBox from '../components/common/PlateBox.vue'
import StarBtn from '../components/common/StarBtn.vue'
import StarChip from '../components/common/StarChip.vue'
import type { ConstellationAtlas } from '../types'

const scan = useScanStore()
const atlasStore = useAtlasStore()

const isMock = new URLSearchParams(window.location.search).has('mock')
type OverlayMode = 'overlay' | 'atlas'

const overlayMode = ref<OverlayMode>('overlay')
const heicNotice = ref(false)
const showStory = ref(true)
const ssCanvas = ref<HTMLCanvasElement | null>(null)
/* ★ 视觉调节：叠层透明度（仅 overlay 模式生效）。
   0 = 完全透明（看不到星空识别线/标注）  1 = 完全不透明（默认值）。
   真实投影模式不显示此控件——atlas 数据是另一类视觉，不属于"叠层"。 */
const overlayOpacity = ref<number>(1)

/* ★ 视觉调节 2：按图片自然比例区分横/竖图。横图拉满宽度，竖图限高收缩。 */
const stageImgRatio = ref<number | null>(null)
const isPortraitImg = computed(
  () => stageImgRatio.value !== null && stageImgRatio.value < 1,
)
function onStageImgLoad(e: Event) {
  const img = e.target as HTMLImageElement
  stageImgRatio.value =
    img.naturalWidth > 0 && img.naturalHeight > 0
      ? img.naturalWidth / img.naturalHeight
      : null
}

let isMounted = true
let ssRaf = 0
onUnmounted(() => {
  isMounted = false
  if (ssRaf) cancelAnimationFrame(ssRaf)
})

/* 太阳系公转 Canvas：45° 正交俯视 + 平行投影，不透视缩小
   摄像机固定不动，行星在 XY 平面上跑，z 恒为 0 — 投影后天然成椭圆
   无 halo / 无 gradient / 无 rays / 无交互 — 纯几何 + 星语配色 */
function startSolarSystem() {
  if (ssRaf) cancelAnimationFrame(ssRaf)
  const maybeCanvas = ssCanvas.value
  if (!maybeCanvas) return
  const maybeCtx = maybeCanvas.getContext('2d')
  if (!maybeCtx) return
  // 闭包内 frame() 反复引用 — TS 没法跨嵌套函数追踪 null check，
  // 这里用 const 别名固化类型，后面所有引用都安全
  const canvas = maybeCanvas
  const ctx = maybeCtx

  // 摄像机：相对太阳系平面 30°（更接近水平俯视），方位 -45°（西北）
  const CAMERA_ELEVATION = Math.PI / 6   // 30°
  const cameraAzimuth = -Math.PI / 4

  // 星语羊皮纸配色（取自 star-atlas.css CSS 变量但写死避免运行时读取）
  // canvas 不画背景 — 让 plate 自带的羊皮纸色透过来，避免视觉叠层
  const INK = '#2e2417'             // --ink
  const SUN = '#f3f3f3'             // 纯白偏冷太阳（参照参考代码 fillStyle #f3f3f3）
  const GOLD_2 = '#c9a24a'          // --gold-2
  const ORBIT = 'rgba(169, 126, 47, 0.32)' // 轨道虚线
  const SATURN_RING = '#8b7e58'     // 土星环

  // 8 大行星完整列表（水/金/地/火/木/土/天王/海王）。
  // a 半长轴按真实比例（AU）排后整体放大，确保水星轨道半径
  // > 太阳渲染半径的 2 倍（不被吞掉）。外圈（天王/海王）密度
  // 适当压缩（log 化）让所有 8 条轨道能塞进 320px 容器。
  const planets = [
    { name: '水星',   a: 4.0,  size: 5.5,  color: '#8f7d5f', speed: 4.15,  hasRing: false },
    { name: '金星',   a: 6.0,  size: 8.0,  color: GOLD_2,    speed: 1.62,  hasRing: false },
    { name: '地球',   a: 8.0,  size: 9.0,  color: '#5e7d8a', speed: 1.00,  hasRing: false },
    { name: '火星',   a: 10.4, size: 6.5,  color: '#9c3b2a', speed: 0.53,  hasRing: false },
    { name: '木星',   a: 14.6, size: 16,   color: '#b89f82', speed: 0.084, hasRing: false },
    { name: '土星',   a: 18.6, size: 14,   color: '#c1b58e', speed: 0.034, hasRing: true },
    { name: '天王星', a: 22.0, size: 11,   color: '#87aeb3', speed: 0.012, hasRing: true },
    { name: '海王星', a: 24.5, size: 10,   color: '#536fa0', speed: 0.006, hasRing: false },
  ]
  const RING_MAX = 25.0  // 海王星最大轨道 24.5，留 0.5 余量到容器边

  type V3 = { x: number; y: number; z: number }
  type Basis = { right: V3; up: V3; fwd: V3 }
  // 计算相机正交基（right / up / forward），forward 用于深度排序
  function basis(): Basis {
    const ce = Math.cos(CAMERA_ELEVATION)
    const se = Math.sin(CAMERA_ELEVATION)
    const ca = Math.cos(cameraAzimuth)
    const sa = Math.sin(cameraAzimuth)
    return {
      right: { x: -sa, y: ca, z: 0 },
      up:    { x: -se * ca, y: -se * sa, z: ce },
      fwd:   { x: ce * ca, y: ce * sa, z: se },
    }
  }
  function project(p: V3, b: Basis, scale: number): { x: number; y: number } {
    const sx = p.x * b.right.x + p.y * b.right.y
    const sy = p.x * b.up.x    + p.y * b.up.y
    return {
      x: canvas.width  / 2 + sx * scale,
      y: canvas.height / 2 - sy * scale,
    }
  }
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const cssW = canvas.clientWidth  || 300
    const cssH = canvas.clientHeight || 300
    canvas.width  = Math.floor(cssW * dpr)
    canvas.height = Math.floor(cssH * dpr)
  }

  let time = 0
  let lastT = performance.now()
  function frame(now: number) {
    const dt = Math.min(0.05, (now - lastT) / 1000)
    lastT = now
    time += dt

    resize()
    const b = basis()
    const short = Math.min(canvas.width, canvas.height)
    const scale = short * 0.46 / (RING_MAX)

    // 透明背景 — 让 plate 自带的羊皮纸色直接透过来
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // 轨道
    ctx.strokeStyle = ORBIT
    ctx.lineWidth = Math.max(1, canvas.width / 800)
    for (const p of planets) {
      ctx.beginPath()
      const seg = 144
      for (let i = 0; i <= seg; i++) {
        const t = (i / seg) * Math.PI * 2
        const q = project({ x: p.a * Math.cos(t), y: p.a * Math.sin(t), z: 0 }, b, scale)
        if (i === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y)
      }
      ctx.stroke()
    }

    // 行星：先按相机 forward 方向排序 — 前面的覆盖后面的
    const drawList = planets.map((p, i) => {
      const angle = time * p.speed * 0.675 + i * 0.73  // 0.45 × 1.5 = 0.675，公转适中
      const pos = { x: p.a * Math.cos(angle), y: p.a * Math.sin(angle), z: 0 }
      const depth = pos.x * b.fwd.x + pos.y * b.fwd.y
      return { p, pos, depth }
    }).sort((x, y) => x.depth - y.depth)

    // 行星（实心圆，半径由 size × zoom 决定，无 halo）
    for (const { p, pos } of drawList) {
      const q = project(pos, b, scale)
      const r = Math.max(3, p.size * (scale / 220))
      ctx.beginPath()
      ctx.arc(q.x, q.y, r, 0, Math.PI * 2)
      ctx.fillStyle = p.color
      ctx.fill()

      // 土星 / 天王星环：纯色椭圆 + 内圆擦空（不发光）
      // 土星环宽，天王星环窄（垂直行星轨道面，更稀薄）
      if (p.hasRing) {
        const ringScale = p.name === '土星' ? 1.95 : 1.6
        const ringWidth = p.name === '土星' ? 0.45 : 0.25
        const innerScale = p.name === '土星' ? 1.1 : 1.05
        ctx.save()
        ctx.translate(q.x, q.y)
        ctx.rotate(-cameraAzimuth)
        ctx.scale(1, 0.42)
        ctx.beginPath()
        ctx.ellipse(0, 0, r * ringScale, r * ringScale, 0, 0, Math.PI * 2)
        ctx.strokeStyle = SATURN_RING
        ctx.lineWidth = Math.max(1, r * ringWidth)
        ctx.stroke()
        // 用行星色擦出环中空区
        ctx.beginPath()
        ctx.arc(0, 0, r * innerScale, 0, Math.PI * 2)
        ctx.fillStyle = p.color
        ctx.fill()
        ctx.restore()
      }
    }

    // 太阳：纯白实心圆，**无 halo 无 rays**。比最大行星还大几倍（视觉中心锚点）
    ctx.beginPath()
    ctx.arc(canvas.width / 2, canvas.height / 2, Math.max(10, 66 * (scale / 220)), 0, Math.PI * 2)
    ctx.fillStyle = SUN
    ctx.fill()

    ssRaf = requestAnimationFrame(frame)
  }
  ssRaf = requestAnimationFrame(frame)
}

/* status 进入 uploading 时启动 canvas，退出时停掉 — 别在 done 态还跑
   requestAnimationFrame 浪费 CPU。
   关键：scan.status 改了之后 v-if 切换 PlateBox 还没 mount canvas DOM，
   必须 nextTick 等 DOM 更新完 ssCanvas.value 才不为 null。 */
watch(
  () => scan.status,
  (s) => {
    if (s === 'uploading') {
      nextTick(() => startSolarSystem())
    } else if (ssRaf) {
      cancelAnimationFrame(ssRaf)
      ssRaf = 0
    }
  },
)
onMounted(() => {
  if (scan.status === 'uploading') startSolarSystem()
})

type AtlasMap = Record<string, ConstellationAtlas>

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  heicNotice.value = await isHeic(file)
  scan.selectImage(file)
  // 上传后自动开始识别，免去手动点击
  await scan.solve(isMock)
}

// done 态下切换 tradition：仅前端过滤展示，不触发 re-solve
// （astrometry 与 tradition 无关，重解只是白白浪费 20s 上游调用）
function onTraditionChange(next: '' | 'western' | 'chinese') {
  if (scan.lockedTradition === next) return
  scan.setLockedTradition(next)
}

// T7: 透传 tradition 到 StarCanvas 用于标注
const atlasTradition = computed<string>(
  () => scan.result?.constellations?.[0]?.tradition ?? 'western',
)

// T8+: 按 scan.lockedTradition 过滤 constellation 列表（前端过滤，不重解）
// 0=不限 → 全展示；1=western 仅展示 tradition==='western'；2=chinese 同理
const displayedConstellations = computed(() => {
  const all = scan.result?.constellations ?? []
  const lock = scan.lockedTradition
  if (!lock) return all
  return all.filter((c) => (c.tradition ?? 'western') === lock)
})

const atlasData = computed<ConstellationAtlas | null>(() => {
  // ★ 用 activeConstellation（跟 scan.activeAbbr 走），不能用 constellations[0]：
  // 用户点 CYG chip 时 activeAbbr='cyg'，但 constellations[0] 永远是 LYR；
  // 之前固定拿 LYR 的 atlas，画布点击切换无响应。
  const hit = activeConstellation.value
  if (!hit) return null
  const key = `${hit.tradition ?? 'western'}/${hit.abbr}`
  return atlasStore.atlasCache[key] ?? null
})

// T8: 按 activeAbbr 过滤 overlay_lines — 点 chip 时只画对应星座的线。
// 修复 test4 反馈：3 星座同时画时点击 chip 线不亮（之前 star 走 dim
// 0.5/1.0 有微弱区分，line 一律 33% 完全看不出）。无 activeAbbr 时画全。
const displayLines = computed<[number, number, number, number][]>(() => {
  const all = scan.result?.overlay_lines ?? []
  const byAbbr = scan.result?.overlay_lines_by_abbr
  const abbr = scan.activeAbbr
  if (!abbr || !byAbbr) return all
  return byAbbr[abbr] ?? all
})

// ★ 视觉调节 5：命中星座（tradition 过滤后）传给 StarCanvas overlay，
// 在每个星座成员星点几何中心标注星座名。
const hitLabels = computed(() =>
  displayedConstellations.value.map((c) => ({ abbr: c.abbr, name: c.name })),
)

const activeConstellation = computed(() => {
  // 用 displayedConstellations（受 lockedTradition 过滤）做 active 选择，
  // 让 result-card / story atlas / 命中数 都跟着切 tradition 一起变。
  const list = displayedConstellations.value
  if (list.length === 0) {
    // 过滤后空：fallback 全量（避免切到空 tradition 时 result-card 全空）
    const all = scan.result?.constellations ?? []
    return all[0] ?? null
  }
  const abbr = scan.activeAbbr
  if (abbr) {
    const hit = list.find((c) => c.abbr === abbr)
    if (hit) return hit
  }
  return list[0]
})

const confidenceLabel = computed(() => {
  const c = activeConstellation.value
  if (!c) return ''
  const pct = c.confidence * 100
  if (pct >= 85) return '识别成功 · 高可信'
  if (pct >= 70) return '识别成功'
  return '识别成功 · 低可信'
})

const confidenceNote = computed(() => {
  const c = activeConstellation.value
  if (!c) return ''
  // T7: hit_stars → visible_stars（命中星座在画面内的星点数）
  const vis = c.visible_stars ?? c.hit_stars ?? 0
  return `匹配《星语图鉴》第 ${(vis + 17)} 页图版 · 命中 ${vis}/${c.total_bright_stars} 亮星`
})

// 任务 7：识别完成后自动加载 atlas（spec v4 任务 6 已实现 getAtlas 缓存）。
// ★ 跟 activeConstellation 走：识别完默认载入第一颗（LYR），点 CYG chip 时再载入 cyg。
watch(
  () => activeConstellation.value?.abbr,
  async (newAbbr) => {
    const hit = activeConstellation.value
    if (!hit || !newAbbr) return
    const trad = hit.tradition ?? 'western'
    await atlasStore.getAtlas(trad, newAbbr)
    if (!isMounted) return
  },
  { immediate: true },
)
</script>

<template>
  <div class="scan-view">
    <!-- 上传前的 idle 提示：单独 plate -->
    <PlateBox
      v-if="scan.status === 'idle'"
      plate="PLATE Ⅱ"
      caption="星空识别 · 以图问天"
    >
      <div class="idle-block">
        <p class="idle-text">拍一张星空照片，让星语为你解读天上的故事。</p>
        <label class="upload-area" data-testid="upload-area">
          <input
            type="file"
            accept=".jpg,.jpeg,.png"
            class="upload-native"
            data-testid="file-input"
            @change="onFileChange"
          />
          <div class="upload-orn" aria-hidden="true">✦</div>
          <div class="upload-title">点击此处 选取星空</div>
          <div class="upload-hint">支持 JPG · JPEG · PNG · 单张不超过 20MB</div>
          <div class="upload-pick">
            <span class="upload-pick-btn">浏览文件</span>
            <span class="upload-pick-sep">·</span>
            <span class="upload-pick-name">未选择任何文件</span>
          </div>
        </label>
        <p v-if="heicNotice" class="chip warn inline">HEIC 将由服务器自动转换为 JPG</p>
      </div>
    </PlateBox>

    <!-- 已选图待识别 -->
    <PlateBox
      v-else-if="scan.status === 'ready'"
      plate="PLATE Ⅱ"
      caption="等待解读"
    >
      <div class="photo-stage viewer">
        <img
          v-if="scan.previewUrl"
          :src="scan.previewUrl"
          class="stage-img"
          :class="{ portrait: isPortraitImg }"
          alt="待识别"
          @load="onStageImgLoad"
        />
        <div class="fig-tag">FIG. 待识别 · 选自相册</div>
      </div>
      <div class="actions">
        <StarBtn label="换一张" variant="ghost" @click="scan.reset()" />
      </div>
    </PlateBox>

    <!-- 识别中 -->
    <PlateBox
      v-else-if="scan.status === 'uploading'"
      plate="PLATE Ⅱ"
      caption="正在解读"
    >
      <div class="veil">
        <canvas
          ref="ssCanvas"
          class="solar-canvas"
          data-testid="solar-system"
        />
        <p class="step-text">正在解读星图…</p>
        <StarBtn label="取消" variant="ghost" @click="scan.cancel()" />
      </div>
    </PlateBox>

    <!-- 识别成功 -->
    <PlateBox
      v-else-if="scan.status === 'done'"
      plate="PLATE Ⅱ"
      caption="星空识别 · 以图问天"
    >
      <div class="scan-grid">
        <!-- 左：viewer -->
        <div>
          <div class="photo-stage viewer">
            <img
              v-if="scan.previewUrl"
              :src="scan.previewUrl"
              class="stage-img"
              :class="{ portrait: isPortraitImg }"
              alt="已识别"
              @load="onStageImgLoad"
            />
            <StarCanvas
              v-if="overlayMode === 'overlay'"
              class="overlay"
              mode="overlay"
              :stars-overlay="scan.result?.stars_overlay"
              :overlay-lines="displayLines"
              :image-width="scan.result?.image_width"
              :image-height="scan.result?.image_height"
              :active-abbr="scan.activeAbbr"
              :hit-constellations="hitLabels"
              :overlay-opacity="overlayOpacity"
            />
            <!-- atlasData 来自 spec v3 T7 已有的 computed（stores/atlas.atlasCache 派生），无需新增 -->
            <StarCanvas
              v-else
              class="overlay atlas"
              mode="real-projection"
              :constellation-data="atlasData"
              :active-abbr="scan.activeAbbr"
              :tradition="atlasTradition"
            />

          </div>

          <div class="tradition-switch inline" data-testid="tradition-switch-done">
            <span class="switch-label">识别文化：</span>
            <StarChip
              data-testid="tradition-chip-auto-done"
              label="不限"
              :active="scan.lockedTradition === ''"
              @click="onTraditionChange('')"
            />
            <StarChip
              data-testid="tradition-chip-western-done"
              label="西方"
              :active="scan.lockedTradition === 'western'"
              @click="onTraditionChange('western')"
            />
            <StarChip
              data-testid="tradition-chip-chinese-done"
              label="中国古代"
              :active="scan.lockedTradition === 'chinese'"
              @click="onTraditionChange('chinese')"
            />
          </div>

          <div class="constellation-list">
            <StarChip
              v-for="c in displayedConstellations"
              :key="`${c.tradition}-${c.abbr}`"
              :data-testid="`constellation-chip-${c.abbr}`"
              :label="`${c.name} (${(c.confidence * 100).toFixed(0)}%)`"
              :active="scan.activeAbbr === c.abbr"
              @click="scan.toggleConstellation(c.abbr)"
            />
          </div>

          <div class="view-toggle">
            <span class="toggle-label">视图：</span>
            <StarChip
              data-testid="chip-overlay"
              label="照片叠层"
              :active="overlayMode === 'overlay'"
              @click="overlayMode = 'overlay'"
            />
            <StarChip
              data-testid="chip-real-projection"
              label="真实投影"
              :active="overlayMode === 'atlas'"
              @click="overlayMode = 'atlas'"
            />
          </div>

          <!-- ★ 视觉调节：叠层透明度滑块。仅 overlay 模式显示。
               真实投影模式（atlas 数据）不在此范围，控件整行 v-if 隐藏。 -->
          <div v-if="overlayMode === 'overlay'" class="opacity-slider" data-testid="opacity-slider-row">
            <label class="opacity-label" for="overlay-opacity-slider">叠层透明度</label>
            <input
              id="overlay-opacity-slider"
              data-testid="overlay-opacity-slider"
              class="opacity-range"
              type="range"
              min="0"
              max="1"
              step="0.05"
              v-model.number="overlayOpacity"
            />
            <span class="opacity-value">{{ Math.round(overlayOpacity * 100) }}%</span>
          </div>
        </div>

        <!-- 右：识别结果卡 + 故事 -->
        <div>
          <div class="result-card" data-testid="result-card">
            <div class="head">
              <div class="seal gold">{{ activeConstellation?.abbr?.toUpperCase() ?? '???' }}</div>
              <div class="head-text">
                <h4>{{ activeConstellation?.name ?? '—' }}</h4>
                <div class="lat">{{ activeConstellation?.latin ?? '—' }}</div>
              </div>
              <StarBtn
                class="ml-auto btn-rescan"
                label="↻ 换图识别"
                variant="ghost"
                size="sm"
                data-testid="btn-rescan"
                @click="scan.reset()"
              />
            </div>

            <div class="conf-row compact">
              <div class="conf-left">
                <span class="conf-label">识别可信度</span>
                <b class="conf-pct">{{ activeConstellation ? (activeConstellation.confidence * 100).toFixed(1) + '%' : '—' }}</b>
              </div>
              <div class="conf-note">{{ confidenceNote }}</div>
            </div>
          </div>

          <!-- 故事面板（嵌在 result-card 下方，复用 StoryPanel 真 SSE 流式） -->
          <div v-if="showStory" class="story-inline">
            <PlateBox plate="STORY" caption="星座故事">
              <StoryPanel
                :abbr="scan.activeAbbr ?? scan.result?.constellations?.[0]?.abbr ?? ''"
              />
            </PlateBox>
          </div>
        </div>
      </div>
    </PlateBox>

    <!-- 空命中 -->
    <PlateBox
      v-else-if="scan.status === 'empty'"
      plate="PLATE Ⅱ"
      caption="未识别到已收录星座"
    >
      <div class="photo-stage viewer">
        <img v-if="scan.previewUrl" :src="scan.previewUrl" class="stage-img" alt="已选择" />
        <StarCanvas
          class="overlay"
          mode="overlay"
          :stars-overlay="scan.result?.stars_overlay"
          :overlay-lines="[]"
          :image-width="scan.result?.image_width"
          :image-height="scan.result?.image_height"
          :empty="true"
        />
      </div>
      <div class="banner-empty">画面内未识别到已收录星座</div>
    </PlateBox>

    <!-- 错误 -->
    <PlateBox
      v-else-if="scan.status === 'error'"
      plate="PLATE Ⅱ"
      caption="识别失败"
    >
      <div class="error-card">
        <h4>✕ 识别未成</h4>
        <p class="error-message">{{ scan.errorMessage ?? '识别失败' }}</p>
        <p v-if="scan.result?.advice" class="error-advice">
          建议：{{ scan.result.advice }}
        </p>
        <div class="acts">
          <StarBtn label="↻ 重试一次" variant="seal" size="sm" @click="scan.solve(isMock)" />
          <StarBtn label="换一张" variant="ghost" size="sm" @click="scan.reset()" />
        </div>
      </div>
    </PlateBox>
  </div>
</template>

<style scoped>
.scan-view {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin-top: 8px;
  flex: 1;
  min-height: 0;
}
/* 让 PlateBox 的 plate/plate-body 也参与 flex chain，约束 .scan-grid 不撑高 */
.scan-view :deep(.plate) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.scan-view :deep(.plate-body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.scan-grid {
  display: grid;
  grid-template-columns: 1.25fr 0.95fr;
  gap: 22px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.scan-grid > div:last-child {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
@media (max-width: 1000px) {
  .scan-grid {
    grid-template-columns: 1fr;
  }
}

/* viewer：照片 + sepia 滤镜 + fig-tag 标注（done 态已移除"已识别"标签） */
/* ★ 视觉调节 3（用户反馈：还有黑边）：
   旧实现 padding:10px + background:#171208——padding 区域始终显示深色底，
   即使 img 拉满也会形成 10px 黑边圈；img max-height 触发 contain 时留白
   区域同样显示深色。改为 padding:0 + 透明背景，让照片直接贴容器，contain
   留白透出 plate 纸色（非黑）；canvas overlay inset 同步改 0。 */
.photo-stage.viewer {
  position: relative;
  border: 1px solid var(--ink);
  background: transparent;
  padding: 0;
  max-width: 100%;
  display: block;
}
.stage-img {
  display: block;
  width: 100%;
  height: auto;
  max-height: min(68vh, 640px);
  object-fit: contain;
}
.stage-img.portrait {
  width: auto;
  max-width: 100%;
  height: min(66vh, 620px);
  margin: 0 auto;
}
.photo-stage.viewer :deep(.star-canvas-container) {
  position: absolute;
  inset: 0;
  pointer-events: none;
  width: 100%;
  height: 100%;
}
.photo-stage.viewer :deep(.star-canvas-container.atlas) {
  background: var(--paper-lo);
  filter: none;
}
.fig-tag {
  position: absolute;
  left: 18px;
  bottom: 18px;
  background: rgba(23, 18, 8, 0.72);
  color: var(--gold-pale);
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: 0.3em;
  padding: 5px 12px;
  border: 1px solid rgba(233, 213, 162, 0.3);
}

.constellation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

/* 任务 7：3 chip 视图切换（替代原 showAtlas 按钮） */
.view-toggle {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 14px;
}
.toggle-label {
  font-family: var(--cn);
  font-size: 11.5px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
}

/* ★ 视觉调节：叠层透明度滑块。仅 overlay 模式显示。
   用 plate 暖金边框 + 同心字距，沿用切换行视觉语言；
   滑块轨道 accent 用 var(--gold-2) 与 chip hover 状态呼应。 */
.opacity-slider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding: 8px 12px;
  border: 1px dashed var(--line-soft);
  background: rgba(246, 238, 216, 0.5);
}
.opacity-label {
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.16em;
  color: var(--ink-soft);
  white-space: nowrap;
  cursor: pointer;
}
.opacity-range {
  flex: 1;
  max-width: 240px;
  height: 4px;
  accent-color: var(--gold-2);
  cursor: pointer;
}
.opacity-value {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--gold);
  min-width: 38px;
  text-align: right;
}

/* result-card 识别结果卡 */
.result-card {
  margin-top: 4px;
  border: 1px solid var(--line);
  background: #f6eed8;
  padding: 14px 18px;
  animation: rise 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
  flex-shrink: 0;
}
.result-card .head {
  display: flex;
  align-items: center;
  gap: 16px;
}
.result-card .seal {
  width: 58px;
  height: 58px;
  font-size: 13px;
}
.result-card .seal.gold {
  color: var(--gold);
}
.head-text h4 {
  font-family: var(--cn);
  font-weight: 900;
  font-size: 24px;
  letter-spacing: 0.14em;
  margin: 0;
}
.head-text .lat {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.3em;
  color: var(--gold);
}
.ml-auto {
  margin-left: auto;
}
/* 换图识别：金色描边特殊样式，区别于普通 ghost 按钮 */
.btn-rescan {
  border-color: var(--gold);
  color: var(--gold);
  font-weight: 700;
  letter-spacing: 0.18em;
}
.btn-rescan:hover {
  background: var(--gold-2);
  border-color: var(--gold-2);
  color: #241c10;
}
.conf-row {
  margin-top: 10px;
}
.conf-row.compact {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
}
.conf-left {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}
.conf-label {
  font-family: var(--cn);
  font-size: 13px;
  color: var(--ink-soft);
}
.conf-pct {
  font-family: var(--disp);
  font-weight: 600;
  color: var(--ink);
  font-size: 14px;
}
.conf-note {
  font-family: var(--cn);
  font-size: 12px;
  color: var(--ink-faint);
  text-align: right;
  white-space: nowrap;
}
.acts {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* story-inline：识别卡下方嵌套 plate（可滚动的故事区） */
.story-inline {
  margin-top: 18px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.story-inline :deep(.plate) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.story-inline :deep(.plate-body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.story-inline :deep(.story-panel) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* idle / ready 占位 */
.idle-block {
  text-align: center;
  padding: 20px;
  /* 在 .plate-body 的 flex 列里填满剩余高度，让 upload-area 真正上下居中 */
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 22px;
}
.upload-area {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 26px 22px 22px;
  max-width: 520px;
  background:
    linear-gradient(var(--paper-hi), var(--paper-hi)) padding-box,
    repeating-linear-gradient(
      135deg,
      rgba(169, 126, 47, 0.55) 0 6px,
      transparent 6px 12px
    ) border-box;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background-color 0.25s, transform 0.25s;
}
.upload-area::before,
.upload-area::after {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  border: 1px solid var(--gold);
  pointer-events: none;
}
.upload-area::before {
  top: 8px;
  left: 8px;
  border-right: none;
  border-bottom: none;
}
.upload-area::after {
  bottom: 8px;
  right: 8px;
  border-left: none;
  border-top: none;
}
.upload-area:hover {
  background-color: #f4ead0;
}
.upload-area:hover .upload-pick-btn {
  background: var(--ink);
  color: var(--paper-hi);
  border-color: var(--ink);
}
.upload-native {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.upload-orn {
  font-family: var(--disp);
  color: var(--gold);
  font-size: 22px;
  letter-spacing: 0.5em;
  margin-left: 0.5em;
  line-height: 1;
}
.upload-title {
  font-family: var(--cn);
  font-weight: 700;
  font-size: 17px;
  letter-spacing: 0.28em;
  color: var(--ink);
  margin-top: 2px;
}
.upload-hint {
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}
.upload-pick {
  margin-top: 12px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--cn);
  font-size: 12.5px;
  color: var(--ink-soft);
  letter-spacing: 0.14em;
}
.upload-pick-btn {
  border: 1px solid var(--gold);
  background: var(--gold-2);
  color: #241c10;
  font-weight: 700;
  padding: 5px 16px;
  letter-spacing: 0.2em;
  transition: 0.25s;
}
.upload-pick-sep {
  color: var(--gold);
}
.upload-pick-name {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--ink-faint);
}
.tradition-switch {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 12px 0 16px;
  flex-wrap: wrap;
}
.tradition-switch.inline {
  margin: 14px 0 0;
  padding-top: 10px;
  border-top: 1px dashed var(--line-soft);
}
.switch-label {
  font-family: var(--cn);
  font-size: 13px;
  color: var(--ink-soft);
  letter-spacing: 0.12em;
  margin-right: 4px;
}
.idle-text {
  margin: 0;
  color: var(--ink-soft);
  font-style: italic;
}
.chip.inline {
  display: inline-flex;
  margin: 0;
}

/* veil 识别中 */
.veil {
  display: flex;
  flex-direction: column;
  gap: 18px;
  align-items: center;
  justify-content: center;
  padding: 36px 10px;
  color: var(--ink-faint);
}

/* 太阳系公转 Canvas：等上游 astrometry 解读时跑（最长 20+s），
   让等待也像观星。所有几何都在 Canvas 里绘制（45° 正交俯视 + 平行投影），
   这里只管盒子尺寸 + 居中。 */
.solar-canvas {
  display: block;
  width: 320px;
  height: 320px;
  max-width: 100%;
}

.step-text {
  font-family: var(--cn);
  font-size: 13px;
  letter-spacing: 0.24em;
  margin: 0;
}

/* banner-empty */
.banner-empty {
  background: var(--paper-lo);
  border: 1px dashed var(--ink-light);
  padding: 12px;
  text-align: center;
  color: var(--ink-light);
  margin-top: 12px;
}

/* error-card */
.error-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.error-card h4 {
  font-family: var(--cn);
  font-weight: 900;
  color: var(--seal);
  letter-spacing: 0.1em;
  margin: 0;
}
.error-card p {
  margin: 0;
  font-size: 13px;
  color: var(--ink-soft);
}

/* ================= 移动端适配 ================= */
@media (max-width: 1000px) {
  /* 解除图片高度限制，让图片自然流动 */
  .stage-img {
    max-height: none;
  }
  .stage-img.portrait {
    height: auto;
    max-width: 100%;
  }
  /* 解除溢出裁剪，让内容自然展开 */
  .scan-view :deep(.plate) {
    overflow: visible;
  }
  .scan-grid {
    overflow: visible;
  }
  .story-inline :deep(.plate) {
    overflow: visible;
  }
  .photo-stage.viewer {
    max-width: 100%;
  }
}
</style>