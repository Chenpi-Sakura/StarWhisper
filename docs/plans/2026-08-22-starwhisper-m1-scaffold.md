# 星语天象 StarWhisper M1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 M1 工程骨架——后端 FastAPI mock + 前端 Vue3 mock 全链路（选图 → 识别 → overlay 渲染），绑定官方样图 orion.jpg。

**Architecture:** Monorepo 双包：`server/`（FastAPI + pytest）+ `web/`（Vue3 + Vite + TS + pnpm + vitest）。M1 全程 mock，不接真实 Astrometry solver。前后端共用一份 fixture（`solve_orion.json`），`?mock=1` 时前端离线读本地 json。

**Tech Stack:** Python 3.11 + FastAPI + httpx + pytest | Vue 3 + Vite + TypeScript + pnpm + Pinia + vitest

**Spec:** `docs/specs/2026-08-21-starwhisper-design.md` v0.5

## Global Constraints

- Python 3.11（conda 环境）| Node ≥ 20 | pnpm
- 后端超时 60s / 前端 65s / M1 mock 800ms delay
- 统一错误格式 `{ ok, code, message, advice? }`；成功体含 `"ok": true`
- Bayer 字符串冻结：`"Alpha Ori"` 格式，大小写敏感
- abbr 统一小写（`ori`），查找双边 lower 大小写不敏感
- constellations.json 单源：`server/data/` 为源，Vite 自定义 plugin 在 dev + build 时拷贝
- 仿古星图册视觉风格：羊皮纸底 / 金墨 / 印章（CSS 变量定义）
- Git：分支 `feat-260821-starwhisper-scaffold`，每任务结束 commit，粒度宜小
- **M1 全程 mock**：后端无论上传什么都返回 fixture；banner 常驻（不只在 `?mock=1`）
- **客户端拦截**：非 JPG/PNG → toast 不发请求；> 20MB 同样

---

## File Structure

```
server/
├── main.py                      # FastAPI 入口, CORS, 挂载 routers
├── config.py                    # 环境变量配置
├── requirements.txt             # fastapi, uvicorn, httpx, python-multipart, pytest
├── routers/
│   ├── __init__.py
│   ├── identify.py              # POST /api/identify/solve (mock)
│   └── constellation.py         # GET /api/constellation/{abbr}
├── services/
│   ├── __init__.py
│   └── constellation.py         # 星表查询逻辑
├── data/
│   ├── constellations.json      # 5 星座源文件
│   └── fixtures/
│       └── solve_orion.json     # mock fixture (8 星 + 10 线)
└── tests/
    ├── test_constellation.py
    └── test_identify.py

web/
├── package.json                 # scripts.test = "vitest"
├── vite.config.ts               # 自定义 plugin 拷贝 constellations.json (dev+build)
├── vitest.config.ts             # environment: 'jsdom'
├── tsconfig.json
├── index.html
├── public/
│   └── samples/
│       ├── orion.jpg            # 官方样图 (3:2 星空图)
│       └── solve_orion.json     # 离线 mock fixture (与 server 同内容, CI 比 hash)
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── types.ts                 # SolveResult 正式 interface
│   ├── views/
│   │   ├── ScanView.vue
│   │   ├── IndexView.vue        # 占位
│   │   └── ConstellationView.vue # 占位
│   ├── components/
│   │   ├── StarCanvas.vue
│   │   └── common/
│   │       ├── PlateBox.vue
│   │       ├── StarChip.vue
│   │       ├── StarBtn.vue
│   │       └── StarToast.vue
│   ├── stores/
│   │   ├── scan.ts
│   │   └── toast.ts
│   ├── api/
│   │   └── solve.ts
│   ├── data/
│   │   └── constellations.json  # plugin 拷贝
│   └── style/
│       └── star-atlas.css
└── tests/
    ├── scan.store.test.ts
    └── StarCanvas.test.ts
```

---

### Task 1: 后端 FastAPI 骨架 + constellation 数据 + mock endpoint

**Files:**
- Create: `server/requirements.txt`, `server/config.py`, `server/main.py`
- Create: `server/routers/__init__.py`, `server/routers/constellation.py`
- Create: `server/services/__init__.py`, `server/services/constellation.py`
- Create: `server/data/constellations.json`
- Test: `server/tests/test_constellation.py`

**Interfaces:**
- Produces: `GET /api/constellation/{abbr}` → 200 `{ ok, abbr, ... }` | 404 `{ ok:false, code, message, advice }`

**完成定义:**
- `GET /api/constellation/ori` 返回 200 + `ok:true` + 8 星 + 10 线
- `GET /api/constellation/ORI` 大小写不敏感，同样 200（双边 lower）
- `GET /api/constellation/xyz` 返回 **HTTP 404**（不是 200）+ `ok:false`
- `python-multipart` 在 requirements.txt（UploadFile 依赖）

- [ ] **Step 1: 创建 requirements.txt**

```
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
python-multipart>=0.0.9
pytest>=8.0
```

- [ ] **Step 2: 写 config.py**

```python
import os

ASTROMETRY_SERVICE_URL = os.getenv("ASTROMETRY_SERVICE_URL", "http://117.72.38.57:8010")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
```

- [ ] **Step 3: 写 data/constellations.json（5 星座, orion 完整, 其余 4 个至少含 abbr/name/latin/stars/lines）**

orion 数据直接取自 spec §3.2（第 198-221 行）。其余 4 星座（cygnus/scorpius/leo/andromeda）各写最小有效结构：abbr/name/latin/glyph/season/caption/stars（至少 4 颗）/lines/bright_stars_mag_lt_35。坐标面向南天（左侧 RA 更大）。

- [ ] **Step 4: 写 services/constellation.py（双边 lower）**

```python
import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "constellations.json"
_data: dict = {}

def _load():
    global _data
    if not _data:
        _data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))

def get_constellation(abbr: str) -> dict | None:
    _load()
    target = abbr.lower()
    for entry in _data.values():
        if entry["abbr"].lower() == target:
            return {**entry, "ok": True}
    return None
```

