<script setup lang="ts">
import { computed, ref } from 'vue'

import ScanView from './views/ScanView.vue'
import IndexView from './views/IndexView.vue'
import ConstellationView from './views/ConstellationView.vue'
import StarToast from './components/common/StarToast.vue'
import { useScanStore } from './stores/scan'
import { useArtworkStore } from './stores/artwork'

type TabKey = 'scan' | 'index' | 'atlas'

const activeTab = ref<TabKey>('index')
const scan = useScanStore()
const art = useArtworkStore()

/** 页面最底层的配图：只在星空识别页且配图就绪时出现（切走页面就收掉） */
const artWash = computed(() =>
  activeTab.value === 'scan' && art.phase === 'ready' ? art.current : null,
)

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
    <!-- 星纹配图：铺在页面最底层，托盘浮在它上面（托盘纸底半透才看得见，见 ScanView） -->
    <div
      v-if="artWash"
      class="bg-art"
      :style="{ backgroundImage: `url(${artWash})` }"
      aria-hidden="true"
    ></div>

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
/* 星纹配图铺在页面最底层：z-index 0 与 .bg-atlas 同层、DOM 在其后，故压在星图水印
   之上、内容（.frame z-index 1 / .masthead z-index 50）之下。
   fixed + inset:0 让背景按视口取尺寸，1024 方图 cover 到屏幕上只放大约 1.8 倍。

   变浅的方式是「罩白纱」而不是「乘黄纸」：早期版本用 mix-blend-mode: multiply 去乘
   body 的 #e9dcba，再加 sepia(0.22)/saturate(0.4)，结果整幅画被拽成土黄——配图本身
   已经是羊皮纸淡黄色调，等于黄上加黄。现在保留原色，只在其上叠一层中性白。 */
.bg-art {
  position: fixed;
  inset: 0;
  z-index: 0;
  background-repeat: no-repeat;
  background-size: cover;
  background-position: center;
  pointer-events: none;
}
/* 中性白纱：只抬明度、不改色相。实测在无人遮挡的页边距处色相偏移 0.0°，
   即完全保留配图原色（旧的 sepia+saturate+multiply 方案是 82.5°）。
   α 越大越淡、画的残留越少，与托盘 α 连乘，见 ScanView 里那条扫描表。 */
.bg-art::after {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.42);
}
</style>
