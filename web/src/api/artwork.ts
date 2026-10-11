import type { ArtworkPollResponse, ArtworkStartResponse } from '../types'

/** 单次 HTTP 请求超时：上游同步生成实测 32–38s（n=4 更久）。 */
export const ARTWORK_REQUEST_TIMEOUT_MS = 120_000
/** 轮询间隔。 */
export const ARTWORK_POLL_INTERVAL_MS = 2_000
/** 从提交到拿到结果的端到端上限；超上限即判失败，不再干等。 */
export const ARTWORK_DEADLINE_MS = 180_000

/** 带业务码的错误，便于 UI 区分"余额不足"与"任务过期"。 */
export class ArtworkApiError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ArtworkApiError'
    this.code = code
  }
}

/** 后端错误体有三形状：{detail:{code,message}} / {detail:[…]} / {detail:"…"}。 */
async function toError(r: Response): Promise<ArtworkApiError> {
  const body = (await r.json().catch(() => ({}))) as {
    detail?: { code?: string; message?: string } | Array<{ msg?: string }> | string
  }
  const d = body.detail
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    return new ArtworkApiError(d.code ?? `HTTP_${r.status}`, d.message ?? `HTTP ${r.status}`)
  }
  if (Array.isArray(d)) {
    return new ArtworkApiError('ARTWORK_BAD_REQUEST', d[0]?.msg ?? '请求不合法')
  }
  return new ArtworkApiError(`HTTP_${r.status}`, typeof d === 'string' ? d : `HTTP ${r.status}`)
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(ARTWORK_REQUEST_TIMEOUT_MS),
  })
  if (!r.ok) throw await toError(r)
  return (await r.json()) as T
}

export async function startArtwork(story: string, cacheBust = false): Promise<ArtworkStartResponse> {
  return post<ArtworkStartResponse>('/api/artwork', { story, lang: 'zh', cache_bust: cacheBust })
}

export async function pollArtwork(jobId: string): Promise<ArtworkPollResponse> {
  const r = await fetch(`/api/artwork/${encodeURIComponent(jobId)}`, {
    signal: AbortSignal.timeout(ARTWORK_REQUEST_TIMEOUT_MS),
  })
  if (!r.ok) throw await toError(r)
  return (await r.json()) as ArtworkPollResponse
}