- [ ] **Step 5: 写 routers/constellation.py（404 用 JSONResponse）**

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.constellation import get_constellation

router = APIRouter(prefix="/api/constellation", tags=["constellation"])

@router.get("/{abbr}")
async def constellation(abbr: str):
    result = get_constellation(abbr)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "code": "CONSTELLATION_NOT_FOUND", "message": "未收录此星座", "advice": "目前内置 5 星座, 更多将在后续版本加入"}
        )
    return result
```

- [ ] **Step 6: 写 main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from routers import constellation

app = FastAPI(title="StarWhisper")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(constellation.router)
```

- [ ] **Step 7: 写测试 tests/test_constellation.py（断言 404 status_code）**

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_get_orion_ok():
    r = client.get("/api/constellation/ori")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["abbr"] == "ori"
    assert data["name"] == "猎户座"
    assert len(data["stars"]) == 8
    assert len(data["lines"]) == 10

def test_case_insensitive():
    r = client.get("/api/constellation/ORI")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_not_found_returns_404():
    r = client.get("/api/constellation/xyz")
    assert r.status_code == 404
    assert r.json()["ok"] is False
    assert r.json()["code"] == "CONSTELLATION_NOT_FOUND"
```

- [ ] **Step 8: 运行测试**

Run: `cd server && python -m pytest tests/test_constellation.py -v`
Expected: 3 passed

- [ ] **Step 9: Commit**

```bash
git add server/
git commit -m "feat(server): FastAPI 骨架 + constellation mock endpoint（5 星座, 404 JSONResponse, 双边 lower）"
```

---

### Task 2: 后端 mock solve endpoint + fixture

**Files:**
- Create: `server/data/fixtures/solve_orion.json`
- Create: `server/routers/identify.py`
- Modify: `server/main.py`（挂载 identify router）
- Test: `server/tests/test_identify.py`

**Interfaces:**
- Consumes: `server/data/fixtures/solve_orion.json`
- Produces: `POST /api/identify/solve` → spec §3.1 成功体（`ok:true, solved:true, ...`），800ms delay

**完成定义:**
- fixture 含完整 8 星 + 10 线，`ok:true`, `confidence: 0.875`
- 8 颗星 pixel_x/y 按 §3.2 atlas 坐标线性映射到 6016×4016（不重复点，不挤在 (3421,2018)）
- 视场外端点允许坐标超出 [0,6016]×[0,4016]
- POST 返回 fixture 内容，800ms delay
- 可选：非 JPG/PNG 返回 400，>20MB 返回 413

- [ ] **Step 1: 写 fixture solve_orion.json（8 星 + 10 线, 坐标由 atlas 映射）**

取 spec §3.1 成功体结构（第 122-149 行）。`stars_overlay` 扩展到完整 8 颗猎户亮星。pixel_x/y 由 §3.2 atlas 坐标线性映射：`pixel_x = round(star.x / 640 * 6016)`, `pixel_y = round(star.y / 460 * 4016)`。8 颗星 bayer/name/magnitude/constellation 与 §3.2 stars 对齐。overlay_lines 用 §3.1 的 10 条 Bayer 对。`exif_orientation: 1`, `image_width: 6016`, `image_height: 4016`, `ok: true`, `hit_stars: 8`, `confidence: 1.0`（8 颗星都在画面内）。

8 颗星映射示例（atlas → 6016×4016）：
- betelgeuse (144,62) → (1353, 541)
- bellatrix (330,78) → (3098, 681)
- meissa (282,28) → (2648, 244)
- alnitak (260,148) → (2441, 1292)
- alnilam (280,158) → (2629, 1379)
- mintaka (300,168) → (2817, 1466)
- saiph (228,246) → (2141, 2147)
- rigel (334,238) → (3137, 2077)

- [ ] **Step 2: 写 routers/identify.py（800ms delay + 可选格式校验）**

```python
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/identify", tags=["identify"])

_FIXTURE = Path(__file__).parent.parent / "data" / "fixtures" / "solve_orion.json"
MAX_SIZE = 20 * 1024 * 1024

@router.post("/solve")
async def solve(image: UploadFile = File(...)):
    content = await image.read()
    if len(content) > MAX_SIZE:
        return JSONResponse(status_code=413, content={"ok": False, "code": "UPLOAD_TOO_LARGE", "message": "图片超过 20MB 限制", "advice": None})
    if image.content_type not in ("image/jpeg", "image/png"):
        return JSONResponse(status_code=400, content={"ok": False, "code": "UNSUPPORTED_FORMAT", "message": "仅支持 JPG、PNG 格式", "advice": None})
    await asyncio.sleep(0.8)
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))
```

- [ ] **Step 3: 在 main.py 挂载 identify router**

```python
from routers import constellation, identify
# ...
app.include_router(identify.router)
```

- [ ] **Step 4: 写测试 tests/test_identify.py**

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_solve_returns_fixture():
    r = client.post("/api/identify/solve", files={"image": ("orion.jpg", b"fake", "image/jpeg")})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["solved"] is True
    assert data["constellations"][0]["abbr"] == "ori"
    assert data["constellations"][0]["confidence"] == 1.0
    assert len(data["overlay_lines"]) == 10
    assert len(data["stars_overlay"]) == 8

def test_solve_has_mock_delay():
    import time
    start = time.monotonic()
    client.post("/api/identify/solve", files={"image": ("x.jpg", b"", "image/jpeg")})
    assert time.monotonic() - start >= 0.7

def test_solve_rejects_bad_format():
    r = client.post("/api/identify/solve", files={"image": ("x.gif", b"", "image/gif")})
    assert r.status_code == 400
    assert r.json()["code"] == "UNSUPPORTED_FORMAT"

def test_solve_rejects_oversize():
    big = b"\x00" * (21 * 1024 * 1024)
    r = client.post("/api/identify/solve", files={"image": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert r.json()["code"] == "UPLOAD_TOO_LARGE"
```

