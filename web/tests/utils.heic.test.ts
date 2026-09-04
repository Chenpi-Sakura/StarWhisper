import { describe, it, expect } from 'vitest'
import { isHeic } from '../src/utils/heic'

describe('isHeic', () => {
  it('true for heic brand', async () => {
    const buf = new Uint8Array(12)
    buf[4]=0x66; buf[5]=0x74; buf[6]=0x79; buf[7]=0x70
    buf[8]=0x68; buf[9]=0x65; buf[10]=0x69; buf[11]=0x63
    const f = new File([buf], 'test.heic', { type: 'image/heic' })
    expect(await isHeic(f)).toBe(true)
  })
  it('false for jpeg', async () => {
    const f = new File([new Uint8Array([0xFF,0xD8])], 'test.jpg', { type: 'image/jpeg' })
    expect(await isHeic(f)).toBe(false)
  })
})