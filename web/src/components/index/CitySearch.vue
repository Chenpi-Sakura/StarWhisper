<script setup lang="ts">
/**
 * 城市搜索框（自绘下拉，替代原生 `<datalist>`）
 *
 * 为什么不用 datalist：候选由浏览器绘制（无前缀高亮、无键盘导航），中文输入法
 * 组合态期间常不刷新，且只能靠 `@change` 拿值 —— 用户打完字直接点「查阅」时
 * 输入值往往还没同步，于是弹出「未找到该城市，请先查询再查阅」。
 *
 * 现在：本地前缀树（中文城市名）立即出结果，↑↓/Enter/Esc 全键支持，
 * 「查阅」取高亮项（无高亮取首条）—— 不再需要「先点下拉再查阅」。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import StarBtn from '../common/StarBtn.vue'
import { useStargazeStore } from '../../stores/stargaze'
import { useToastStore } from '../../stores/toast'
import type { CityOption } from '../../utils/cityTrie'

const store = useStargazeStore()
const toast = useToastStore()

const query = ref('')
const open = ref(false)
/** 高亮项下标（-1 = 无高亮，回车/查阅取首条） */
const active = ref(-1)
const box = ref<HTMLElement | null>(null)

/** 命中前缀需要高亮的切分：[高亮部分, 其余] */
function split(text: string, q: string): [string, string] {
  return text.startsWith(q) ? [text.slice(0, q.length), text.slice(q.length)] : [text, '']
}

/** 下拉行（预切分好高亮片段，避免模板里重复计算） */
const rows = computed(() =>
  store.searchResults.map((o: CityOption) => {
    const q = o.prefix ?? ''
    const [nameHead, nameTail] = q ? split(o.name, q) : [o.name, '']
    return { o, nameHead, nameTail }
  }),
)

const showEmpty = computed(
  () => open.value && !!query.value.trim() && !store.searchResults.length && !store.searching,
)

function onInput(e: Event): void {
  // 直读 el.value：Vue 的 v-model 在输入法组合态期间不更新，会丢掉中文打字的中间态
  query.value = (e.target as HTMLInputElement).value
  open.value = true
  active.value = -1
  store.search(query.value)
}

async function onFocus(): Promise<void> {
  open.value = true
  await store.ensureCityIndex()
}

function onSelect(o: CityOption): void {
  query.value = o.name
  open.value = false
  active.value = -1
  store.selectSearchResult(o)
}

/** 「查阅」：取高亮项 → 否则首条命中 → 否则给出明确反馈。 */
function onSubmit(): void {
  const list = store.searchResults
  const hit = active.value >= 0 && active.value < list.length ? list[active.value] : list[0]
  if (hit) {
    onSelect(hit)
    return
  }
  if (!query.value.trim()) {
    toast.show('请输入要查询的城市名', 'info')
    return
  }
  if (store.searching) return
  toast.show(`未找到「${query.value.trim()}」，换个说法试试`, 'info')
}

function move(step: number): void {
  const n = store.searchResults.length
  if (!n) return
  open.value = true
  if (active.value < 0) {
    active.value = step > 0 ? 0 : n - 1
    return
  }
  active.value = (active.value + step + n) % n
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    onSubmit()
  } else if (e.key === 'Escape') {
    open.value = false
    active.value = -1
  }
}

/** 点击组件外部 → 收起下拉 */
function onDocClick(e: MouseEvent): void {
  if (box.value && !box.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))

watch(store.searchResults, () => {
  active.value = -1
})
</script>

<template>
  <div ref="box" class="city-search">
    <div class="cs-row">
      <div class="cs-field">
        <input
          class="field"
          :value="query"
          placeholder="搜索城市：成都 / 阿坝 / 冷湖…"
          autocomplete="off"
          role="combobox"
          aria-label="城市搜索"
          :aria-expanded="open"
          @input="onInput"
          @focus="onFocus"
          @keydown="onKeydown"
        />
        <span v-if="store.cityIndexStatus === 'loading'" class="cs-hint">载入城市表…</span>
        <span v-else-if="store.searching" class="cs-hint">在线查询…</span>
      </div>
      <StarBtn label="查阅" @click="onSubmit" />
      <StarBtn label="◎ 自动定位" variant="gold" @click="store.locate()" />
    </div>

    <ul v-if="open && rows.length" class="cs-list" role="listbox">
      <li
        v-for="(r, i) in rows"
        :key="`${r.o.source}-${r.o.lat},${r.o.lng}`"
        class="cs-item"
        :class="{ on: i === active, online: r.o.source === 'online' }"
        role="option"
        :aria-selected="i === active"
        @mouseenter="active = i"
        @mousedown.prevent="onSelect(r.o)"
      >
        <b class="cs-name"><mark v-if="r.nameHead">{{ r.nameHead }}</mark>{{ r.nameTail }}</b>
        <span class="cs-label">{{ r.o.label }}</span>
        <span v-if="r.o.source === 'online'" class="cs-key online-tag">在线</span>
        <span v-else class="cs-key"></span>
      </li>
    </ul>

    <p v-if="showEmpty" class="cs-empty">未找到匹配城市</p>
  </div>
</template>

<style scoped>
.city-search {
  position: relative;
  flex: 1;
  min-width: 260px;
}
/* 输入框与预设下拉的图版样式（原本在 IndexView 的 scoped 样式中，
   控件移入本组件后必须一并移过来，否则子组件内部元素拿不到父组件的 scope 属性） */
.field {
  width: 100%;
  border: 1px solid var(--line-soft);
  background: #efe5c9;
  padding: 7px 12px;
  font-family: var(--cn);
  font-size: 13px;
  letter-spacing: 0.08em;
  color: var(--ink);
  transition: 0.25s;
}
.field:focus {
  outline: none;
  border-color: var(--gold);
}
.cs-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-field {
  position: relative;
  flex: 1;
  min-width: 180px;
}
.cs-hint {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: #8a7a5e;
  pointer-events: none;
}
.cs-list {
  position: absolute;
  z-index: 30;
  left: 0;
  right: 0;
  margin: 4px 0 0;
  padding: 4px 0;
  list-style: none;
  background: #fdfaf1;
  border: 1px dashed #c9b88f;
  border-radius: 4px;
  box-shadow: 0 6px 18px rgba(92, 75, 50, 0.18);
  max-height: 288px;
  overflow-y: auto;
}
.cs-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: baseline;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 14px;
}
.cs-item.on {
  background: rgba(169, 126, 47, 0.14);
}
.cs-name {
  color: #3d3226;
  font-weight: 600;
}
.cs-label {
  color: #8a7a5e;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-key {
  color: #a97e2f;
  font-size: 12px;
  font-style: italic;
}
.cs-item.online .online-tag {
  color: #8a7a5e;
  font-style: normal;
}
mark {
  background: rgba(169, 126, 47, 0.28);
  color: inherit;
  padding: 0 1px;
  border-radius: 2px;
}
.cs-empty {
  position: absolute;
  z-index: 30;
  left: 0;
  margin: 4px 0 0;
  padding: 6px 12px;
  font-size: 12px;
  color: #8a7a5e;
  background: #fdfaf1;
  border: 1px dashed #c9b88f;
  border-radius: 4px;
}
</style>