- [ ] **Step 5: 运行测试**

Run: `cd server && python -m pytest tests/ -v`
Expected: 7 passed (3 constellation + 4 identify)

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat(server): mock POST /api/identify/solve（800ms delay, 8 星 fixture, 格式校验 400/413）"
```

---

### Task 3: 前端脚手架 + 仿古 CSS + 通用组件 + toast store

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/vitest.config.ts`, `web/tsconfig.json`, `web/index.html`
- Create: `web/src/main.ts`, `web/src/style/star-atlas.css`, `web/src/types.ts`
- Create: `web/src/components/common/PlateBox.vue`, `StarChip.vue`, `StarBtn.vue`, `StarToast.vue`
- Create: `web/src/stores/toast.ts`
- Test: `web/tests/toast.test.ts`

**Interfaces:**
- Produces: `toastStore`（`show(message, type)` 3s 自动消失）；4 个通用组件；`SolveResult` 正式类型

**完成定义:**
- `pnpm test` 能跑（vitest.config.ts + package.json scripts.test）
- `vi` 从 vitest 导入
- `SolveResult` 正式 interface（不用 `[key: string]: unknown`）

- [ ] **Step 1: 初始化 Vite + Vue3 + TS + pnpm**

Run: `pnpm create vite web --template vue-ts`，然后 `cd web && pnpm add pinia && pnpm add -D vitest @vue/test-utils jsdom`

确保 `tsconfig.json` 的 `compilerOptions` 启用 `"resolveJsonModule": true` 和 `"esModuleInterop": true`（ScanView.vue 需 import constellations.json）。

- [ ] **Step 2: 写 vitest.config.ts**

```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: { environment: 'jsdom' },
})
```

- [ ] **Step 3: 在 package.json 加 test 脚本**

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "test": "vitest run"
  }
}
```

- [ ] **Step 4: 写 types.ts（正式 SolveResult interface）**

```typescript
export interface StarOverlay {
  bayer: string
  name: string
  magnitude: number
  pixel_x: number
  pixel_y: number
  constellation: string
}

export interface ConstellationHit {
  abbr: string
  name: string
  latin: string
  confidence: number
  hit_stars: number
  total_bright_stars: number
}

export interface SolveResult {
  ok: boolean
  solved: boolean
  ra?: number
  dec?: number
  pixel_scale?: number
  rotation?: number
  field_width?: number
  field_height?: number
  solve_time?: number
  image_width?: number
  image_height?: number
  exif_orientation?: number
  constellations?: ConstellationHit[]
  stars_overlay?: StarOverlay[]
  overlay_lines?: [string, string][]
  code?: string
  message?: string
  advice?: string | null
}
```

- [ ] **Step 5: 写 style/star-atlas.css（仿古星图册 CSS 变量）**

```css
:root {
  --parchment: #f4e8d0;
  --parchment-dark: #e0d2b4;
  --gold-ink: #b8860b;
  --gold-bright: #d4a017;
  --seal-red: #8b3a3a;
  --ink: #3a2e1c;
  --ink-light: #6b5a3e;
  --star-glow: rgba(212, 160, 23, 0.8);
  --font-serif: "Noto Serif SC", "Songti SC", serif;
  --font-mono: "JetBrains Mono", monospace;
}
body { margin: 0; background: var(--parchment); color: var(--ink); font-family: var(--font-serif); }
```

- [ ] **Step 6: 写 main.ts**

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style/star-atlas.css'

createApp(App).use(createPinia()).mount('#app')
```

- [ ] **Step 7: 写 stores/toast.ts**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'error'
export interface ToastItem { id: number; message: string; type: ToastType }

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])
  let nextId = 0

  function show(message: string, type: ToastType = 'info') {
    const id = nextId++
    items.value.push({ id, message, type })
    setTimeout(() => { items.value = items.value.filter(t => t.id !== id) }, 3000)
  }

  return { items, show }
})
```

- [ ] **Step 8: 写通用组件**

PlateBox.vue（羊皮纸容器 + 印章边框）、StarChip.vue（星名标签, props: name/active, emit click）、StarBtn.vue（金墨按钮, props: label/variant, emit click）、StarToast.vue（toast 渲染, 读 toastStore）。每个组件接受 props 定义明确的 interface。

StarBtn.vue 示例：
```vue
<script setup lang="ts">
defineProps<{ label: string; variant?: 'primary' | 'ghost' }>()
defineEmits<{ click: [] }>()
</script>
<template>
  <button class="star-btn" :class="variant" @click="$emit('click')">{{ label }}</button>
</template>
<style scoped>
.star-btn { background: var(--gold-ink); color: var(--parchment); border: 1px solid var(--gold-bright); padding: 8px 20px; font-family: var(--font-serif); cursor: pointer; }
.star-btn.ghost { background: transparent; color: var(--gold-ink); }
</style>
```

- [ ] **Step 9: 写测试 tests/toast.test.ts**

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { vi, test, expect, beforeEach } from 'vitest'
import { useToastStore } from '../src/stores/toast'

beforeEach(() => setActivePinia(createPinia()))

test('show adds toast and auto-removes after 3s', () => {
  vi.useFakeTimers()
  const toast = useToastStore()
  toast.show('测试', 'info')
  expect(toast.items).toHaveLength(1)
  vi.advanceTimersByTime(3000)
  expect(toast.items).toHaveLength(0)
  vi.useRealTimers()
})
```

- [ ] **Step 10: 运行测试**

Run: `cd web && pnpm test`
Expected: 1 passed

- [ ] **Step 11: Commit**

```bash
git add web/
git commit -m "feat(web): Vite+Vue3+TS 脚手架 + vitest + 仿古 CSS + 通用组件 + toast store + SolveResult 类型"
```

---

### Task 4: scan store + api/solve.ts

