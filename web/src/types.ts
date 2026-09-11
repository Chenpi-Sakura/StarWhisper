/**
 * Public SolveResult envelope. Mirrors `docs/specs/2026-08-21-starwhisper-design.md`
 * §3.1 — keep in sync with server fixture / handler.
 */

export interface StarOverlay {
  bayer: string
  name: string
  /** ★ 视觉调节 5：中文星名（后端 catalog 透传；displayNameFor 优先用） */
  name_zh?: string
  magnitude: number
  pixel_x: number
  pixel_y: number
  constellation: string
  /**
   * ★ 多归属（用户反馈：选人马座后人马座内部星点不亮）：该物理星在所有
   * tradition 星座条目中的归属 abbr（合并星表 HIP 去重保留首现，单一
   * constellation 会被 chinese 抢注 → 前端 dim 对 western chip 全 miss）。
   * 旧 fixture / 老后端可能缺失 → 回退 constellation 单字段判断。
   */
  constellations?: string[]
}

export interface ConstellationHit {
  abbr: string
  name: string
  latin: string
  confidence: number
  /** T7: visible_stars = 命中星座在画面内的投影星点数（已按 abbr 过滤） */
  visible_stars?: number
  hit_stars?: number
  total_bright_stars: number
  /** T7: 命中的 tradition key（western / chinese） */
  tradition?: string
}

export interface SolveResult {
  ok: boolean
  solved: boolean
  ra?: number
  dec?: number
  pixel_scale?: number
  rotation?: number
  field_width?: number
  field_height?: number
  solve_time?: number
  image_width?: number
  image_height?: number
  exif_orientation?: number
  constellations?: ConstellationHit[]
  stars_overlay?: StarOverlay[]
  /**
   * 星座连线像素坐标：每条线 4 个数 [x1, y1, x2, y2]，坐标已变换到
   * 显示坐标系（EXIF orientation 已处理），与 stars_overlay 同坐标系。
   * 服务端通过 services.astrometry.project_lines() 直接投端点（不依赖
   * bayer 字符串匹配），所以暗星座（Vul / Sge / Equ）也能正常画线。
   */
  overlay_lines?: [number, number, number, number][]
  /**
   * T8: 按 abbr 分组的 overlay_lines — 前端 chip 切换时只画 active 星座的线
   * （修复 test4 反馈：点 chip 时星点高亮但线不亮）。key=constellation abbr，
   * value=该星座的 [x1, y1, x2, y2] 列表（坐标系同 overlay_lines）。无命中
   * 星座时为 {}；向后兼容：overlay_lines 仍返回全量合并版。
   */
  overlay_lines_by_abbr?: Record<string, [number, number, number, number][]>
  code?: string
  message?: string
  advice?: string | null
}

export type StoryStyle = 'myth' | 'science'

export interface StoryResponse {
  ok: boolean
  abbr: string
  style: StoryStyle
  title: string
  paragraphs: string[]
  provider: 'openai-compatible' | 'mock' | 'disabled' | 'fallback' | 'agentarts' | 'ai'
  model: string
  latency_ms: number
  cached: boolean
  degraded: boolean
  degraded_reason?: string
}

export type StoryStreamEvent =
  | { type: 'title'; title: string }
  /** P2-16：字符级事件——AI 推多快前端就显示多快，\n 自然换行、\n\n 段落间距。 */
  | { type: 'char'; char: string }
  | { type: 'done'; meta: StoryResponse }
  | { type: 'reset' }
  | { type: 'error'; message: string }

/**
 * Photo-level 故事上下文（spec `docs/superpowers/specs/2026-09-03-story-photo-design.md` §3.1）
 *
 * 与 atlas 单星座故事不同：photo-level 把整张照片解算出的多星座 / 亮星 /
 * 视场中心一起交给 AI，`POST /api/story` 的 body 即 `PhotoStoryRequest`。
 */
export interface PhotoConstellation {
  abbr: string
  tradition: 'western' | 'chinese'
  name: string
  latin?: string
  confidence?: number
  /** chinese tradition 专用：本宿 / 星官归属 */
  mansion?: string
}

