<script setup lang="ts">
/**
 * SampleStrip — 「星空识别」idle / error 态的样图速测条。
 *
 * 目的：评审 / 测试者手边没有星图时，点一张真实星图即可完成一次端到端识别。
 * 本组件只负责展示与抛事件，**下载与解算由调用方（ScanView）处理**，
 * 因为要复用 scan store 的 selectImage + solve 链路（EXIF 读取、mock 开关都在那里）。
 *
 * Props:
 *  - loadingId: 正在下载的样图 id（非空时整条禁用并显示"载入中"）
 *  - disabled:  额外禁用（例如 status === 'uploading'）
 * Emits:
 *  - pick: 点击某张样图
 */
import { QUICK_SAMPLES, type QuickSample } from '../data/samples'

const props = defineProps<{
  loadingId?: string | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'pick', sample: QuickSample): void
}>()

function onPick(sample: QuickSample): void {
  if (props.disabled || props.loadingId) return
  emit('pick', sample)
}
</script>

<template>
  <div class="sample-strip" data-testid="sample-strip">
    <div class="strip-head">
      <i class="rule" />
      <span class="strip-title">✦ 手边没有星图？点一张样图直接开测 ✦</span>
      <i class="rule" />
    </div>

    <div class="strip-grid">
      <button
        v-for="s in QUICK_SAMPLES"
        :key="s.id"
        type="button"
        class="sample-card"
        :class="{ busy: loadingId === s.id }"
        :disabled="disabled || Boolean(loadingId)"
        :data-testid="`sample-card-${s.id}`"
        :aria-label="`用样图 ${s.roman} ${s.title} 快速测试`"
        @click="onPick(s)"
      >
        <span class="thumb-wrap">
          <img class="thumb" :src="s.thumb" :alt="s.title" loading="lazy" />
          <span class="fig-tag">FIG. {{ s.roman }}</span>
          <span v-if="loadingId === s.id" class="busy-mask">载入中…</span>
        </span>
        <span class="card-body">
          <span class="card-title">{{ s.roman }} · {{ s.title }}</span>
          <span class="card-meta">{{ s.meta }}</span>
          <span class="card-expect">预期：{{ s.expect }}</span>
        </span>
        <span class="card-size">{{ s.size }}</span>
      </button>
    </div>

    <p class="strip-foot">
      样图为真实拍摄星图，已按公网 4MB 约束预压；点击后与自行上传完全同链路（含
      EXIF 方向校正）。解算需 15–50 秒，请耐心等待。
    </p>
  </div>
</template>

<style scoped>
.sample-strip {
  width: 100%;
  max-width: 720px;
  margin-top: 4px;
}

/* 与 plate-cap 同语法的分隔线 + 小标题 */
.strip-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.strip-head .rule {
  flex: 1;
  height: 1px;
  background: var(--line-soft);
}
.strip-title {
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--gold);
  white-space: nowrap;
}

.strip-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 12px;
}
@media (max-width: 640px) {
  .strip-grid {
    grid-template-columns: 1fr;
  }
}

.sample-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0;
  text-align: left;
  background: var(--paper-hi);
  border: 1px solid var(--line);
  cursor: pointer;
  transition: border-color 0.25s, transform 0.25s, box-shadow 0.25s;
}
.sample-card:hover:not(:disabled) {
  border-color: var(--gold);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(46, 36, 23, 0.18);
}
.sample-card:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.sample-card.busy {
  opacity: 1;
  border-color: var(--gold);
}

.thumb-wrap {
  position: relative;
  display: block;
  height: 116px;
  overflow: hidden;
  background: #171208;
  border-bottom: 1px solid var(--line-soft);
}
.thumb {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.fig-tag {
  position: absolute;
  left: 8px;
  bottom: 8px;
  font-family: var(--disp);
  font-size: 9px;
  letter-spacing: 0.24em;
  color: var(--gold-pale);
  background: rgba(23, 18, 8, 0.72);
  border: 1px solid rgba(233, 213, 162, 0.3);
  padding: 2px 7px;
}
.busy-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--cn);
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--gold-pale);
  background: rgba(23, 18, 8, 0.62);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 11px 11px;
}
.card-title {
  font-family: var(--cn);
  font-weight: 700;
  font-size: 13.5px;
  letter-spacing: 0.12em;
  color: var(--ink);
}
.card-meta {
  font-family: var(--cn);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.card-expect {
  font-family: var(--cn);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--gold);
}

.card-size {
  position: absolute;
  top: 8px;
  right: 8px;
  font-family: var(--disp);
  font-size: 9.5px;
  letter-spacing: 0.14em;
  color: var(--gold-pale);
  background: rgba(23, 18, 8, 0.6);
  padding: 2px 6px;
}

.strip-foot {
  margin: 10px 0 0;
  font-family: var(--cn);
  font-size: 11px;
  line-height: 1.8;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
  text-align: center;
}
</style>
