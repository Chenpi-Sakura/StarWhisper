import { describe, it, expect } from 'vitest'
import { estCharWidth, wrapText } from '../src/utils/textWrap'

/** 分享卡实际用的字号与行宽（W-120 = 680） */
const FONT = '20px serif'
const MAX_WIDTH = 680

const fakeCtx = { font: FONT }

/** 按估算系数校验某行估算宽度不超 maxWidth */
function lineWidth(line: string): number {
  const fontSize = 20
  let w = 0
  for (const ch of line) w += estCharWidth(ch, fontSize)
  return w
}

describe('textWrap · 折行（分享卡专用）', () => {
  it('纯 CJK 长段 → 切多行，每行估算宽度不超 maxWidth', () => {
    const text = '猎户座是冬季星空最醒目的坐标，腰带三星横跨天球赤道之间，腰间悬挂着肉眼可见的猎户大星云，是一柄孕育恒星的剑。'.repeat(2)
    const lines = wrapText(fakeCtx, text, MAX_WIDTH)
    expect(lines.length).toBeGreaterThanOrEqual(3)
    for (const line of lines) {
      expect(lineWidth(line)).toBeLessThanOrEqual(MAX_WIDTH)
    }
  })

  it('回归：无空格中文段内含英文单词（AI 简介典型输入）→ 必须折行', () => {
    // 旧实现走 measureText 分支：\S+ 把整段切成一个 token → 整段一行。
    // 新实现按字符估算宽度，无论是否含 ASCII 都稳定折行。
    const text =
      '猎户座（Orion）是冬夜最壮观的星座。腰带三星横跨天球赤道，猎户大星云肉眼可见，' +
      '参宿四与参宿七分别是上肢与下肢的亮星。天狼星 Sirius 在它的东南方，冬季大三角由此展开，' +
      '每月上旬夜里最宜观测。'
    const lines = wrapText(fakeCtx, text, MAX_WIDTH)
    expect(lines.length).toBeGreaterThan(1)
    for (const line of lines) {
      expect(lineWidth(line)).toBeLessThanOrEqual(MAX_WIDTH)
    }
  })

  it('含数字与全角标点的混合文本 → 同样折行且不溢出', () => {
    const text = '视星等 0.42ᵐ，位于 1 月入夜后的东南天空（海拔约 30°），用双筒即可分辨腰带三星。'.repeat(3)
    const lines = wrapText(fakeCtx, text, MAX_WIDTH)
    expect(lines.length).toBeGreaterThan(1)
    for (const line of lines) {
      expect(lineWidth(line)).toBeLessThanOrEqual(MAX_WIDTH)
    }
  })

  it('保留 \\n 段落结构，空段落输出空行字符串', () => {
    const text = '第一段内容。\n\n第二段内容。'
    const lines = wrapText(fakeCtx, text, MAX_WIDTH)
    expect(lines).toContain('')
    expect(lines[0]).toContain('第一段')
    expect(lines[2]).toContain('第二段')
  })

  it('短文本 → 单行', () => {
    const lines = wrapText(fakeCtx, '猎户座。', MAX_WIDTH)
    expect(lines).toEqual(['猎户座。'])
  })

  it('从 ctx.font 解析字号（bold 20px → 20）', () => {
    const lines = wrapText({ font: 'bold 20px serif' }, '猎'.repeat(100), 380)
    expect(lines.length).toBeGreaterThan(1)
  })

  it('空输入 → 只有一段空串（与旧 wrapText 行为一致）', () => {
    expect(wrapText(fakeCtx, '', MAX_WIDTH)).toEqual([''])
  })
})