export interface PhotoStar {
  bayer: string
  name: string
  name_zh?: string
  magnitude: number
  /** 多归属：该物理星在各 tradition 下的星座 abbr 列表 */
  constellations?: string[]
}

export interface PhotoCenter {
  ra: number
  dec: number
}

export interface PhotoField {
  width_deg: number
  height_deg: number
}

export interface PhotoStoryContext {
  constellations: PhotoConstellation[]
  bright_stars?: PhotoStar[]
  center?: PhotoCenter
  field?: PhotoField
}

export interface PhotoStoryRequest {
  lang: 'zh'
  style: StoryStyle
  cache_bust?: boolean
  context: PhotoStoryContext
}

/**
 * StoryStreamEvent 已含 char 变体（P2-16）；photo-level 的 error 事件额外带
 * `code`（AI_DISABLED / AI_TIMEOUT / ...），且不发 `reset`（photo 无 preset 降级）。
 */
export type PhotoErrorEvent = { type: 'error'; code: string; message: string }

export interface HealthResponse {
  ok: boolean
  astrometry: 'up' | 'mock' | 'down'
  ai_provider: 'up' | 'disabled' | 'down'
  ai_model: string
}

export interface StoryRequest {
  abbr: string
  style: StoryStyle
  lang: 'zh'
  cacheBust?: number
  /** P2-12：可选 tradition key（western / chinese）；缺省按 abbr 跨 tradition 首命中。 */
  tradition?: string
}

/**
 * 星座图鉴类型（spec §10 / plan T6 Step 1）
 *
 * 注：后端 `GET /api/constellations` 实际返回 7 字段
 * (abbr/name/latin/glyph/season/caption/bright_stars)，不含
 * hemisphere/bestMonth/magnitude/storyStyles。前端类型按 plan 契约
 * 声明，但 hemisphere/bestMonth/magnitude/storyStyles 标可选，
 * 以兼容后端实际返回（运行时为 undefined，View 层用 `?? '-'` 兜底）。
 *
 * 另：season/caption/glyph/lines 亦标可选，以兼容 T4 锁定测试
 * (web/tests/StarCanvas.*.test.ts) 内局部 ConstellationAtlas 的宽松形态
 * ——T4 测试的 constellationData 仅含 {abbr,name,latin,stars,lines?}，
 * 若此处 season/caption 必选会导致 vue-tsc 报 "missing property"。
 */
export type Hemisphere = 'N' | 'S' | 'B'

export interface AtlasListItem {
  abbr: string
  name: string
  latin: string
  glyph?: string
  hemisphere?: Hemisphere
  bestMonth?: number
  season?: string
  caption?: string
  magnitude?: number
  bright_stars?: number
  storyStyles?: string[]
  /** T7: 命中的 tradition key（listConstellations 端点返回） */
  tradition?: string
  /** T7: 该星座的星点数（来自 list 端点 star_count） */
  star_count?: number
  /** T7: 该星座是否有 stories（来自 list 端点 has_stories） */
  has_stories?: boolean
  /** T7+: 后端下发的分组键（中国："东方七宿"/"紫微垣"/"近南极" 等；西方 null） */
  group?: string | null
}

export interface AtlasStar {
  x: number
  y: number
  bayer?: string
  name?: string
  /** T7: 中文星名（西方星座 name 通常是英文） */
  name_zh?: string
  magnitude: number
  /** T7: ICRS J2000 赤经 (度) */
  ra?: number
  /** T7: ICRS J2000 赤纬 (度) */
  dec?: number
  /** T7: 是否为常驻标注（true 时画 <text>） */
  label?: boolean
}

export type AtlasLine = [string, string]

/** T6: 单条预设故事的标题 + 段落列表 */
export interface StoryBlock {
  title: string
  paragraphs: string[]
}

/** 故事扁平结构 {view: StoryBlock} — view = 'myth' | 'science' */
export type ConstellationStories = Record<StoryStyle, StoryBlock>

/** T6: StarCanvas 渲染模式（overlay / scan-atlas / real-projection） */
export type StarCanvasMode = 'overlay' | 'scan-atlas' | 'real-projection'

