/**
 * App.vue 的页面底层星纹（.bg-art）。
 *
 * 配图不铺在图版内部，而是铺在页面最底层、托盘之下，所以这一层归 App.vue 管。
 * 三个子视图用 stub 替掉：本用例只关心 App 自己的背景层与 tab 切换，不想被
 * ScanView / IndexView 的 store 与 API 依赖拖进来。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../src/views/ScanView.vue', () => ({ default: { name: 'ScanViewStub', render: () => null } }))
vi.mock('../src/views/IndexView.vue', () => ({ default: { name: 'IndexViewStub', render: () => null } }))
vi.mock('../src/views/ConstellationView.vue', () => ({
  default: { name: 'ConstellationViewStub', render: () => null },
}))

beforeEach(() => {
  setActivePinia(createPinia())
})

async function mountApp() {
  const App = (await import('../src/App.vue')).default
  return mount(App)
}

function seed(images: string[], picked = 0) {
  return import('../src/stores/artwork').then(({ useArtworkStore }) => {
    const art = useArtworkStore()
    art.images = images
    art.picked = picked
    art.phase = 'ready'
    return art
  })
}

describe('App 页面底层星纹', () => {
  it('默认在观星指数页，不该出现底图', async () => {
    const wrapper = await mountApp()
    await seed(['https://img/a.jpg'])
    await flushPromises()
    expect(wrapper.find('.bg-art').exists()).toBe(false)
  })

  it('切到星空识别且配图就绪后，底图铺上选中的那张', async () => {
    const wrapper = await mountApp()
    await seed(['https://img/a.jpg', 'https://img/b.jpg'], 1)
    await flushPromises()

    const tab = wrapper.findAll('.nav-tab').find((b) => b.text().includes('星空识别'))
    await tab!.trigger('click')
    await flushPromises()

    const bg = wrapper.find('.bg-art')
    expect(bg.exists()).toBe(true)
    // 跟随用户挑的候选，而不是固定第一张
    expect(bg.attributes('style')).toContain('https://img/b.jpg')
  })

  it('换回别的 tab 时收掉底图（不该在图鉴页残留识别页的画）', async () => {
    const wrapper = await mountApp()
    await seed(['https://img/a.jpg'])
    await flushPromises()

    const tabs = wrapper.findAll('.nav-tab')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.bg-art').exists()).toBe(true)

    await tabs[2].trigger('click')
    await flushPromises()
    expect(wrapper.find('.bg-art').exists()).toBe(false)
  })

  it('配图未就绪（loading / error）时不给底图', async () => {
    const wrapper = await mountApp()
    const { useArtworkStore } = await import('../src/stores/artwork')
    const art = useArtworkStore()
    art.images = ['https://img/a.jpg']
    art.phase = 'loading'
    await flushPromises()

    const tab = wrapper.findAll('.nav-tab').find((b) => b.text().includes('星空识别'))
    await tab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.bg-art').exists()).toBe(false)
  })
})