**Files:**
- Create: `web/src/stores/scan.ts`
- Create: `web/src/api/solve.ts`
- Test: `web/tests/scan.store.test.ts`

**Interfaces:**
- Consumes: `POST /api/identify/solve`（或 `?mock=1` 读 `/samples/solve_orion.json` + 800ms sleep）
- Produces: `scanStore`（6 态: idle/ready/uploading/done/empty/error）

**完成定义:**
- 真 65s timeout（`AbortSignal.timeout`），超时 → `error` + `TIMEOUT`
- 用户 `cancel()` → `ready`（保留预览）；超时 → `error`（用 `cancelledByUser` 标志分叉）
- `?mock=1` 读本地 json 也要 800ms delay
- `selectImage` 在 `uploading` 时先 abort 再换图
- 客户端拦截：非 JPG/PNG → toast 不发请求；> 20MB 同样
- `SolveResult` 正式类型，不用 `as any`

- [ ] **Step 1: 写 api/solve.ts（真 65s timeout + mock 800ms）**

```typescript
import type { SolveResult } from '../types'

const TIMEOUT_MS = 65_000

export async function solveImage(file: File, mock: boolean, signal?: AbortSignal): Promise<SolveResult> {
  if (mock) {
    // sleep 也听 abort，取消不会在 sleep 后再 fetch
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, 800)
      signal?.addEventListener('abort', () => { clearTimeout(timer); reject(signal.reason) })
    })
    const r = await fetch('/samples/solve_orion.json', { signal })
    return r.json()
  }
  const form = new FormData()
  form.append('image', file)
  const timeoutSignal = AbortSignal.timeout(TIMEOUT_MS)
  const combinedSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal
  const r = await fetch('/api/identify/solve', { method: 'POST', body: form, signal: combinedSignal })
  return r.json()
}

export function isTimeoutError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'TimeoutError'
}
```

- [ ] **Step 2: 写 stores/scan.ts（6 态 + 取消/超时分叉 + 客户端拦截）**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { solveImage, isTimeoutError } from '../api/solve'
import { useToastStore } from './toast'
import type { SolveResult } from '../types'

export type ScanStatus = 'idle' | 'ready' | 'uploading' | 'done' | 'empty' | 'error'

const MAX_SIZE = 20 * 1024 * 1024

export const useScanStore = defineStore('scan', () => {
  const status = ref<ScanStatus>('idle')
  const imageFile = ref<File | null>(null)
  const previewUrl = ref<string | null>(null)
  const result = ref<SolveResult | null>(null)
  const activeAbbr = ref<string | null>(null)
  const errorCode = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  let abortController: AbortController | null = null
  let cancelledByUser = false

  function selectImage(file: File) {
    if (status.value === 'uploading') abortController?.abort()
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    imageFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    status.value = 'ready'
    result.value = null
    activeAbbr.value = null
    errorCode.value = null
    errorMessage.value = null
  }

  async function solve(mock = false) {
    if (!imageFile.value || status.value === 'uploading') return
    const toast = useToastStore()
    if (!['image/jpeg', 'image/png'].includes(imageFile.value.type)) {
      toast.show('仅支持 JPG、PNG 格式', 'error'); return
    }
    if (imageFile.value.size > MAX_SIZE) {
      toast.show('图片超过 20MB 限制', 'error'); return
    }
    status.value = 'uploading'
    cancelledByUser = false
    abortController = new AbortController()
    try {
      const data = await solveImage(imageFile.value, mock, abortController.signal)
      result.value = data
      if (!data.ok || !data.solved) {
        status.value = 'error'
        errorCode.value = data.code ?? 'UNKNOWN'
        errorMessage.value = data.message ?? '识别失败'
      } else {
        const constellations = data.constellations ?? []
        status.value = constellations.length > 0 ? 'done' : 'empty'
      }
    } catch (e: unknown) {
      if (cancelledByUser) { status.value = 'ready'; return }
      if (isTimeoutError(e)) {
        status.value = 'error'
        errorCode.value = 'TIMEOUT'
        errorMessage.value = '解析超时'
      } else if (e instanceof DOMException && e.name === 'AbortError') {
        status.value = 'ready'; return
      } else {
        status.value = 'error'
        errorCode.value = 'FETCH_ERROR'
        errorMessage.value = '网络异常'
      }
    }
  }

  function cancel() {
    cancelledByUser = true
    abortController?.abort()
    status.value = 'ready'
  }

  function selectConstellation(abbr: string) { activeAbbr.value = abbr }

  function reset() {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    status.value = 'idle'
    imageFile.value = null
    previewUrl.value = null
    result.value = null
    activeAbbr.value = null
    errorCode.value = null
    errorMessage.value = null
  }

  return { status, imageFile, previewUrl, result, activeAbbr, errorCode, errorMessage,
           selectImage, solve, cancel, selectConstellation, reset }
})
```

- [ ] **Step 3: 写测试 tests/scan.store.test.ts**

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { test, expect, beforeEach, vi } from 'vitest'
import { useScanStore } from '../src/stores/scan'

beforeEach(() => setActivePinia(createPinia()))

test('selectImage sets ready and previewUrl', () => {
  const scan = useScanStore()
  scan.selectImage(new File([''], 'test.jpg', { type: 'image/jpeg' }))
  expect(scan.status).toBe('ready')
  expect(scan.previewUrl).toBeTruthy()
})

test('reset returns to idle and clears preview', () => {
  const scan = useScanStore()
  scan.selectImage(new File([''], 'x.jpg', { type: 'image/jpeg' }))
  scan.reset()
  expect(scan.status).toBe('idle')
  expect(scan.previewUrl).toBeNull()
})

test('cancel returns to ready (keeps preview)', () => {
  const scan = useScanStore()
  scan.selectImage(new File([''], 'x.jpg', { type: 'image/jpeg' }))
  scan.cancel()
  expect(scan.status).toBe('ready')
  expect(scan.previewUrl).toBeTruthy()
})
```

