/**
 * Atlas 共享投影公式（Azimuthal Stereographic）。
 *
 * 双端实现：
 * - Python: server/scripts/atlas_projection.py（build 脚本用）
 * - TypeScript: 本文件（runtime 渲染用）
 *
 * 公式基于球面余弦定理。中心点 c=0 时显式返回画布中心。
 */

const CENTER_GUARD_EPS = 1e-14

export interface StarCoord {
  ra: number
  dec: number
}

export interface Viewbox {
  w: number
  h: number
}

export interface ProjectionField {
  scale: number
  center: { ra: number; dec: number }
  padding: number
}

export function angularSeparation(
  ra1: number, dec1: number, ra2: number, dec2: number
): number {
  const dra = ((ra1 - ra2) * Math.PI) / 180
  let cosC =
    Math.sin((dec1 * Math.PI) / 180) * Math.sin((dec2 * Math.PI) / 180) +
    Math.cos((dec1 * Math.PI) / 180) * Math.cos((dec2 * Math.PI) / 180) *
      Math.cos(dra)
  cosC = Math.max(-1, Math.min(1, cosC))
  return (Math.acos(cosC) * 180) / Math.PI
}

export function computeCenter(stars: StarCoord[]): { ra: number; dec: number } {
  if (stars.length === 0) return { ra: 0, dec: 0 }
  let vx = 0, vy = 0, vz = 0
  for (const s of stars) {
    const raR = (s.ra * Math.PI) / 180
    const decR = (s.dec * Math.PI) / 180
    vx += Math.cos(decR) * Math.cos(raR)
    vy += Math.cos(decR) * Math.sin(raR)
    vz += Math.sin(decR)
  }
  const n = stars.length
  vx /= n
  vy /= n
  vz /= n
  const ra = ((Math.atan2(vy, vx) * 180) / Math.PI + 360) % 360
  const dec = (Math.atan2(vz, Math.hypot(vx, vy)) * 180) / Math.PI
  return { ra, dec }
}

export function computeField(
  stars: StarCoord[], viewbox: Viewbox, padding = 30
): ProjectionField {
  const center = computeCenter(stars)
  if (stars.length === 0) {
    return { scale: 1, center, padding }
  }
  let maxC = 0
  for (const s of stars) {
    const c = angularSeparation(s.ra, s.dec, center.ra, center.dec)
    if (c > maxC) maxC = c
  }
  if (maxC > 170) {
    throw new Error(
      `星座成员存在接近对跖点（max_c=${maxC.toFixed(1)}° > 170°），Stereographic 投影会爆炸`
    )
  }
  if (maxC < 1e-6) {
    return { scale: 1, center, padding }
  }
  const maxRadius = 2 * Math.tan((maxC * Math.PI) / 360)
  const scale = Math.min(
    (viewbox.w / 2 - padding) / maxRadius,
    (viewbox.h / 2 - padding) / maxRadius,
  )
  return { scale, center, padding }
}

export function projectStereographic(
  ra: number, dec: number,
  centerRa: number, centerDec: number,
  scale: number, viewbox: Viewbox
): { x: number; y: number } {
  const draRad = ((ra - centerRa) * Math.PI) / 180
  const decRad = (dec * Math.PI) / 180
  const dec0Rad = (centerDec * Math.PI) / 180

  let cosC =
    Math.sin(dec0Rad) * Math.sin(decRad) +
    Math.cos(dec0Rad) * Math.cos(decRad) * Math.cos(draRad)
  cosC = Math.max(-1, Math.min(1, cosC))

  if (Math.abs(1 - cosC) < CENTER_GUARD_EPS) {
    return { x: viewbox.w / 2, y: viewbox.h / 2 }
  }

  const k = 2 / (1 + cosC)
  const xLocal = Math.cos(decRad) * Math.sin(draRad)
  const yLocal =
    Math.cos(dec0Rad) * Math.sin(decRad) -
    Math.sin(dec0Rad) * Math.cos(decRad) * Math.cos(draRad)

  const x = viewbox.w / 2 + k * xLocal * scale
  const y = viewbox.h / 2 - k * yLocal * scale
  return { x, y }
}
