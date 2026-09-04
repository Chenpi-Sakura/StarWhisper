<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { useAtlasStore } from '../stores/atlas'
import StarCanvas from '../components/StarCanvas.vue'
import AtlasStoryStatic from '../components/AtlasStoryStatic.vue'
import AtlasTraditionTabs from '../components/AtlasTraditionTabs.vue'
import PlateBox from '../components/common/PlateBox.vue'
import StarChip from '../components/common/StarChip.vue'
import type { AtlasListItem, ConstellationAtlas } from '../types'

defineEmits<{
  'go-scan': []
}>()

const atlas = useAtlasStore()

const selected = ref<ConstellationAtlas | null>(null)
const loadingDetail = ref(false)

onMounted(async () => {
  await atlas.loadTraditions()
  // 默认选中 western
  await atlas.setTradition('western')
  if (atlas.currentItems.length > 0 && !selected.value) {
    await pick(atlas.currentItems[0])
  }
})

// 切换 tradition 时清选中
watch(() => atlas.currentTradition, () => {
  selected.value = null
  if (atlas.currentItems.length > 0) {
    pick(atlas.currentItems[0])
  }
})

async function pick(item: AtlasListItem) {
  loadingDetail.value = true
  try {
    selected.value = await atlas.getAtlas(item.tradition ?? 'western', item.abbr)
  } finally {
    loadingDetail.value = false
  }
}

function selectMedal(it: AtlasListItem) {
  pick(it)
}

const starTableRows = computed(() => {
  if (!selected.value?.stars) return []
  const stars = selected.value.stars
  // 选取 magnitude 最亮的 6 颗
  return Object.entries(stars)
    .map(([bayer, star]) => ({ bayer, ...star }))
    .sort((a, b) => a.magnitude - b.magnitude)
    .slice(0, 6)
})

function onMedalWheel(e: WheelEvent) {
  // smedal-row 是垂直滚动区；横向 deltaY（如触控板两指横向滑）映射成横向滚动，
  // 否则只让垂直滚轮走原生路径。
  const el = e.currentTarget as HTMLElement
  if (e.deltaY !== 0) return  // 垂直：交给 overflow-y: auto
  if (e.deltaX !== 0) {
    el.scrollLeft += e.deltaX
    e.preventDefault()
  }
}
</script>

