/**
 * Canvas 离屏文本折行（分享卡专用）。
 *
 * 刻意不依赖 ctx.measureText（CJK 段不信任其上宽度）：
 * 字体未加载 / fallback 时 measureText 的宽度与实际渲染不一致，
 * 会导致换行失效、整段文本画成一行、溢出右侧。
 * 改为按字号估算每个字符宽度折行，任何字体环境下都稳定。
 *
 * 宽度估算系数（em 倍数）：
 * - 空格        0.35
 * - ASCII 字母/数字 0.55（中英混排中略窄更安全）
 * - CJK / 全角   1.0（思源宋体等 serif 实际渲染接近 1.0em，保守取整）
 * - 其余（标点/希腊字母等）0.55
 */

/** 估算单个字符的渲染宽度（px）。 */
export function estCharWidth(ch: string, fontSize: number): number {
  if (ch === ' ') return fontSize * 0.35
  if (
    (ch >= '0' && ch <= '9') ||
    (ch >= 'a' && ch <= 'z') ||
    (ch >= 'A' && ch <= 'Z')
  ) {
    return fontSize * 0.55
  }
  const code = ch.codePointAt(0) ?? 0
  if (code >= 0x2e80) return fontSize * 1.0
  return fontSize * 0.55
}

/**
 * 按估算宽度把文本切成不超过 maxWidth 的多行。
 * 保留原始 \n 段落结构；空段落以空字符串行输出（占一个行高）。
 */
export function wrapText(
  ctx: Pick<CanvasRenderingContext2D, 'font'>,
  text: string,
  maxWidth: number,
): string[] {
  const out: string[] = []
  const paragraphs = text.split(/\r?\n/)
  // 从 ctx.font 提字号："bold 18px ..." → 18（fallback 15）
  const fontSizeMatch = ctx.font.match(/(\d+)\s*px/)
  const fontSize = fontSizeMatch ? parseInt(fontSizeMatch[1], 10) : 15

  for (const para of paragraphs) {
    if (!para.trim()) {
      out.push('')
      continue
    }
    let line = ''
    let lineWidth = 0
    for (const ch of para) {
      const w = estCharWidth(ch, fontSize)
      if (lineWidth + w > maxWidth && line) {
        out.push(line)
        line = ch
        lineWidth = w
      } else {
        line += ch
        lineWidth += w
      }
    }
    if (line) out.push(line)
  }
  return out
}