<script setup lang="ts">
import { computed, ref } from 'vue'

import ScanView from './views/ScanView.vue'
import IndexView from './views/IndexView.vue'
import ConstellationView from './views/ConstellationView.vue'
import StarToast from './components/common/StarToast.vue'
import { useScanStore } from './stores/scan'

type TabKey = 'scan' | 'index' | 'atlas'

const activeTab = ref<TabKey>('index')
const scan = useScanStore()

const tabs: ReadonlyArray<{ key: TabKey; label: string; roman: string; mark: string }> = [
  { key: 'index', label: '观星指数', roman: 'Ⅰ', mark: 'PLATE Ⅰ · INDEX STELLARUM' },
  { key: 'scan', label: '星空识别', roman: 'Ⅱ', mark: 'PLATE Ⅱ · COGNITIO CAELI' },
  { key: 'atlas', label: '星座图鉴', roman: 'Ⅲ', mark: 'PLATE Ⅲ · MYTHOLOGIA ET LINEAE' },
]

const currentMark = computed(() => tabs.find((t) => t.key === activeTab.value)?.mark ?? '')

async function tryOrion() {
  activeTab.value = 'scan'
  try {
    const res = await fetch('/samples/orion.jpg')
    const blob = await res.blob()
    const file = new File([blob], 'orion.jpg', { type: 'image/jpeg' })
    scan.selectImage(file)
  } catch {
    // 演示数据加载失败时静默回退到 scan idle，用户可手动上传
  }
}
</script>

<template>
  <div class="app">
    <!-- 装饰层（纸纹 + 底层星图水印） -->
    <div class="grain"></div>
    <div class="bg-atlas"><i class="c1"></i><i class="c2"></i><i class="c3"></i><i class="ecliptic"></i></div>

    <!-- 报头 -->
    <header class="masthead">
      <div class="frame" style="padding-bottom: 0">
        <div class="mast-top">
          <div class="brand">
            <div class="zh">星<b>✶</b>语</div>
            <div class="en">STARWHISPER · ATLAS COELESTIS</div>
          </div>
          <div class="mast-side right">
            <div class="mast-meta">MMXXV · 概念图版</div>
            <nav class="nav">
              <button
                v-for="t in tabs"
                :key="t.key"
                class="nav-tab"
                :class="{ active: activeTab === t.key }"
                type="button"
                @click="activeTab = t.key"
              >
                <span class="rm">{{ t.roman }}</span>{{ t.label }}
              </button>
            </nav>
            <div class="page-mark">{{ currentMark }}</div>
          </div>
        </div>
      </div>
    </header>

    <main class="frame">
      <!-- 各 page 区域（一次只显示一个，但保留 v-if 以触发入场动效） -->
      <ScanView v-if="activeTab === 'scan'" />
      <IndexView v-else-if="activeTab === 'index'" @go-atlas="activeTab = 'atlas'" @try-orion="tryOrion" />
      <ConstellationView v-else @go-scan="activeTab = 'scan'" />
    </main>

    <StarToast />
  </div>
</template>

<style scoped>
.app {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
