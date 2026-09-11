/**
 * 观星指数 FIG.2 时间区间工具（最小粒度：小时）。
 *
 * 后端 `/api/index` 用「相对今日 00:00 的小时偏移」表达区间：
 *   - `start_hour` ∈ [0, 167]（7 天窗口内的小时序号）
 *   - `hours` ∈ [1, 168]，且 `start_hour + hours <= 168`
 * 前端选择器用「日期 + 整点」表达，二者通过本模块互转（纯函数，可单测）。
 *
 * 日期一律用设备本地时区的 `YYYY-MM-DD`（不用 `toISOString`，避免 UTC 偏移）。
 */

/** 7 天窗口的最后一个小时偏移（0..167，共 168 个整点）。 */
export const MAX_HOUR_OFFSET = 167

/** 选择器形态的区间端点（含首尾）。 */
export interface RangeSelection {
  startDate: string
  startHour: number
  endDate: string
  endHour: number
}

/** 后端形态的区间（含首尾：hours = endHour - startHour + 1）。 */
export interface ResolvedRange {
  startHour: number
  hours: number
}

function clampInt(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return lo
  return Math.max(lo, Math.min(hi, Math.floor(v)))
}

/** 本地日期 → `YYYY-MM-DD`（避开 `toISOString` 的 UTC 偏移）。 */
export function toLocalIso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${dd}`
}

/** 今天（本地时区）的 `YYYY-MM-DD`。 */
export function todayIso(now: Date = new Date()): string {
  return toLocalIso(now)
}

/** 当前整点相对今日 00:00 的偏移（0-23）——FIG.2 默认区间起点。 */
export function currentHourOffset(now: Date = new Date()): number {
  return now.getHours()
}

/** ISO 日期 ± N 天。 */
export function isoPlusDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + days)
  return toLocalIso(dt)
}

/** 整天差（b - a），入参为 ISO 日期。 */
export function daysBetweenIso(a: string, b: string): number {
  const [ay, am, ad] = a.split('-').map(Number)
  const [by, bm, bd] = b.split('-').map(Number)
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000)
}

/** 日期 + 整点 → 相对今日 00:00 的小时偏移。 */
export function hourOffsetFromToday(dateIso: string, hour: number, today: string): number {
  return daysBetweenIso(today, dateIso) * 24 + hour
}

/** 小时偏移 → 日期 + 整点（`hourOffsetFromToday` 的逆变换，越界 clamp）。 */
export function dateHourFromOffset(
  offset: number,
  today: string,
): { date: string; hour: number } {
  const o = clampInt(offset, 0, MAX_HOUR_OFFSET)
  return { date: isoPlusDays(today, Math.floor(o / 24)), hour: o % 24 }
}

/** 选择器 → 后端区间（clamp 进 7 天窗口；终点早于起点时收敛为 1 小时）。 */
export function resolveRange(sel: RangeSelection, today: string): ResolvedRange {
  const s = clampInt(
    hourOffsetFromToday(sel.startDate, sel.startHour, today),
    0,
    MAX_HOUR_OFFSET,
  )
  const e = clampInt(
    hourOffsetFromToday(sel.endDate, sel.endHour, today),
    s,
    MAX_HOUR_OFFSET,
  )
  return { startHour: s, hours: e - s + 1 }
}

/**
 * 单端调整后重算区间：
 * - 只动起点 → 保持原时长整体平移（右端越界则 clamp 到 7 天窗口末尾）
 * - 只动终点 → 保持起点（`resolveRange` 负责终点早于起点时收敛）
 * - 两端同时动（或都没动）→ 直接按当前值解析
 */
export function applyRangePatch(
  current: RangeSelection,
  patch: Partial<RangeSelection>,
  today: string,
): ResolvedRange {
  const next: RangeSelection = { ...current, ...patch }
  const startTouched =
    patch.startDate !== undefined || patch.startHour !== undefined
  const endTouched = patch.endDate !== undefined || patch.endHour !== undefined

  if (startTouched && !endTouched) {
    const { hours } = resolveRange(current, today)
    const newStart = clampInt(
      hourOffsetFromToday(next.startDate, next.startHour, today),
      0,
      MAX_HOUR_OFFSET,
    )
    const newEnd = clampInt(newStart + hours - 1, newStart, MAX_HOUR_OFFSET)
    const p = dateHourFromOffset(newEnd, today)
    next.endDate = p.date
    next.endHour = p.hour
  }

  return resolveRange(next, today)
}

/** 小时偏移 → 展示文案（今天 14:00 / 明天 13:00 / 后天 08:00 / 09/12 08:00 / 2027/01/01 08:00）。 */
export function formatHourOffset(offset: number, today: string): string {
  const { date, hour } = dateHourFromOffset(offset, today)
  const hh = `${String(hour).padStart(2, '0')}:00`
  switch (daysBetweenIso(today, date)) {
    case 0:
      return `今天 ${hh}`
    case 1:
      return `明天 ${hh}`
    case 2:
      return `后天 ${hh}`
    default:
      // 跨年时补上年份，避免“01/02”到底是今年还是明年
      return date.slice(0, 4) === today.slice(0, 4)
        ? `${date.slice(5).replace('-', '/')} ${hh}`
        : `${date.replace(/-/g, '/')} ${hh}`
  }
}

interface MomentParts {
  y: string
  m: number
  d: number
  hhmm: string
}

function momentParts(t: string): MomentParts {
  return {
    y: t.slice(0, 4),
    m: Number(t.slice(5, 7)),
    d: Number(t.slice(8, 10)),
    hhmm: t.slice(11, 16),
  }
}

/**
 * 两个时刻区间（入参 "YYYY-MM-DDTHH:MM"，即 HourlyPoint.time）的展示文案。
 *
 * 常识做法：只有跨年才写年、跨月才写月、跨日才写日，否则只给时刻。
 * 单一时刻（首尾相同）退化到「M月D日 HH:MM」。
 */
export function formatSpan(start: string, end: string): string {
  const a = momentParts(start)
  const b = momentParts(end)
  if (start === end) return `${a.m}月${a.d}日 ${a.hhmm}`
  const level: 'year' | 'month' | 'day' | 'time' =
    a.y !== b.y ? 'year' : a.m !== b.m ? 'month' : a.d !== b.d ? 'day' : 'time'
  const fmt = (p: MomentParts): string => {
    switch (level) {
      case 'year':
        return `${p.y}年${p.m}月${p.d}日 ${p.hhmm}`
      case 'month':
        return `${p.m}月${p.d}日 ${p.hhmm}`
      case 'day':
        return `${p.d}日 ${p.hhmm}`
      default:
        return p.hhmm
    }
  }
  return `${fmt(a)} — ${fmt(b)}`
}
