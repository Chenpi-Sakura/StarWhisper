import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ArtworkApiError, pollArtwork, startArtwork } from '../src/api/artwork'

// jsdom 的 AbortSignal 没有 timeout()，api 层用到它——补一个永不由时触发的桩
if (typeof AbortSignal.timeout !== 'function') {
  AbortSignal.timeout = (() => new AbortController().signal) as typeof AbortSignal.timeout
}

const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

function jsonResponse(status: number, body: unknown) {
  return { status, ok: status >= 200 && status < 300, json: async () => body }
}

describe('startArtwork', () => {
  it('POST /api/artwork 带故事正文与 lang，默认不绕缓存', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, job_id: 'j1', status: 'pending', cached: false, model: 'image-01' }))
    const out = await startArtwork('一段故事')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/artwork')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ story: '一段故事', lang: 'zh', cache_bust: false })
    expect(out.job_id).toBe('j1')
  })

  it('cache_bust 透传', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, job_id: 'j', status: 'pending', cached: false, model: 'm' }))
    await startArtwork('故事', true)
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).cache_bust).toBe(true)
  })

  it('EMPTY_STORY 错误体转成带码异常', async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { detail: { code: 'EMPTY_STORY', message: '缺少故事正文' } }))
    await expect(startArtwork('')).rejects.toMatchObject({ code: 'EMPTY_STORY' })
  })
})

describe('pollArtwork', () => {
  it('GET 带 job id 的路径', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, job_id: 'j1', status: 'ready', model: 'm', cached: false, images: ['a.jpg'] }))
    const out = await pollArtwork('j1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/artwork/j1')
    expect(out.status).toBe('ready')
    expect(out.images).toEqual(['a.jpg'])
  })

  it('404 转 ARTWORK_JOB_NOT_FOUND', async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { detail: { code: 'ARTWORK_JOB_NOT_FOUND', message: '任务不存在或已过期' } }))
    await expect(pollArtwork('gone')).rejects.toMatchObject({ code: 'ARTWORK_JOB_NOT_FOUND' })
  })

  it('422 的 detail 数组形状也能归类', async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: [{ msg: 'String should have at most 4000 characters' }] }))
    const err = (await pollArtwork('j1').catch((e: unknown) => e)) as ArtworkApiError
    expect(err).toBeInstanceOf(ArtworkApiError)
    expect(err.code).toBe('ARTWORK_BAD_REQUEST')
    expect(err.message).toContain('4000')
  })

  it('无 JSON 体的错误退化成 HTTP_<status>', async () => {
    fetchMock.mockResolvedValue({ status: 502, ok: false, json: async () => { throw new Error('no body') } })
    await expect(pollArtwork('j1')).rejects.toMatchObject({ code: 'HTTP_502' })
  })
})