<template>
  <div class="const-view">
    <!-- 顶部：tradition 切换 chips -->
    <AtlasTraditionTabs />

    <!-- 顶部：圆形 medal 铭牌（3 行高，鼠标滚轮滑动查看更多） -->
    <div
      v-if="atlas.currentItems.length > 0"
      class="smedal-row anim go"
      data-testid="smedal-row"
      @wheel="onMedalWheel"
    >
      <button
        v-for="it in atlas.currentItems"
        :key="it.abbr"
        class="smedal"
        :class="{ active: selected?.abbr === it.abbr }"
        type="button"
        @click="selectMedal(it)"
      >
        <span class="medal">{{ it.abbr.toUpperCase().slice(0, 3) }}</span>
        <span>{{ it.name }}</span>
      </button>
    </div>

    <!-- 空状态：tradition 无星座数据 -->
    <div v-else class="atlas-empty" data-testid="atlas-empty">
      <p class="atlas-empty-glyph">☷</p>
      <h3>该体系暂无星座数据</h3>
      <p>后续版本将逐步加入。</p>
    </div>

    <div class="const-grid">
      <!-- 左列：map + 主要亮星 -->
      <div class="left-col">
        <PlateBox plate="PLATE Ⅲ" caption="星座互动 · 唤醒星线">
          <div class="map-stage">
            <StarCanvas
              v-if="selected"
              mode="scan-atlas"
              :constellation-data="selected"
              :active-abbr="selected.abbr"
              class="map-svg"
            />
            <div v-else class="map-empty">
              <div class="big">「轻触顶部一枚星座铭牌，唤醒沉睡的星线。」</div>
              <div class="small">星点流转之间，连线将循着古图缓缓描出</div>
            </div>
          </div>
          <div v-if="selected" class="map-caption">
            已唤醒 · <b>{{ selected.name }} {{ selected.latin }}</b>
            —— <i>{{ selected.caption ?? '古图铭刻，恒星流转。' }}</i>
          </div>
        </PlateBox>

        <PlateBox plate="TAB." caption="主要亮星">
          <table v-if="starTableRows.length > 0" class="star-table">
            <thead>
              <tr>
                <th>拜耳</th>
                <th>位置</th>
                <th>星等</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in starTableRows" :key="row.bayer">
                <td class="mono">{{ row.bayer }}</td>
                <td class="mono">x={{ row.x.toFixed(0) }}, y={{ row.y.toFixed(0) }}</td>
                <td>{{ row.magnitude.toFixed(2) }}{{ row.magnitude < 1 ? 'ᵐ' : 'ᵐ' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="footnote">载入中…</p>
          <p class="table-note">ᵛ 变星 · ᵈ 双星 · 数据依依巴谷星表</p>
        </PlateBox>
      </div>

      <!-- 右列：story + nota -->
      <div class="right-col">
        <PlateBox plate="PLATE Ⅳ" caption="星座故事 · 神话与实测">
          <div v-if="selected" class="story-head">
            <div class="seal gold">{{ selected.abbr.toUpperCase().slice(0, 3) }}</div>
            <div class="head-text">
              <h3>{{ selected.name }}</h3>
              <div class="sub">{{ selected.latin }}</div>
              <div class="story-meta">
                <StarChip
                  :glyph="selected.glyph ?? '✶'"
                  variant="gold"
                  :label="`符号 ${selected.glyph ?? '✶'}`"
                />
                <StarChip :label="`当令 · ${selected.season ?? '—'}`" />
                <StarChip
                  variant="gold"
                  :label="`最亮 · ${selected.bright_stars ?? '—'} 亮星`"
                />
              </div>
            </div>
          </div>

          <!-- 星座图鉴从 traditions store 读预设文稿 -->
          <AtlasStoryStatic
            v-if="selected"
            :tradition="selected.tradition ?? 'western'"
            :abbr="selected.abbr"
          />
        </PlateBox>

        <PlateBox plate="NOTA" caption="识读小笺">
          <p class="nota-text">
            「神话」是古人写给星空的信，「科普」是星空写给今人的回信。两相对读，方见一颗星的全部。
          </p>
          <div class="chip-list-inline">
            <StarChip variant="gold" label="切换视角" />
            <StarChip label="重新讲述" />
            <StarChip variant="gold" label="生成分享卡" />
          </div>
        </PlateBox>
      </div>
    </div>
  </div>
</template>

<style scoped>
.const-view {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin-top: 8px;
}

/* smedal-row：圆形铭牌，3 行高，鼠标滚轮垂直滑动。
   高度 = 单 medal 高（58px 圆 + 7px gap + 12.5px 文字行 + 12px 上下 padding ≈ 90px） × 3 + 14px × 2 行间 gap = ~300px */
.smedal-row {
  display: flex;
  gap: 14px 18px;
  flex-wrap: wrap;
  margin-bottom: 22px;
  max-height: 300px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 6px 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--gold) rgba(201, 162, 74, 0.15);
  /* 底部加渐隐，提示可继续滑动 */
  -webkit-mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 18px), transparent 100%);
  mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 18px), transparent 100%);
}
.smedal-row::-webkit-scrollbar {
  width: 8px;
}
.smedal-row::-webkit-scrollbar-track {
  background: rgba(201, 162, 74, 0.1);
  border-radius: 4px;
}
.smedal-row::-webkit-scrollbar-thumb {
  background: var(--gold);
  border-radius: 4px;
  border: 1px solid rgba(169, 126, 47, 0.4);
}
.smedal-row::-webkit-scrollbar-thumb:hover {
  background: #8a6520;
}
.smedal {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  background: none;
  border: none;
  padding: 6px 8px;
  transition: 0.25s;
  cursor: pointer;
  flex: 0 0 auto;
}
.smedal .medal {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 1px solid var(--gold);
  display: grid;
  place-items: center;
  flex: none;
  font-family: var(--disp);
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--gold);
  font-weight: 700;
  background: radial-gradient(circle at 35% 30%, #f7efd8, #e8d8ae);
  box-shadow:
    inset 0 0 0 2px #f0e6c8,
    inset 0 0 0 3px rgba(169, 126, 47, 0.55);
  transition: 0.3s;
}
.smedal span:not(.medal) {
  font-family: var(--cn);
  font-size: 12.5px;
  letter-spacing: 0.16em;
  color: var(--ink-soft);
}
.smedal:hover .medal {
  transform: translateY(-4px);
  box-shadow:
    inset 0 0 0 2px #f0e6c8,
    inset 0 0 0 3px rgba(169, 126, 47, 0.55),
    0 10px 16px -10px rgba(120, 84, 20, 0.7);
}
.smedal.active .medal {
  background: var(--ink);
  color: var(--gold-2);
  border-color: var(--ink);
}
.smedal.active span:not(.medal) {
  color: var(--gold);
  font-weight: 700;
}

.const-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
}
@media (max-width: 1000px) {
  .const-grid {
    grid-template-columns: 1fr;
  }
}

/* 左列 / 右列布局 */
.left-col,
.right-col {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

/* map-stage */
.map-stage {
  position: relative;
  border: 1px solid var(--line);
  background: #ece0c0;
  min-height: 470px;
  display: grid;
  place-items: center;
}
.map-svg {
  width: 100%;
  height: 100%;
  display: block;
}
.map-empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  font-family: var(--cn);
  color: var(--ink-faint);
  text-align: center;
  padding: 20px;
}
.map-empty .big {
  font-size: 17px;
  font-style: italic;
  letter-spacing: 0.1em;
}
.map-empty .small {
  font-size: 12px;
}
.map-caption {
  padding: 14px 22px 0;
  border-top: 1px solid var(--line-soft);
  font-family: var(--cn);
  font-size: 13.5px;
  color: var(--ink-soft);
  min-height: 52px;
  margin-top: 12px;
}
.map-caption b {
  color: var(--gold);
}
.map-tools {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

/* story-head */
.story-head {
  display: flex;
  gap: 20px;
  align-items: center;
  padding-bottom: 18px;
  border-bottom: 3px double var(--line);
}
.story-head .seal {
  width: 72px;
  height: 72px;
  font-size: 18px;
}
.head-text h3 {
  font-family: var(--cn);
  font-weight: 900;
  font-size: 34px;
  letter-spacing: 0.16em;
  line-height: 1.2;
  margin: 0;
}
.head-text .sub {
  font-family: var(--disp);
  font-size: 11px;
  letter-spacing: 0.4em;
  color: var(--gold);
  margin-top: 4px;
}
.story-meta {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

/* NOTA plate */
.nota-text {
  font-size: 13.5px;
  color: var(--ink-soft);
  margin: 0;
}
.chip-list-inline {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}
</style>