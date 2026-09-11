# 星座图鉴页 · 识读小笺改造（AI 简介 + 分享卡）计划

- 分支：`feat-260916-atlas-nota-ai`
- 日期：2026-09-16
- 范围：`web/` 前端 + `server/` 后端
- 改动主对象：`web/src/views/ConstellationView.vue` 右列底部内联 NOTA 板

---

## 1. 背景：当前「识读小笺」= 空壳

`web/src/views/ConstellationView.vue:181-190` 当前内容：

```vue
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
```

问题：
1. 主体是一段写死的引言，**不绑定选中星座**
2. 三个 chip **没有 `@click`**，点了什么都不发生
3. 既不告诉用户"这是什么星座"，也不引导用户"接下来做什么"

---

## 2. 目标 / 非目标

**目标**
1. 把这段改成**这个星座的读图说明**：你是谁 / 怎么找你 / 星座简介三段
2. **星座简介段**由 AgentArts 生成（手动触发），失败降级到 `caption` 字段
3. 新增「**生成分享卡**」：把当前页的你是谁/怎么找你/简介 + 二维码打包成 PNG 下载
4. 三个 chip 全部接上真实动作

**非目标**
- 不改 PLATE Ⅳ（故事板块）、 StarCanvas 渲染
- 不动 AtlasTraditionTabs 视觉与交互
- 不改 traditions 数据文件（`server/data/traditions/*/<abbr>.json`）——`caption` 字段已存在，作为降级源
- 不引入新 npm 依赖（分享卡用 Canvas 2D 直接画，不引 `html2canvas` / `html-to-image`）
- 不改 `docs/API.md` 已有的端点文档

---

## 3. 用户拍板的设计决定

| 决定点 | 选择 | 备注 |
|---|---|---|
| 触发时机 | **手动** | 板内默认空，按钮「✦ 讲讲这个星座」点击后才发请求 |
| 板面段数 | **3 段**（你是谁 + 怎么找你 + 星座简介） | 删去原「怎么读图」段，二维码不在页面渲染 |
| 风格档位 | **单档「星图导读」** | 不复用 `myth/science`，专门写 100-200 字中文短文 |
| QR 位置 | **只出现在 PNG 分享卡里** | 页面 DOM 不渲染 `<img>`，只在 Canvas 画图时通过 `new Image()` 加载到内存 |
| 分享卡内容 | 你是谁 + 怎么找你 + 星座简介 + QR + URL | Canvas 2D 直接画，不引第三方库 |
| chip 数 | 3 个全部保留 | 切换视角 / 重新讲述 / 生成分享卡 |
| 文件移动 | `httpsstarwhisper.caipiischenpi.top.png` → `web/public/qr/starwhisper-qr.png` | public/ 原样拷贝到 dist/，组件用 `${BASE_URL}qr/starwhisper-qr.png` 引用 |

---

## 4. 新板面视觉示意（页面 DOM）

```
┌─ NOTA 识读小笺 ─────────────────────────────────────────┐
│                                                         │
│ ── 你是谁 ─────────────────────────────────────────── │
│ 猎户座 Orion                                             │
│ [ 当令 冬季 ] [ 北天 ] [ 拜耳 ⍺ ⍴ ] [ 最亮 7 颗 ] │
│                                                         │
│ ── 怎么找你 ──────────────────────────────────────── │
│ ◆ 找参宿四（⍺ Betelgeuse），星等 0.42ᵐ，1 月入夜即升        │
│ ◆ 找参宿七（⍺ Rigel），星等 0.13ᵐ，参宿四右下方              │
│ ◆ 中西对照：猎户 ↔ 参宿 / 觜宿 / 毕宿（部分星）               │
│                                                         │
│ ── 星座简介 ──────────────────────────────────────── │
│                                                       │
│      [ ✦ 讲讲这个星座 ]                                  │
│                                                         │
│      （点完后 → AgentArts 输出 100-200 字简介）              │
│      （失败时降级 → traditions 里 caption 字段）             │
│                                                         │
│ [ 切换视角 ]  [ 重新讲述 ]  [ 生成分享卡 ]                    │
└─────────────────────────────────────────────────────────┘
```