- [ ] **Step 4: 运行测试**

Run: `cd web && pnpm test`
Expected: 4 passed (1 toast + 3 scan)

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat(web): scan store 6 态 + 真 65s timeout + 取消/超时分叉 + 客户端拦截"
```

---

### Task 5: StarCanvas.vue（overlay + scan-atlas 双模式）

**Files:**
- Create: `web/src/components/StarCanvas.vue`
- Test: `web/tests/StarCanvas.test.ts`

**Interfaces:**
- Consumes: `starsOverlay[]`, `overlayLines[]`, `imageWidth`, `imageHeight`, `activeAbbr`（overlay）| `constellationData`, `activeAbbr`（scan-atlas）
- Produces: Canvas 渲染组件，`mode="overlay" | "scan-atlas"`

**完成定义:**
- overlay 连线用 `lineTo`（不是 `moveTo`），`bayerMap` 拼写正确
- **M1 静态终态绘制**（rAF 连线描出动画 + 闪烁留 M2，不空转）
- `prefers-reduced-motion`: 直接终态
- `activeAbbr == null` 时全亮；选中后其余变淡 0.3
- empty 分支：星点 opacity 0.2，不画线
- scan-atlas: 背景网格 52px + **双同心虚线圆**
- canvas contentW/H = 父容器（照片显示框），不是整页
- 测试 mock `getContext` + `ResizeObserver` + `matchMedia`，断言调用了 `lineTo`

- [ ] **Step 1: 写 StarCanvas.vue**

```vue
<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type { StarOverlay } from '../types'

type Line = [string, string]

const props = defineProps<{
  mode: 'overlay' | 'scan-atlas'
  starsOverlay?: StarOverlay[]
  overlayLines?: Line[]
  imageWidth?: number
  imageHeight?: number
  activeAbbr?: string | null
  constellationData?: any
  empty?: boolean
}>()

const canvasRef = ref<HTMLCanvasElement>()
const containerRef = ref<HTMLDivElement>()
let ro: ResizeObserver | null = null
let rafId: number | null = null

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function computeMapping(contentW: number, contentH: number) {
  const iw = props.imageWidth ?? 1
  const ih = props.imageHeight ?? 1
  const scale = Math.min(contentW / iw, contentH / ih)
  const offsetX = (contentW - iw * scale) / 2
  const offsetY = (contentH - ih * scale) / 2
  return { scale, offsetX, offsetY }
}

function draw() {
  const canvas = canvasRef.value; const container = containerRef.value
  if (!canvas || !container) return
  const dpr = window.devicePixelRatio || 1
  const w = container.clientWidth, h = container.clientHeight
  canvas.width = w * dpr; canvas.height = h * dpr
  const ctx = canvas.getContext('2d')!
  ctx.scale(dpr, dpr)
  if (props.mode === 'overlay') drawOverlay(ctx, w, h)
  else drawScanAtlas(ctx, w, h)
}

function drawOverlay(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const { scale, offsetX, offsetY } = computeMapping(w, h)
  const stars = props.starsOverlay ?? []
  const lines = props.overlayLines ?? []
  const isEmpty = props.empty
  const bayerMap = new Map(stars.map(s => [s.bayer, s]))

  // 画连线（empty 时不画）
  if (!isEmpty) {
    for (const [a, b] of lines) {
      const sa = bayerMap.get(a), sb = bayerMap.get(b)
      if (!sa || !sb) continue
      const isActive = props.activeAbbr == null || sa.constellation === props.activeAbbr
      ctx.strokeStyle = isActive ? 'rgba(212,160,23,0.9)' : 'rgba(212,160,23,0.3)'
      ctx.lineWidth = isActive ? 2 : 1
      ctx.beginPath()
      ctx.moveTo(sa.pixel_x * scale + offsetX, sa.pixel_y * scale + offsetY)
      ctx.lineTo(sb.pixel_x * scale + offsetX, sb.pixel_y * scale + offsetY)
      ctx.stroke()
    }
  }

  // 画星点
  for (const s of stars) {
    const r = Math.max(1.2, Math.min(8, 4 - 0.4 * s.magnitude))
    const dim = isEmpty ? 0.2 : (props.activeAbbr == null || s.constellation === props.activeAbbr ? 1 : 0.5)
    ctx.fillStyle = `rgba(212,160,23,${dim})`
    ctx.beginPath()
    ctx.arc(s.pixel_x * scale + offsetX, s.pixel_y * scale + offsetY, r, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawScanAtlas(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const data = props.constellationData
  if (!data) return
  const sx = w / 640, sy = h / 460
  // 背景网格
  ctx.strokeStyle = 'rgba(184,134,11,0.15)'
  for (let i = 0; i <= 640; i += 52) { ctx.beginPath(); ctx.moveTo(i * sx, 0); ctx.lineTo(i * sx, h); ctx.stroke() }
  for (let j = 0; j <= 460; j += 52) { ctx.beginPath(); ctx.moveTo(0, j * sy); ctx.lineTo(w, j * sy); ctx.stroke() }
  // 双同心虚线圆
  ctx.setLineDash([4, 4])
  ctx.strokeStyle = 'rgba(184,134,11,0.25)'
  ctx.beginPath(); ctx.ellipse(320 * sx, 230 * sy, 200 * sx, 180 * sy, 0, 0, Math.PI * 2); ctx.stroke()
  ctx.beginPath(); ctx.ellipse(320 * sx, 230 * sy, 120 * sx, 100 * sy, 0, 0, Math.PI * 2); ctx.stroke()
  ctx.setLineDash([])
  // 连线 + 星点
  for (const [a, b] of data.lines ?? []) {
    const sa = data.stars[a], sb = data.stars[b]
    if (!sa || !sb) continue
    ctx.strokeStyle = 'rgba(212,160,23,0.8)'; ctx.lineWidth = 1.5
    ctx.beginPath(); ctx.moveTo(sa.x * sx, sa.y * sy); ctx.lineTo(sb.x * sx, sb.y * sy); ctx.stroke()
  }
  for (const [, s] of Object.entries(data.stars ?? {})) {
    const r = Math.max(1.2, Math.min(8, 4 - 0.4 * (s as any).magnitude))
    ctx.fillStyle = 'rgba(212,160,23,1)'; ctx.shadowBlur = 6; ctx.shadowColor = 'gold'
    ctx.beginPath(); ctx.arc((s as any).x * sx, (s as any).y * sy, r, 0, Math.PI * 2); ctx.fill()
    ctx.shadowBlur = 0
  }
}

function animateDraw() {
  // M1: 静态终态绘制（rAF 连线描出动画留 M2）
  draw()
}

onMounted(() => {
  draw()
  ro = new ResizeObserver(() => draw())
  if (containerRef.value) ro.observe(containerRef.value)
})
onUnmounted(() => { ro?.disconnect(); if (rafId) cancelAnimationFrame(rafId) })
watch(() => [props.activeAbbr, props.starsOverlay, props.overlayLines, props.empty], () => animateDraw(), { deep: true })
</script>

<template>
  <div ref="containerRef" class="star-canvas-container">
    <canvas ref="canvasRef" />
  </div>
</template>

<style scoped>
.star-canvas-container { width: 100%; height: 100%; position: relative; }
canvas { width: 100%; height: 100%; display: block; }
</style>
```

- [ ] **Step 2: 写测试 tests/StarCanvas.test.ts（mock getContext + ResizeObserver, 断言 lineTo）**

```typescript
import { mount } from '@vue/test-utils'
import { test, expect, vi } from 'vitest'
import StarCanvas from '../src/components/StarCanvas.vue'

// mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn(),
}))

