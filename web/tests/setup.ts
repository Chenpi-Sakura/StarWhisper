/**
 * jsdom 25 does not implement blob URL helpers. We provide minimal stubs so
 * the scan store can be exercised without a real browser.
 */
if (typeof URL.createObjectURL !== 'function') {
  let counter = 0
  URL.createObjectURL = (_obj: Blob | MediaSource | unknown): string => {
    counter += 1
    return `blob:test://${counter}`
  }
  URL.revokeObjectURL = (_url: string): void => {
    /* no-op */
  }
}

/**
 * jsdom 25 does not implement Blob.prototype.arrayBuffer. Fall back to
 * FileReader so utilities that read file headers (e.g. HEIC brand sniffing)
 * work in tests.
 */
if (typeof Blob.prototype.arrayBuffer !== 'function') {
  Blob.prototype.arrayBuffer = async function (): Promise<ArrayBuffer> {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as ArrayBuffer)
      reader.onerror = () => reject(reader.error)
      reader.readAsArrayBuffer(this)
    })
  }
}