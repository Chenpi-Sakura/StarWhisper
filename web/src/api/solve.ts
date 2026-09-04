import type { SolveResult } from '../types'

/** Hard timeout enforced on the wire (matches server-side 60s + slack). */
export const SOLVE_TIMEOUT_MS = 65_000

/** Mock-mode latency to mimic a solver response. */
export const MOCK_DELAY_MS = 800

export interface SolveOptions {
  mock: boolean
  signal?: AbortSignal
  /** EXIF Orientation (1–8) read from the JPEG. Server uses it to transform
   *  raw solver pixel coords into the browser's display coordinate system.
   *  Defaults to 1 (no rotation). */
  exifOrientation?: number
}

/**
 * Submit the user's image to the plate-solver. In mock mode the call is
 * redirected to a static fixture shipped under `/samples/`. The `signal`
 * aborts both the mock sleep AND the real fetch so cancel() is always
 * honoured — neither path can leak a response after the user gave up.
 */
export async function solveImage(
  file: File,
  options: SolveOptions,
): Promise<SolveResult> {
  const { mock, signal, exifOrientation = 1 } = options

  if (mock) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, MOCK_DELAY_MS)
      signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(signal.reason)
      })
    })
    const r = await fetch('/samples/solve_orion.json', { signal })
    if (!r.ok) throw new Error(`mock fixture HTTP ${r.status}`)
    return (await r.json()) as SolveResult
  }

  const form = new FormData()
  form.append('image', file)
  form.append('orientation', String(exifOrientation))

  const timeoutSignal = AbortSignal.timeout(SOLVE_TIMEOUT_MS)
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal

  const r = await fetch('/api/identify/solve', {
    method: 'POST',
    body: form,
    signal: combinedSignal,
  })
  return (await r.json()) as SolveResult
}

export function isTimeoutError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'TimeoutError'
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}