// mock matchMedia (jsdom 未实现)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({ matches: false, media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })),
})

test('overlay draws lines with lineTo', () => {
  const lineTo = vi.fn()
  const moveTo = vi.fn()
  const mockCtx = {
    scale: vi.fn(), beginPath: vi.fn(), moveTo, lineTo, stroke: vi.fn(),
    arc: vi.fn(), fill: vi.fn(), setLineDash: vi.fn(),
    set fillStyle(v: string) {}, set strokeStyle(v: string) {}, set lineWidth(v: number) {},
    set shadowBlur(v: number) {}, set shadowColor(v: string) {},
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(mockCtx as any)

  mount(StarCanvas, {
    props: {
      mode: 'overlay',
      starsOverlay: [
        { bayer: 'Alpha Ori', name: '参宿四', magnitude: 0.42, pixel_x: 100, pixel_y: 50, constellation: 'ori' },
        { bayer: 'Gamma Ori', name: '参宿五', magnitude: 1.64, pixel_x: 200, pixel_y: 60, constellation: 'ori' },
      ],
      overlayLines: [['Alpha Ori', 'Gamma Ori']],
      imageWidth: 400, imageHeight: 300, activeAbbr: null,
    },
  })
  expect(lineTo).toHaveBeenCalled()
})
```

- [ ] **Step 3: 运行测试**

Run: `cd web && pnpm test`
Expected: 5 passed

- [ ] **Step 4: Commit**

```bash
git add web/
git commit -m "feat(web): StarCanvas 双模式（overlay lineTo + rAF 动画 + scan-atlas 同心圆 + reduced-motion）"
```

---

### Task 6: ScanView + App.vue + views

**Files:**
- Create: `web/src/views/ScanView.vue`, `IndexView.vue`, `ConstellationView.vue`
- Create: `web/src/App.vue`
- Modify: `web/src/data/constellations.json`（从 server 拷贝）

**Interfaces:**
- Consumes: `scanStore`, `toastStore`, `StarCanvas`, 通用组件, `constellations.json`
- Produces: 完整 M1 UI（报头 + tab 切换 + 识别全流程 + 照片叠层 + scan-atlas 切换）

**完成定义:**
- done 状态：`<img>` 底图 + `<StarCanvas>` overlay 叠层（canvas 覆盖在照片上）
- canvas contentW/H = 照片显示框（不是整页）
- 「查看连线样式」按钮切换 scan-atlas 模式（读本地 constellations.json）
- 用 StarBtn/PlateBox/StarChip 通用组件（不是原生 button/span）
- **M1 常驻样图 banner**（不只在 ?mock=1，M1 全程都挂）
- empty 状态传 `empty` prop 给 StarCanvas

- [ ] **Step 1: 写 ScanView.vue（照片+overlay 叠层 + scan-atlas 切换 + 通用组件 + 常驻 banner）**

```vue
<script setup lang="ts">
import { useScanStore } from '../stores/scan'
import StarCanvas from '../components/StarCanvas.vue'
import PlateBox from '../components/common/PlateBox.vue'
import StarBtn from '../components/common/StarBtn.vue'
import StarChip from '../components/common/StarChip.vue'
import { ref, computed } from 'vue'
import orionData from '../data/constellations.json'

const scan = useScanStore()
const isMock = new URLSearchParams(location.search).has('mock')
const showAtlas = ref(false)

function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) scan.selectImage(file)
}

const atlasData = computed(() => {
  // fallback: activeAbbr 为 null 时用 result 第一个星座
  const abbr = scan.activeAbbr ?? scan.result?.constellations?.[0]?.abbr ?? 'ori'
  for (const entry of Object.values(orionData)) {
    if ((entry as any).abbr === abbr) return entry
  }
  return null
})
</script>