export interface ConstellationAtlas extends AtlasListItem {
  stars: Record<string, AtlasStar>
  lines?: AtlasLine[]
  viewBox?: { width: number; height: number }
  bright_stars_mag_lt_35?: number
  ok?: boolean
  /** T7: 真实天球中心坐标（RA, Dec） */
  center?: { ra: number; dec: number }
  /** T7: 中国二十八宿专用：本宿英文名（西方为 null） */
  mansion?: string | null
  /** T7: 中国三垣专用：所属垣 id（西方为 null） */
  asterism_id?: string | null
  /** T7: 故事嵌套结构 */
  stories?: ConstellationStories
}

export interface AtlasListResponse {
  ok?: boolean
  tradition?: string // T7: 当前 list 的 tradition
  items: AtlasListItem[]
}

/** T7: /api/traditions 端点返回 */
export interface TraditionListItem {
  key: string
  label: string
  count: number
}

export interface TraditionListResponse {
  items: TraditionListItem[]
}

/** 观星指数四档（对齐 server/services/index.py grade()） */
export type StargazeGrade = '优' | '良' | '一般' | '差'

export interface StargazeMoon {
  phase: number
  /** 0~1，0=新月，1=满月 */
  illumination: number
  label: string
}

export interface StargazeNow {
  time: string
  cloud: number
  precip: number
  wind: number
  temp: number
}

export interface StargazeComponents {
  cloud: number
  precip: number
  windtemp: number
  moon: number
  bortle: number
}

export interface HourlyPoint {
  time: string
  score: number
  grade: StargazeGrade
  cloud: number
  precip: number
  /**
   * 是否属夜间可观测时段（日落之后 或 天文晨光之前）。
   * 后端 /api/index 逐点计算；旧 fixture 缺省时按「可观测」处理。
   */
  night?: boolean
}

/** /api/index astro 时间组（"HH:MM" 或 null = 事件不可见） */
export interface StargazeAstro {
  sunrise: string | null
  sunset: string | null
  /** 天文暮光结束（太阳降到 −18°）：今晚真正的暗夜开始 */
  astro_dusk: string | null
  /** 天文晨光（太阳升到 −18°）：次日暗夜结束 */
  astro_dawn: string | null
  moonrise: string | null
  moonset: string | null
  galactic_rise: string | null
  galactic_set: string | null
}

export interface StargazeIndex {
  ok: boolean
  city: string
  province: string
  lat: number
  lon: number
  timezone?: string
  bortle: number
  bortle_label: string
  score: number
  grade: StargazeGrade
  moon: StargazeMoon
  now: StargazeNow
  components: StargazeComponents
  astro?: StargazeAstro
  hourly: HourlyPoint[]
  /** /api/index 返回当前所选日的索引（0=今天，最大 6，snake_case 对齐后端） */
  day_index?: number
  /** 未来 7 天每日月相（与 moon 同形态，snake_case 对齐后端） */
  daily_moon?: StargazeMoon[]
  /** 未来 7 天每日天文时刻（日出/日落/暮光/晨光/月出月落/银心升落，snake_case 对齐后端） */
  daily_astro?: StargazeAstro[]
}

/**
 * 图鉴页 · 星座导读请求（POST /api/atlas-nota）。
 * 2026-09-16 新增：取代原 <PlateBox caption="识读小笺"> 内联空壳。
 * 与 /api/atlas-story 关系：atlas-story 走 SSE 流式 + myth/science 双视角，
 * atlas-nota 是单档「星图导读」100-200 字非流式短文。
 */
export interface AtlasNotaRequest {
  abbr: string
  /** tradition key（western / chinese）；缺省时按 abbr 跨 tradition 首命中（向后兼容） */
  tradition?: string
  /** 跳过缓存重取 */
  cacheBust?: boolean
  /** 语言代码（暂固定 zh） */
  lang?: string
}

export interface AtlasNotaResponse {
  ok: boolean
  tradition: string
  abbr: string
  /** AgentArts 生成的导读正文（100-200 字）或降级时的 caption */
  intro: string
  /** true 时表示 AI 不可用、降级到了 caption */
  degraded: boolean
  /** 来源：'agentarts' | 'preset' | 'cache' | 'ai' */
  source: string
}