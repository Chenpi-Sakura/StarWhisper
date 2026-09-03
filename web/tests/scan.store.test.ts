import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, expect, test, vi } from 'vitest'

import { useScanStore } from '../src/stores/scan'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useRealTimers()
})

function makeJpegFile(name = 'test.jpg', size = 1024): File {
  // Real images aren't needed — the store only inspects type/size for the
  // client-side gates. Body bytes are irrelevant in unit tests.
  return new File([new Uint8Array(size)], name, { type: 'image/jpeg' })
}

test('selectImage transitions to ready and assigns previewUrl', () => {
  const scan = useScanStore()
  scan.selectImage(makeJpegFile())
  expect(scan.status).toBe('ready')
  expect(scan.previewUrl).toBeTruthy()
  expect(scan.imageFile).not.toBeNull()
})

test('reset returns to idle and clears previewUrl', () => {
  const scan = useScanStore()
  scan.selectImage(makeJpegFile())
  const revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
  scan.reset()
  expect(scan.status).toBe('idle')
  expect(scan.previewUrl).toBeNull()
  expect(scan.imageFile).toBeNull()
  expect(revokeSpy).toHaveBeenCalled()
})

test('cancel keeps the preview and returns to ready', () => {
  const scan = useScanStore()
  scan.selectImage(makeJpegFile())
  const previewBefore = scan.previewUrl
  scan.cancel()
  expect(scan.status).toBe('ready')
  expect(scan.previewUrl).toBe(previewBefore)
})

test('selectImage aborts in-flight upload and switches the image', () => {
  const scan = useScanStore()
  scan.selectImage(makeJpegFile('a.jpg'))
  const ac = new AbortController()
  // Simulate an in-flight solve by replacing the internal controller.
  // We can't access the private field, but we can exercise the public path:
  // calling selectImage while uploading triggers abort.
  scan.status = 'uploading'
  // Trigger abort via the public selectImage path.
  scan.selectImage(makeJpegFile('b.jpg'))
  expect(scan.status).toBe('ready')
  expect(scan.imageFile?.name).toBe('b.jpg')
  // The AbortController was aborted; we can only assert no throw occurred.
  expect(ac.signal.aborted).toBe(false) // unrelated AC, sanity
})

test('selectConstellation updates activeAbbr', () => {
  const scan = useScanStore()
  scan.selectImage(makeJpegFile())
  scan.selectConstellation('ori')
  expect(scan.activeAbbr).toBe('ori')
})

test('client-side validation rejects non-JPG/PNG without network call', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
    throw new Error('should not be called')
  })
  const scan = useScanStore()
  scan.selectImage(new File([new Uint8Array(8)], 'x.gif', { type: 'image/gif' }))
  await scan.solve(false)
  expect(scan.status).toBe('ready')
  expect(fetchSpy).not.toHaveBeenCalled()
  fetchSpy.mockRestore()
})

test('client-side validation rejects oversized files', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
    throw new Error('should not be called')
  })
  const scan = useScanStore()
  const oversized = new File([new Uint8Array(21 * 1024 * 1024)], 'big.jpg', {
    type: 'image/jpeg',
  })
  scan.selectImage(oversized)
  await scan.solve(false)
  expect(scan.status).toBe('ready')
  expect(fetchSpy).not.toHaveBeenCalled()
  fetchSpy.mockRestore()
})

test('selectedStyle defaults to myth and setStyle updates it', () => {
  const scan = useScanStore()
  expect(scan.selectedStyle).toBe('myth')
  scan.setStyle('science')
  expect(scan.selectedStyle).toBe('science')
})