---

## 5. 数据来源（全部已存在）

| 段 | 数据字段 | 来源 |
|---|---|---|
| 你是谁 · 名称 | `selected.name`、`selected.latin` | `ConstellationAtlas`（已 bind） |
| 你是谁 · chip | `season` / `hemisphere` / `glyph` / `bright_stars` | 同上 |
| 怎么找你 · 亮星 | `selected.stars` 按 `magnitude` 升序，取前 3 颗 | 同上 |
| 怎么找你 · 中西对照 | 遍历 `selected.stars[*].name_zh` 收集与英文名不同的星名 | 同上 |
| 星座简介 | 后端 `/api/atlas-nota`（AI 生成）| **新增端点** |
| 星座简介 · 降级 | `traditions/<tradition>/<abbr>.json` 的 `caption` 字段 | **已存在** |
| 分享卡 · QR | `web/public/qr/starwhisper-qr.png` | **新增静态资源** |

---

## 6. 后端：`POST /api/atlas-nota`

### 6.1 协议（仿照 `/api/atlas-story` 的非流式分支）

请求：
```json
{
  "abbr": "ori",
  "tradition": "western",   // 可选；缺省跨 tradition 首命中（向后兼容）
  "cacheBust": false,        // 可选；true 跳过缓存
  "lang": "zh"               // 暂固定 zh
}
```

响应（200）：
```json
{
  "ok": true,
  "tradition": "western",
  "abbr": "ori",
  "intro": "猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道……",
  "degraded": false,
  "source": "agentarts"      // "agentarts" | "preset" | "cache"
}
```

错误（4xx / 5xx）：
- `404 CONSTELLATION_NOT_FOUND`（abbr 找不到）
- `400 INVALID_TRADITION`（tradition 非法）
- 不走 SSE、不返回 SSE 事件；该端点**纯非流式**（一段短文，一次返回完即可）

### 6.2 实现要点

仿照 `server/routers/atlas_story.py`：
- `routers/atlas_nota.py`：路由 + 请求/响应 schema + 缓存 key + 调用 service
- `services/atlas_nota.py`：业务逻辑
- 缓存：`cachetools.TTLCache(maxsize=96, ttl=600)`，key = `(tradition, abbr)` 二维（没有 style 这一维，单档风格）
- 熔断：`services/story_throttle.get_circuit("atlas-nota")` 独立窗口（不与 atlas-story 共享——避免一处故障波及其它端点）
- 限流：`check_rate_limit(ip)`，阈值与 atlas-story 同款
- 总时长预算：复用 `STORY_TOTAL_TIMEOUT`（默认 45s）

### 6.3 失败降级

按 `atlas_story.py` 的"preset degraded fallback"约定：
1. AI 抛 `DisabledProvider` → 取 `traditions/<tradition>/<abbr>.json` 的 `caption` → `degraded:true, source:"preset"`
2. AI 抛超时/网络异常 → 同上降级
3. `caption` 也不存在 → `503 NOTE_FALLBACK_MISSING`（罕见，仅在数据损坏时出现）
4. `degraded:true` **不写缓存**（失败一次别让整场都是离线简介）

### 6.4 AI Provider

复用现成 `services/ai_provider.py`：
- `make_provider()` 单例，按 `config.AI_PROVIDER` 选择（`openai` 或 `agentarts`）
- AgentArts provider 已就绪（CLAUDE.md 写明）
- **新写一份 SYSTEM_PROMPT**（与 `SYSTEM_PROMPT = "..."` 在 `ai_provider.py:410` 风格一致）：
  > 你是「星语天象（StarWhisper）」的星座导读官。用一段 100-200 字中文短文介绍 {constellation_zh}（{latin}）。
  > 包含：神话起源或文化背景、最显著的观测特征（最亮星/形状）、观测时间提示。
  > 风格：通俗、雅致、有画面感，不要 Markdown、不要列表、不要 JSON。

---

## 7. 前端：`components/atlas/AtlasNota.vue`

### 7.1 Props

