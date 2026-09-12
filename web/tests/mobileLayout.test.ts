/**
 * 观星指数页移动端布局回归守卫
 *
 * 背景：390px 真机实测发现三类问题（2026-09-12）——
 *  1. `main.frame` 的 `overflow-x: clip` 会把越界内容直接裁掉（不滚动），
 *     所以任何"被固定宽度撑宽"的容器都会表现为**右侧内容被切掉**；
 *     根因是 `.index-grid` 单列用了 `1fr`（最小尺寸 = auto）被 plate 内
 *     仪表盘（280px）顶到 366px，窄屏整块图版溢出；
 *  2. `.gauge-wrap` 两列（auto + 1fr）在窄屏把 1fr 列压到 0 宽，等级印章
 *     溢出行外、等级描述一字一行；
 *  3. 报头右侧栏被品牌挤到 ~104px，三个 nav tab 变成一字一行竖排。
 *
 * jsdom 没有布局引擎（测不到"谁溢出了谁"），因此这里守的是**修复契约本身**：
 * 关键选择器必须落在对应断点的 `@media` 块内。真机视觉验证走 CDP/headless
 * 浏览器（见 docs/fix-notes 记录），本文件防的是"以后有人把规则删了/挪出断点"。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

function read(rel: string): string {
  return readFileSync(resolve(__dirname, '..', rel), 'utf8')
}

/** 抽出 `<style>` 内容（SFC）或整份 CSS。 */
function css(file: string): string {
  const src = read(file)
  const m = src.match(/<style[^>]*>([\s\S]*?)<\/style>/)
  return m ? m[1] : src
}

/**
 * 提取 `@media (max-width: Npx)` 块的正文（花括号配对，容忍嵌套规则）。
 * 找不到该断点返回空串——这样"规则被挪到别的断点"也会测失败。
 */
function mediaBlock(source: string, maxWidth: number): string {
  const open = new RegExp(`@media\\s*\\(max-width:\\s*${maxWidth}px\\)\\s*\\{`).exec(source)
  if (!open) return ''
  let depth = 0
  const start = open.index + open[0].length - 1
  for (let i = start; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(start + 1, i)
    }
  }
  return ''
}

describe('观星指数页移动端布局契约', () => {
  const indexView = css('src/views/IndexView.vue')
  const globalCss = read('src/style/star-atlas.css')
  const citySearch = css('src/components/index/CitySearch.vue')
  const trendBars = css('src/components/index/TrendBars.vue')
  const moonCard = css('src/components/index/MoonCard.vue')

  const m1000 = mediaBlock(indexView, 1000)
  const m620 = mediaBlock(indexView, 620)

  it('单列图版必须 minmax(0, 1fr)：1fr 会被仪表盘 280px 撑宽 → 整块内容被裁', () => {
    expect(m1000).toContain('.index-grid')
    expect(m1000).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    // 防止回退成会把容器顶宽的裸 1fr
    expect(m1000).not.toMatch(/grid-template-columns:\s*1fr\s*;/)
  })

  it('≤620px：仪表盘与等级印章改单列并收小印章（否则 1fr 列被压到 0 宽）', () => {
    expect(m620).toContain('.gauge-wrap')
    expect(m620).toMatch(/\.gauge-wrap\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    expect(m620).toMatch(/\.gauge-meta \.seal\s*\{[^}]*width:\s*96px/)
    // 等级描述不再一字一行（去掉 23px 大字与窄列的组合）
    expect(m620).toMatch(/\.gauge-meta \.lv-desc\s*\{[^}]*font-size:\s*17px/)
  })

  it('≤620px：起/止区间选择器成组换行 + 行动按钮竖排铺满', () => {
    expect(m620).toMatch(/\.range-picker \.range-hint\s*\{[^}]*flex:\s*1 1 100%/)
    expect(m620).toMatch(/\.actions\s*\{[^}]*flex-direction:\s*column/)
  })

  it('≤620px：报头导航整行、tab 不换行；plate 内衬收紧', () => {
    const g620 = mediaBlock(globalCss, 620)
    expect(g620).toMatch(/\.nav-tab\s*\{[^}]*white-space:\s*nowrap/)
    expect(g620).toMatch(/\.nav-tab\s*\{[^}]*flex:\s*1 1 0/)
    expect(g620).toMatch(/\.mast-top\s*\{[^}]*display:\s*block/)
    // 报头在 main.frame 之外，不受 overflow-x: clip 保护 → 负右边距必须归零
    expect(g620).toMatch(/\.brand \.zh\s*\{[^}]*margin-right:\s*0/)
    expect(g620).toMatch(/\.plate-body\s*\{[^}]*padding:\s*18px 16px/)
    expect(g620).toMatch(/\.f-title h1\s*\{[^}]*margin:\s*6px 0 0/)
  })

  it('≤620px：城市搜索去掉 260px 硬下限，输入框独占一行', () => {
    const c620 = mediaBlock(citySearch, 620)
    expect(c620).toMatch(/\.city-search\s*\{[^}]*min-width:\s*0/)
    expect(c620).toMatch(/\.cs-field\s*\{[^}]*flex:\s*1 1 100%/)
  })

  it('≤620px：趋势图收高、隐藏竖排说明，避免小时标签叠字', () => {
    const t620 = mediaBlock(trendBars, 620)
    expect(t620).toMatch(/\.chart-box\s*\{[^}]*height:\s*150px/)
    expect(t620).toMatch(/\.chart-ylab\s*\{[^}]*display:\s*none/)
    expect(t620).toMatch(/\.axis-slot\s*\{[^}]*font-size:\s*8\.5px/)
  })

  it('≤620px：月相卡显式单列（minmax(230px,1fr) 会撑宽图版）', () => {
    const mo620 = mediaBlock(moonCard, 620)
    expect(mo620).toMatch(/\.moon-sun\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  })
})
