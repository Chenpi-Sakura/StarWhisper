import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync, existsSync, mkdirSync } from 'fs'
import { dirname, resolve } from 'path'

/**
 * Copy `server/data/constellations.json` into `web/src/data/` on every
 * dev start AND on every `vite build`. Without this, the frontend atlas would
 * drift from the server source of truth. The plugin runs in both phases so
 * `pnpm dev` and `pnpm build` see the same data.
 */
const copyConstellationsDataPlugin = (): Plugin => {
  const src = resolve('..', 'server', 'data', 'constellations.json')
  const dst = resolve('src', 'data', 'constellations.json')

  const copy = () => {
    if (!existsSync(src)) return
    mkdirSync(dirname(dst), { recursive: true })
    copyFileSync(src, dst)
  }

  return {
    name: 'starwhisper:copy-constellations',
    configResolved() {
      copy()
    },
    buildStart() {
      copy()
    },
  }
}

export default defineConfig({
  plugins: [vue(), copyConstellationsDataPlugin()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})