```ts
defineProps<{ constellation: ConstellationAtlas }>()
```
完全复用 `ConstellationView` 已有的 `selected`（已经是 `ConstellationAtlas`，不需要新类型）

### 7.2 内部状态

```ts
const introState = ref<{
  status: 'idle' | 'loading' | 'ready' | 'error'
  text: string
  degraded: boolean
  source: string | null
}>({ status: 'idle', text: '', degraded: false, source: null })
```

### 7.3 渲染

模板分三段，每段一根金线分隔（用 `<hr class="nota-sep">`）：

- **§ 你是谁**：标题 + chip 组
- **§ 怎么找你**：列表（≤3 条亮星 + 可选中西对照 + 兜底文案）
- **§ 星座简介**：根据 `introState.status` 切：
  - `idle` → 显「✦ 讲讲这个星座」按钮（`<StarBtn label="✦ 讲讲这个星座" @click="onGenerate" />`）
  - `loading` → 按钮变「✦ 正在讲述…」（disable）
  - `ready` → 显简介正文 + 「— Agent Arts 创作 · {time}」署名 + 「↻ 重新讲述」小链接
  - `error` → 显「暂无法访问 AI，请稍后再试」+ 重试按钮

底部三个 chip：
- 「切换视角」→ `document.querySelector('.tradition-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'center' })`
- 「重新讲述」→ 若 `introState.status === 'ready'`：重新调 `fetchAtlasNota(...)`；否则同「✦ 讲讲这个星座」按钮
- 「生成分享卡」→ `store.showShareCard = true` 或本地 ref

### 7.4 复用 `StarBtn` / `StarChip`

均已有组件，无需新增基础组件。

---

## 8. 前端：`components/atlas/AtlasShareCard.vue`

### 8.1 定位

**不可见的离屏组件**：不渲染到视口（`display: none` 或 `position: fixed; left: -99999px`），只是持有 Canvas + 暴露 `generateBlob()` 方法。
被 AtlasNota 的「生成分享卡」chip 点击触发。

### 8.2 渲染逻辑（**不引第三方**）

```ts
async function generateBlob(): Promise<Blob> {
  // 1. 加载 QR 到内存（不显示）
  const qr = await loadImage(`${import.meta.env.BASE_URL}qr/starwhisper-qr.png`)

  // 2. 构造 canvas（例 800×1100 px，米色背景）
  const canvas = document.createElement('canvas')
  canvas.width = 800; canvas.height = 1100
  const ctx = canvas.getContext('2d')!
  drawBackground(ctx)         // 米色 + 金色边框

  // 3. 绘制各段（用 canvas API 直接画，不靠 DOM 序列化）
  drawTitle(ctx, constellation)            // 「猎户座 / Orion」
  drawSection(ctx, '你是谁', youAreContent)  // 名称 + chip
  drawSection(ctx, '怎么找你', howToFind)     // 列表
  drawSection(ctx, '星座简介', intro)         // 简介正文
  drawFooter(ctx, qr, 'https://starwhisper.caipiischenpi.top')

  // 4. 输出 Blob
  return new Promise<Blob>((resolve) =>
    canvas.toBlob((b) => resolve(b!), 'image/png'),
  )
}
```

### 8.3 字体处理

- `await document.fonts.ready` 等字体加载完毕
- 标题用 `bold serif`（与板面"星语天象"标识一致），正文用 `serif`
- canvas `font` 属性 fallback：优先 `'Source Han Serif SC', 'Noto Serif CJK SC', 'Songti SC', serif`
- 米色/金色取自 `getComputedStyle(document.documentElement).getPropertyValue('--bg-paper')` 等，确保与页面一致

### 8.4 下载触发

