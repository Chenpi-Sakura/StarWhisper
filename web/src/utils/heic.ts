const HEIC_BRANDS = ['heic', 'heix', 'hevc', 'hevx', 'mif1', 'msf1'] as const

export async function isHeic(file: File): Promise<boolean> {
  if (!file.type.includes('heic') && !file.type.includes('heif')
    && !file.name.endsWith('.heic') && !file.name.endsWith('.heif')) return false
  const slice = file.slice(0, 12)
  const buf = await slice.arrayBuffer()
  const view = new Uint8Array(buf)
  if (view[4] !== 0x66 || view[5] !== 0x74 || view[6] !== 0x79 || view[7] !== 0x70) return false
  const brand = String.fromCharCode(view[8], view[9], view[10], view[11])
  return (HEIC_BRANDS as readonly string[]).includes(brand)
}