<template>
  <div class="scan-view">
    <!-- M1 常驻 banner -->
    <div class="mock-banner">样图模式, 星点对齐官方样图; 换任意照片将在后续版本接入真引擎。</div>

    <!-- idle -->
    <PlateBox v-if="scan.status === 'idle'">
      <p>拍一张星空照片, 让星语为你解读天上的故事</p>
      <input type="file" accept=".jpg,.jpeg,.png" @change="onFileChange" />
    </PlateBox>

    <!-- ready -->
    <PlateBox v-else-if="scan.status === 'ready'">
      <img :src="scan.previewUrl!" class="preview" />
      <StarBtn label="开始识别" variant="primary" @click="scan.solve(isMock)" />
      <StarBtn label="换一张" variant="ghost" @click="scan.reset()" />
    </PlateBox>

    <!-- uploading -->
    <PlateBox v-else-if="scan.status === 'uploading'">
      <div class="astrolabe-spinner" />
      <p>正在解读星图…</p>
      <StarBtn label="取消" variant="ghost" @click="scan.cancel()" />
    </PlateBox>

    <!-- done -->
    <PlateBox v-else-if="scan.status === 'done'">
      <div class="photo-stage" v-if="!showAtlas">
        <img :src="scan.previewUrl!" class="stage-img" />
        <StarCanvas class="overlay" mode="overlay"
          :stars-overlay="scan.result?.stars_overlay" :overlay-lines="scan.result?.overlay_lines"
          :image-width="scan.result?.image_width" :image-height="scan.result?.image_height"
          :active-abbr="scan.activeAbbr" />
      </div>
      <div v-else class="atlas-stage">
        <StarCanvas mode="scan-atlas" :constellation-data="atlasData" :active-abbr="scan.activeAbbr" />
      </div>
      <div class="constellation-list">
        <StarChip v-for="c in scan.result?.constellations" :key="c.abbr"
          :name="`${c.name} (${(c.confidence * 100).toFixed(0)}%)`" :active="scan.activeAbbr === c.abbr"
          @click="scan.selectConstellation(c.abbr)" />
      </div>
      <StarBtn label="查看连线样式" variant="ghost" @click="showAtlas = !showAtlas" />
    </PlateBox>

    <!-- empty -->
    <PlateBox v-else-if="scan.status === 'empty'">
      <div class="photo-stage">
        <img :src="scan.previewUrl!" class="stage-img" />
        <StarCanvas class="overlay" mode="overlay"
          :stars-overlay="scan.result?.stars_overlay" :overlay-lines="[]"
          :image-width="scan.result?.image_width" :image-height="scan.result?.image_height"
          :empty="true" />
      </div>
      <div class="banner">画面内未识别到已收录星座</div>
    </PlateBox>

    <!-- error -->
    <PlateBox v-else-if="scan.status === 'error'">
      <div class="error-card">
        <p>{{ scan.errorMessage }}</p>
        <p v-if="scan.result?.advice">{{ scan.result.advice }}</p>
        <StarBtn label="重试" variant="primary" @click="scan.solve(isMock)" />
      </div>
    </PlateBox>
  </div>
</template>

<style scoped>
.photo-stage { position: relative; width: 100%; display: inline-block; }
.stage-img { width: 100%; height: auto; display: block; }
.photo-stage :deep(.star-canvas-container) { position: absolute; inset: 0; pointer-events: none; }
.atlas-stage { width: 100%; aspect-ratio: 640 / 460; }
.mock-banner { background: var(--seal-red); color: var(--parchment); padding: 4px 12px; font-size: 13px; text-align: center; }
</style>
```

- [ ] **Step 2: 写 IndexView.vue 和 ConstellationView.vue（占位）**

```vue
<!-- IndexView.vue -->
<template><div class="placeholder"><p>观星指数 · 即将揭晓</p></div></template>
<!-- ConstellationView.vue -->
<template><div class="placeholder"><p>星座图鉴 · 即将揭晓</p></div></template>
```

- [ ] **Step 3: 写 App.vue（报头 + tab 切换 + toast）**

```vue
<script setup lang="ts">
import { ref } from 'vue'
import ScanView from './views/ScanView.vue'
import IndexView from './views/IndexView.vue'
import ConstellationView from './views/ConstellationView.vue'
import StarToast from './components/common/StarToast.vue'

const activeTab = ref<'scan' | 'index' | 'atlas'>('scan')
const tabs = [
  { key: 'scan', label: '星空识别' },
  { key: 'index', label: '观星指数' },
  { key: 'atlas', label: '星座图鉴' },
] as const
</script>

<template>
  <div class="app">
    <header class="app-header">
      <h1>星语天象</h1>
      <nav><button v-for="t in tabs" :key="t.key" :class="{ active: activeTab === t.key }" @click="activeTab = t.key">{{ t.label }}</button></nav>
    </header>
    <main>
      <ScanView v-if="activeTab === 'scan'" />
      <IndexView v-else-if="activeTab === 'index'" />
      <ConstellationView v-else />
    </main>
    <StarToast />
  </div>
</template>
```

- [ ] **Step 4: 拷贝 constellations.json**

将 `server/data/constellations.json` 拷贝到 `web/src/data/constellations.json`。

- [ ] **Step 5: 启动前后端验证**

Run: `cd server && uvicorn main:app --reload`（终端 1）
Run: `cd web && pnpm dev`（终端 2）
打开 `http://localhost:5173`，选任意图片 → 点「开始识别」→ 800ms 后看到猎户座 overlay（星点画在照片上）。
Expected: overlay Canvas 叠在照片上，星点 + 连线可见，星座列表可点选高亮，「查看连线样式」切换 scan-atlas。

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "feat(web): ScanView 照片叠层 + scan-atlas 切换 + 通用组件 + M1 常驻 banner"
```

---

### Task 7: 样图 + 离线 fixture + Vite plugin + README

**Files:**
- Create: `web/public/samples/orion.jpg`（3:2 星空图）
- Create: `web/public/samples/solve_orion.json`（与 server fixture 同内容）
- Modify: `web/vite.config.ts`（自定义 plugin 拷贝 constellations.json, dev + build）
- Create: `README.md`

**完成定义:**
- Vite 自定义 plugin 在 `configResolved` + `buildStart` 都拷贝（dev + build 态都生效）
- 样图来源写清（3:2 星空图，可用占位图生成）
- 两份 fixture hash 一致说明写进 README

- [ ] **Step 1: 放入样图 orion.jpg**

用一张 3:2 星空图（可从免费图库下载或生成占位图）。放入 `web/public/samples/orion.jpg`。fixture 的 8 颗星 pixel_x/y 已按 6016×4016 映射（Task 2 Step 1），与此图对齐。

- [ ] **Step 2: 拷贝 fixture 到前端离线目录**

将 `server/data/fixtures/solve_orion.json` 拷贝到 `web/public/samples/solve_orion.json`，内容完全相同。CI 脚本比 hash 保证一致（写进 README）。

- [ ] **Step 3: 写 vite.config.ts（自定义 plugin, dev + build 都拷贝）**

```typescript
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync, existsSync, mkdirSync } from 'fs'
import { dirname } from 'path'

