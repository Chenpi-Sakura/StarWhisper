import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useStoryStore } from '../src/stores/story'

const postStoryMock = vi.fn()

vi.mock('../src/api/story', () => ({
  postStory: (...args: unknown[]) => postStoryMock(...args),
  streamStory: vi.fn(),
  STORY_STREAM_TIMEOUT_MS: 60_000,
  getHealth: vi.fn(),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  postStoryMock.mockReset()
})

describe('storyStore.fetchStory action', () => {
  it("'refetch' 命中二级缓存时不调 postStory", async () => {
    const story = useStoryStore()
    story.current = {
      ok: true, abbr: 'ori', style: 'myth', title: 't', paragraphs: ['p'],
      provider: 'mock', model: 'm', latency_ms: 0, cached: true, degraded: false,
    }
    await story.fetchStory('ori', 'myth', 'refetch')
    expect(postStoryMock).not.toHaveBeenCalled()
  })

  it("'fresh' 强制 postStory + cacheBust=1", async () => {
    const story = useStoryStore()
    postStoryMock.mockResolvedValue({
      ok: true, abbr: 'ori', style: 'myth', title: 't2', paragraphs: ['q'],
      provider: 'mock', model: 'm', latency_ms: 1, cached: false, degraded: false,
    })
    await story.fetchStory('ori', 'myth', 'fresh')
    expect(postStoryMock).toHaveBeenCalledWith(
      expect.objectContaining({ abbr: 'ori', style: 'myth', cacheBust: 1 }),
    )
  })

  it('degraded:true 后 refetch 应重新调用 postStory', async () => {
    const story = useStoryStore()
    story.current = {
      ok: true, abbr: 'ori', style: 'myth', title: 't', paragraphs: ['p'],
      provider: 'mock', model: 'm', latency_ms: 0, cached: false, degraded: true,
      degraded_reason: 'AI_PROVIDER_DISABLED',
    }
    postStoryMock.mockResolvedValue({
      ok: true, abbr: 'ori', style: 'myth', title: 't2', paragraphs: ['q'],
      provider: 'mock', model: 'm', latency_ms: 1, cached: false, degraded: false,
    })
    await story.fetchStory('ori', 'myth', 'refetch')
    expect(postStoryMock).toHaveBeenCalled()
  })
})