```ts
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

文件名 `{tradition}-{abbr}-nota.png`，例：`western-ori-nota.png`。

### 8.5 失败处理

- QR 图加载失败（404 / 网络问题）→ 在 footer 区显示「（二维码暂不可用）」文字 + URL，仍可下载
- canvas `toBlob` 失败（极少见）→ toast 提示「生成失败，请重试」
- 不抛错到组件外（用户操作全程不破图）

---

## 9. 测试计划

### 9.1 后端（新增 ≥10 个用例）

`server/tests/test_atlas_nota_router.py`：
- 正常路径：mock AgentArts 返回 → 200 + `intro` + `degraded:false`
- 缓存命中：第 2 次请求不调 AI（断言 mock 调用次数）
- `cacheBust=true`：绕过缓存（断言调 AI）
- AI 抛 DisabledProvider → 降级到 `caption`，`degraded:true`
- AI 抛超时 → 同上降级
- 未知 abbr → 404 `CONSTELLATION_NOT_FOUND`
- 非法 tradition → 400 `INVALID_TRADITION`
- 限流：连续触发超阈值 → 429
- 降级不写缓存：第一次 degraded 后第二次仍能尝试调 AI
- `tradition` 缺省：跨 tradition 首命中（向后兼容）

`server/tests/test_atlas_nota_service.py`：
- `_build_user_content()`：含名称、季节、亮星、中西对照等字段
- prompt 字符串无 Markdown/JSON 痕迹（避免 AI 误输出格式）

### 9.2 前端（新增 ≥15 个用例）

`web/tests/atlas/AtlasNota.test.ts`：
- 渲染 3 段（你是谁 + 怎么找你 + 星座简介）
- 「你是谁」chip 缺字段时降级（season 缺失则不显该 chip）
- 「怎么找你」按 magnitude 排序、截前 3 颗
- 中西对照仅当 `name_zh` 存在
- 字段全空时显兜底文案
- 「✦ 讲讲这个星座」点击 → 状态 `loading` → mock `/api/atlas-nota` 返回 → 状态 `ready` + 显示简介
- AI 失败 → 状态 `error` + 显降级文字
- 「重新讲述」在 `ready` 状态下重发请求
- 「切换视角」chip 点击 → 滚动到 `.tradition-tabs`
- 「生成分享卡」chip 点击 → 调用 `AtlasShareCard.generateBlob()` + 触发下载
- 切换选中星座 → 简介状态重置为 `idle`

`web/tests/atlas/AtlasShareCard.test.ts`：
- 加载 QR → 生成 Blob → 下载（mock `URL.createObjectURL` + `<a>.click()`）
- QR 加载失败 → 显「（二维码暂不可用）」文字，仍下载
- `intro` 为空 → 仍能生成画布（不崩溃）
- canvas 尺寸验证（800×1100 ±5px 容忍）
- 文件名 = `{tradition}-{abbr}-nota.png`

`web/tests/ConstellationView.test.ts`（改 2-3 处）：
- 不再断言内联 NOTA 文案
- 断言 `<AtlasNota>` 被渲染且传 `:constellation`

---

## 10. 文件清单

**新增**
```
server/routers/atlas_nota.py                              # 端点
server/services/atlas_nota.py                              # 业务逻辑 + prompt
server/tests/test_atlas_nota_router.py                     # 路由测试
server/tests/test_atlas_nota_service.py                     # service 测试
web/src/components/atlas/AtlasNota.vue                     # 主组件（你+怎么找+简介）
web/src/components/atlas/AtlasShareCard.vue                # 离屏分享卡渲染器
web/src/api/atlasNota.ts                                    # 前端 fetch 封装
web/src/composables/useAtlasNota.ts                         # 可选：状态/副作用 hook（简单就放组件本地）
web/tests/atlas/AtlasNota.test.ts
web/tests/atlas/AtlasShareCard.test.ts
docs/plans/2026-09-16-atlas-nota-ai.md                     # 本文档
```

**修改**
```
web/src/views/ConstellationView.vue           # 删内联 NOTA（约 15 行 markup + 15 行 CSS），改成 <AtlasNota :constellation="selected" />
web/src/style/star-atlas.css                  # 加 .nota-sep / .nota-section-title 等 NOTE 板专用样式（约 25 行）
server/services/ai_provider.py                # 加 ATLAS_NOTA_SYSTEM_PROMPT（与现有 SYSTEM_PROMPT 同款写一行）
server/config.py                              # 如需新 STORY_NOTA_TIMEOUT 等配置项；不加也能复用
docs/API.md                                   # 文档化新端点（brief；改动不影响既有接口）
```

**文件移动（仓库内 rename）**
```
httpsstarwhisper.caipiischenpi.top.png  →  web/public/qr/starwhisper-qr.png
```

---

## 11. Commit 计划（分支上逐步提交，最后 squash）

1. `chore(atlas): 移入 StarWhisper 图鉴二维码静态资源`（QR 文件 + 目录）
2. `feat(server): 新增 /api/atlas-nota 端点（AI 简介 + 缓存 + 降级）`（后端实现）
3. `test(server): atlas-nota 端点 + service 覆盖`（后端测试）
4. `feat(atlas): AtlasNota 组件骨架（你是谁 + 怎么找你两段）`（先按 selected 数据渲染）
5. `feat(atlas): 星座简介段接入 AI（手动触发 + 降级）`（接后端 + loading/error 态）
6. `feat(atlas): 生成分享卡（Canvas 2D + 二维码嵌入 + PNG 下载）`（AtlasShareCard）
7. `feat(atlas): NOTE 板底部三 chip 接线 + 集成到 ConstellationView`（切视角/重讲/分享卡 + 替换内联）
8. `test(web): AtlasNota/AtlasShareCard + ConstellationView 更新`（前端测试）
9. `docs: 计划书 + API.md 更新`（本文件 + docs/API.md 新端点）

每步跑 `pnpm test` / `pytest -q` / `pnpm build` / `vue-tsc --noEmit`。

---

## 12. 风险与边界

| 风险 | 缓解 |
|---|---|
| AgentArts 长时间不可用 | 降级到 `caption`（已有）+ degraded 不写缓存，下一次仍尝试 AI |
| 简介 prompt 输出 Markdown 列表 | prompt 明文禁止 Markdown/JSON；后端再加一道 `clean_markdown()`（与 atlas-story 同款复用） |
| Canvas 画中文文本字体丢失 | `await document.fonts.ready` + canvas font 走 fallback 链；测试用 jsdom mock |
| QR 图部署丢失 | public/ 走 vite 原样拷贝；测试断言 `dist/qr/` 存在 |
| 简介正文带数据敏感字符（<> 等） | canvas 文本 API 自带转义；不拼 HTML |
| 用户反复点「生成分享卡」 | 防抖 500ms；同时进行的下载只触发一次 |
| 同一星座多次切 tradition 都触发 | 简介状态在 tradition 切换时**也**重置为 idle（与切选中星座同处理） |
| AtlasStoryStatic 的 preset 与降级 caption 撞文案 | 简介段说"导读"，PLATE Ⅳ 说"故事"，两者侧重点不同，不冲突 |

---

## 13. 验收标准

1. 打开 atlas 页 → 选「猎户座」→ 「你是谁」正确显示4 个 chip；「怎么找你」列最亮 3 颗星；「星座简介」是 idle 态，显示按钮
2. 点「✦ 讲讲这个星座」→ 显 loading → 显 AgentArts 生成的简介（≥100 字，≤200 字，无 Markdown）
3. 模拟 AgentArts 失败 → 显 `caption`（"冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。"）+ `degraded:true` 标记
4. 切到「天蝎座」→ 简介段自动重置为 idle（不继承上一段内容）
5. 切 tradition（western ⇄ chinese）→ 简介段重置 + 「你是谁」chip 按对应 tradition 数据更新
6. 点「生成分享卡」→ 浏览器下载 `western-ori-nota.png`，打开是 800×1100 PNG，含标题/三段/QR/URL
7. 切到 PLATE Ⅳ 故事区不受影响（仍然双视角静态文稿）
8. `pnpm test` 223+ 通过、`pytest -q` 214+ 通过、`pnpm build` 通过、`vue-tsc --noEmit` 通过

---

## 14. 不做清单（再次明确）

- ❌ 不改 PLATE Ⅳ / AtlasTraditionTabs / StarCanvas 视觉与交互
- ❌ 不动 traditions 数据文件（`caption` 字段已存在）
- ❌ 不引新 npm 依赖
- ❌ 不改 `/api/atlas-story` 既有协议
- ❌ 不在页面 DOM 渲染 QR `<img>`