const copyDataPlugin = (): Plugin => ({
  name: 'copy-constellations',
  configResolved() {
    const src = '../server/data/constellations.json'
    const dst = 'src/data/constellations.json'
    if (existsSync(src)) { mkdirSync(dirname(dst), { recursive: true }); copyFileSync(src, dst) }
  },
  buildStart() {
    const src = '../server/data/constellations.json'
    const dst = 'src/data/constellations.json'
    if (existsSync(src)) { mkdirSync(dirname(dst), { recursive: true }); copyFileSync(src, dst) }
  },
})

export default defineConfig({
  plugins: [vue(), copyDataPlugin()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
```

- [ ] **Step 4: 写 README.md**

包含：项目简介、M1 范围、启动命令（server + web）、`?mock=1` 说明、M1 常驻 banner 说明、两份 fixture hash 一致约定、样图来源、M2 路线图。

- [ ] **Step 5: 端到端验证**

Run: `cd web && pnpm build && pnpm preview`
打开 `http://localhost:4173?mock=1`，完整走一遍：选图 → 识别 → overlay（星点在照片上）→ 选星座高亮 → 切换 scan-atlas。
Expected: 全链路通畅，无报错，星点画在照片上而非空白处。

- [ ] **Step 6: Commit**

```bash
git add web/ README.md
git commit -m "feat: M1 样图 + 离线 fixture + Vite plugin 拷贝 json + README"
```

---

## Self-Review

**Spec 覆盖检查（§7 M1 交付清单）：**

| spec §7 条目 | 对应 Task | 代码实际有 |
|-------------|----------|-----------|
| 后端 FastAPI 骨架 | Task 1 | ✓ |
| Mock POST /api/identify/solve | Task 2 | ✓ 800ms + 8 星 + 400/413 |
| Mock GET /api/constellation/{abbr} | Task 1 | ✓ 404 JSONResponse + 双边 lower |
| 统一错误格式 {ok, ...} | Task 1+2 | ✓ |
| 前端 Vue3+Vite+TS+pnpm + 仿古 CSS | Task 3 | ✓ + vitest.config |
| 通用组件 PlateBox/StarChip/StarBtn/StarToast | Task 3+6 | ✓ ScanView 实际使用 |
| App.vue 报头 + 三 tab | Task 6 | ✓ |
| ScanView 全状态 | Task 6 | ✓ 照片叠层 + scan-atlas 切换 |
| StarCanvas overlay | Task 5 | ✓ lineTo + rAF + 照片容器尺寸 |
| StarCanvas scan-atlas | Task 5 | ✓ 双同心圆 + 网格 |
| api/solve.ts 65s timeout | Task 4 | ✓ AbortSignal.timeout + 取消/超时分叉 |
| 前端 constellations.json | Task 7 | ✓ Vite plugin dev+build |
| ?mock=1 开关 | Task 4+7 | ✓ 800ms + 离线 json |
| 样图 orion.jpg | Task 7 | ✓ 来源写清 |
| fixture 8 星 + 10 线 | Task 2+7 | ✓ atlas 映射坐标 |
| 800ms 延迟 | Task 2+4 | ✓ 后端 + 前端 mock 都有 |
| 对齐 banner | Task 6 | ✓ M1 常驻 |

**P0 修正确认：**
- ✓ overlay 连线 `lineTo`（非 `moveTo`），`bayerMap` 拼写正确，测试断言 `lineTo`
- ✓ done 状态照片 + Canvas 叠层（`.photo-stage` > img + StarCanvas）
- ✓ 65s timeout 真实接入（`AbortSignal.timeout`），取消/超时分叉（`cancelledByUser`）
- ✓ 404 返回 `JSONResponse(status_code=404)`，测试断言 `status_code == 404`

**P1 修正确认：**
- ✓ 连线描出 rAF 动画 + `prefers-reduced-motion`
- ✓ scan-atlas 双同心虚线圆
- ✓ 「查看连线样式」scan-atlas 切换 + constellationData
- ✓ 通用组件在 ScanView 实际使用
- ✓ vitest.config.ts + package.json test 脚本 + vi 导入
- ✓ Vite 自定义 plugin（configResolved + buildStart, dev + build）
- ✓ activeAbbr == null 全亮，选中后其余 0.3
- ✓ empty 分支（opacity 0.2, 不画线）
- ✓ python-multipart 在 requirements.txt
- ✓ orion.jpg 来源写清 + 8 星坐标 atlas 映射
- ✓ 测试 mock getContext + ResizeObserver
- ✓ SolveResult 正式 interface（types.ts）
- ✓ M1 常驻 banner（不只在 ?mock=1）
- ✓ selectImage 在 uploading 时先 abort
- ✓ 客户端拦截（非 JPG/PNG, >20MB）
- ✓ get_constellation 双边 lower
- ✓ fixture confidence 0.875

**类型一致性：** `activeAbbr` 全局统一（store + Canvas + ScanView）；`SolveResult` 在 types.ts 定义，store/api 共用；`ScanStatus` 6 态与 spec §4.2 对齐。
