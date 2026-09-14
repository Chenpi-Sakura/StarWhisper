/**
 * 样图速测素材完整性 —— 直接读磁盘，确保**实际发布的那份文件**能用于解算。
 *
 * 生成方式：`server/.venv/Scripts/python.exe scripts/prepare_quick_samples.py`
 * 约束来源：docs/API.md §1 关键约束 1（公网上传到上游 ≤4MB）。
 */
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { QUICK_SAMPLES } from '../src/data/samples'

const SAMPLES_DIR = resolve(__dirname, '..', 'public', 'samples')
const MAX_BYTES = 4 * 1024 * 1024

describe('样图速测素材', () => {
  it('固定两张：test1 / test2', () => {
    expect(QUICK_SAMPLES.map((s) => s.id)).toEqual(['test1', 'test2'])
  })

  it.each(QUICK_SAMPLES)('$id 全尺寸样图存在、是 JPEG 且 ≤4MB', (s) => {
    const path = resolve(SAMPLES_DIR, s.src.replace(/^\/samples\//, ''))
    expect(existsSync(path), `${path} 缺失，请重跑 prepare_quick_samples.py`).toBe(true)
    const bytes = readFileSync(path)
    // JPEG magic FF D8 —— 服务端 is_jpeg() 与上游都按此判断
    expect(bytes[0]).toBe(0xff)
    expect(bytes[1]).toBe(0xd8)
    expect(bytes.length).toBeLessThanOrEqual(MAX_BYTES)
    // 元数据里标注的体积（MB，1 位小数）应与真实体积一致，避免换图后忘改文案
    const declared = Number.parseFloat(s.size)
    expect(declared).toBeCloseTo(bytes.length / 1048576, 1)
  })

  it.each(QUICK_SAMPLES)('$id 缩略图存在且远小于全尺寸图', (s) => {
    const path = resolve(SAMPLES_DIR, s.thumb.replace(/^\/samples\//, ''))
    expect(existsSync(path), `${path} 缺失`).toBe(true)
    expect(readFileSync(path).length).toBeLessThan(60 * 1024)
  })

  it('src / thumb / fileName 三者自洽', () => {
    for (const s of QUICK_SAMPLES) {
      expect(s.src.startsWith('/samples/')).toBe(true)
      expect(s.fileName).toBe(s.src.replace('/samples/', ''))
      expect(s.thumb).toBe(s.src.replace('.jpg', '-thumb.jpg'))
    }
  })
})
