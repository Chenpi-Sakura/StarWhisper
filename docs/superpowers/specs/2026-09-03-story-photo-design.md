# 星语天象 · 照片故事（Photo-Level Story）设计规格

> 版本：v1.0 | 日期：2026-09-03 | M3 启动预备
> 关联：`docs/specs/2026-08-23-starwhisper-design-m2.md`（M2 spec，本文件覆盖 §3.3 AI 故事接口）
> 关联：`docs/API.md`（上游接口事实源）
> 关联：`server/services/ai_provider.py`（AgentArts provider，P2-1 修复后 system prompt 拼在 query；本规格不动 provider，仅调上游侧）

---

## 0. 概述

### 0.1 一句话目标

把 AI 故事从「**单个星座**」重构为「**这张照片**」的故事——融合命中星座（中西 tradition）、亮星、视场中心/范围，按视角（神话/科普）讲 3 段叙事。识别完成后自动讲，**不再跟随星座 chip 切换**。

### 0.2 入规格

| 模块 | 内容 |
|---|---|
| 后端路由 | `POST /api/story`（覆盖）：接 photo-level `context` 入参 |
| 后端路由 | `POST /api/atlas-story`（新增）：保留原 `/api/story` 语义给 ConstellationView 用 |
| 后端服务 | `services/photo_story.py`（新增）：组装 user_content、缓存 key、SSE 字符级流 |
| 后端 prompt | `docs/prompts/story-photo.md`（新增文档文件，用户粘贴到 AgentArts 后台） |
| 前端 store | `useStoryStore.fetchPhotoStory(context, style, action)`（覆盖原 `fetchStoryStream`） |
| 前端 API | `web/src/api/story.ts` 改请求 shape |
| 前端组件 | `StoryPanel.vue`：watch `scanStore.solveId` 触发，不再 watch `(abbr, style)` |
| 前端测试 | story store / api / StoryPanel 测试更新 |
| 后端测试 | test_story_photo.py 改写 / test_atlas_story.py 新增 / test_photo_story.py 单测 |

### 0.3 不入规格

- 观星指数、M3 首页观星条件页 → 另起 spec
- AI provider 抽象 / AgentArts prompt 拼接逻辑 → 不动（已 P2-1 修）
- traditions JSON 数据补全 → atlas 路线独立进行
- 分享卡 / 海报导出 → M3/M4

---

## 1. 设计决策汇总

| 决策项 | 结论 | 备注 |
|---|---|---|
| 触发时机 | 识别完成后自动触发（不依赖 chip 点击） | scanStore.solveId watcher |
| chip 切换是否重讲 | **不重讲** | chip 切换仅影响星点连线绘制 |
| "重新讲述"按钮 | 保留 → `cache_bust=true` 强制重新 | photo-level 缓存仍生效 |
| 视角 | myth / science 两档 | user content 携带 style，**单一 AgentArts prompt** |
| AgentArts 服务 | 一个服务一个 prompt | 后端只拼 user_content，system prompt 由 AgentArts 后台管 |
| fallback | **不提供** | AI 失败直接 error 事件，UI 显示错误态 |
| `/api/story` 形态 | 接 photo-level context（覆盖原接口） | 字段：`lang`, `style`, `cache_bust`, `context{}` |
| `/api/atlas-story` 形态 | 保留原 `/api/story` 语义（新增） | 字段：`abbr`, `style`, `lang`, `tradition?` |
| 协议 | SSE 字符级（P2-16 沿用） | event: title / char / done / error / reset |
| 缓存 key | `sha1(canonical_json({context, style, lang}))[:16]` | 同照片同视角必命中 |
| TTL | 10min（LRU） | 与 P2-15 同 |
| API breaking change | 是 | 前端一起改，文档同步更新 |

---

## 2. 架构

### 2.1 数据流图

```
┌─────────────────────────────────────────────────────────────┐
│ 用户上传照片                                                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
        POST /api/identify/solve → SolveResult
        ┌────────────────────────────────────────────────────┐
        │ { constellations[], stars_overlay[],              │
        │   center{ra,dec}, field{w,h} }                   │
        └────────────────────────────────────────────────────┘
                          │
                          ▼
              scanStore 写入 + solveId 刷新
                          │
                          ▼
       StoryPanel watch (scanStore.solveId)
                          │
                          ▼
      storyStore.fetchPhotoStory(context, style)
                          │
                          ▼
        POST /api/story {lang, style, cache_bust, context}
                          │
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │ services/photo_story.py                              │
   │  ├─ _build_user_content(context, style, lang)       │
   │  ├─ _signature(context, style, lang) → cache_key     │
   │  ├─ LRU 命中 → preset_chars_sse 重放 (无 fallback)   │
   │  └─ miss → ai_provider.chat_stream(user_content)     │
   │       → title 一次（首个 \n 触发）                  │
   │       → char ×N（含 \n \n）                         │
   │       → done / error                                │
   └──────────────────────────────────────────────────────┘
                          │
                          ▼
        SSE event: title → char ×N → done
                          │
                          ▼
                StoryPanel 字符级渲染
```

### 2.2 文件结构变更

```
server/
├── routers/
│   ├── story.py              # 改：接 photo-level context
│   └── atlas_story.py        # 新：原 story.py 主体迁过来
├── services/
│   ├── photo_story.py        # 新：组装 + 缓存 + 流
│   └── story_fallback.py     # 保留：仅 atlas-story 使用
└── tests/
    ├── test_story_photo.py   # 改写（原 test_story.py 中 photo 部分）
    ├── test_atlas_story.py   # 新增（原 test_story.py 中 atlas 部分）
    └── test_photo_story.py   # 新增（services 单测）

web/
├── src/
│   ├── api/story.ts          # 改：streamPhotoStory() 新增；streamAtlasStory() 保留
│   ├── stores/story.ts       # 改：fetchPhotoStory / fetchAtlasStory 双签名
│   ├── components/
│   │   ├── StoryPanel.vue    # 改：watch solveId
│   │   └── AtlasStoryStatic.vue  # 不动：仍用 atlas 接口
│   └── types.ts              # 改：PhotoStoryRequest / PhotoStoryContext 新增
└── tests/
    ├── story.store.test.ts        # 改写
    ├── StoryPanel.test.ts         # 改：solveId 触发
    └── story.api.test.ts          # 新增：请求 shape + SSE 解析

docs/
└── prompts/
    └── story-photo.md        # 新增（用户粘贴到 AgentArts 后台）
```

---

## 3. API 契约

### 3.1 `POST /api/story`（覆盖 · photo-level）

**请求**：

```json
{
  "lang": "zh",
  "style": "myth",
  "cache_bust": false,
  "context": {
    "constellations": [
      {"abbr": "ori", "tradition": "western", "name": "猎户座", "latin": "Orion", "confidence": 0.95},
      {"abbr": "shen_xiu", "tradition": "chinese", "name": "参宿", "mansion": "shen"}
    ],
    "bright_stars": [
      {"bayer": "α Ori", "name": "Betelgeuse", "name_zh": "参宿四",
       "magnitude": 0.5, "constellations": ["ori", "shen_xiu"]}
    ],
    "center": {"ra": 84.0, "dec": -1.0},
    "field": {"width_deg": 12.5, "height_deg": 8.3}
  }
}
```

**字段约束**：
- `lang` ∈ `{"zh"}`（保留扩展位）
- `style` ∈ `{"myth", "science"}`
- `cache_bust` 默认 `false`；`true` 跳过 LRU 直接走 AI
- `context.constellations` 至少 1 项；空 → 400 `EMPTY_CONTEXT`
- `context.bright_stars` 可为空数组（暗星座无亮星场景）
- `context.center` / `context.field` 可选（缺省时 prompt 不带视场描述）

**SSE 响应**（200，`text/event-stream`，沿用 P2-16 字符级协议）：

```
event: title\n
data: {"title":"猎户冬夜的守望"}\n
\n
event: char\n
data: {"char":"从"}\n
\n
event: char\n
data: {"char":"猎"}\n
…
event: char\n
data: {"char":"\n"}\n
event: char\n
data: {"char":"\n"}\n
…
event: done\n
data: {"ok":true,"degraded":false,"provider":"agentarts","model":"deepseek-chat","latency_ms":1820,"cached":false}\n
\n
```

**错误响应**：

| 场景 | HTTP / 事件 | code | 备注 |
|---|---|---|---|
| AI 正常 | 200 + SSE title/char/done | — | — |
| AI 超时 | 200 + SSE `event:error` | `AI_PROVIDER_TIMEOUT` | **不**发 title/char/done |
| AI 5xx | 200 + SSE `event:error` | `AI_PROVIDER_5XX` | 同上 |
| AI 解析失败 | 200 + SSE `event:error` | `AI_PARSE_ERROR` | 同上 |
| Provider 未配 | 200 + SSE `event:error` | `AI_DISABLED` | 同上 |
| 限流触发 | 429 | `RATE_LIMITED` | HTTP 错误，不发 SSE |
| context 空 | 400 | `EMPTY_CONTEXT` | HTTP 错误，不发 SSE |
| 总时长超时 | 200 + SSE `event:error` | `STORY_TIMEOUT` | SSE 兜底（与 P2-15 总超时语义对齐） |
| 熔断中 | 200 + SSE `event:error` | `AI_CIRCUIT_OPEN` | 立即失败 |

### 3.2 `POST /api/atlas-story`（新增 · 保留原 `/api/story` 语义）

**请求**：

```json
{
  "abbr": "ori",
  "style": "myth",
  "lang": "zh",
  "tradition": "western"
}
```

**字段约束**：
- `abbr` 必填（OR `shen_xiu` / `bei_dou` / `tian_shi_yuan` 等 chinese tradition id）
- `style` ∈ `{"myth", "science"}`
- `tradition` 可选（P2-12，缺省跨 tradition 首命中）

**响应**：沿用 P2-16 字符级 SSE + P2-15 缓存 + **保留 degraded fallback**（atlas 体验需要降级兜底）。

---

## 4. UI 流程

### 4.1 StoryPanel 触发逻辑

**新**：

```typescript
// StoryPanel.vue
watch(
  () => scanStore.solveId,  // 每次新 solve 触发一次
  async () => {
    if (!scanStore.result) return
    const context = buildContext(scanStore.result)
    await storyStore.fetchPhotoStory(context, scanStore.selectedStyle, 'refetch')
  },
  { immediate: true },
)
```

**对比 P2-16**：

| 维度 | P2-16 | 本规格 |
|---|---|---|
| 触发 watch | `(props.abbr, scan.selectedStyle)` | `scanStore.solveId` |
| chip 切换 | 触发 refetch | **不**触发（仅影响星点连线绘制） |
| "重新讲述"按钮 | 触发 fresh | 触发 fresh（`cache_bust=true`） |
| 视角切换 | UI 上不再提供 tabs | story 一旦讲完就定，无切换入口 |
| 首次渲染时机 | 立即 + 等 abbr | 等 solve 完成（store 已就绪） |

> **本期决策**：UI 删掉「神话/科普」双 tab，只保留「重新讲述」按钮。style 字段保留入参（myth 固定），为未来扩展留位。

### 4.2 ScanView 协同

`solveId` 由 `scanStore.solveId` 维护：

```typescript
// scanStore.ts
async function solve(image: Blob) {
  // ... existing upload / WCS / etc.
  const result = await identifySolve(image)
  this.result = result
  this.solveId = uuid()   // 新 ID，触发下游 StoryPanel watcher
}
```

### 4.3 StoryPanel UI 状态

- `ready` — 有 title + char 流渲染中或已完成
- `loading` — 流式未到任何内容 / 首次等待
- `error` — error 事件到达，显示「故事暂不可用：{reason}」+ 重试按钮
- 不再有 constellation chip 联动显示

---

## 5. 缓存

### 5.1 key 设计

```python
import hashlib, json

def _signature(context: PhotoContext, style: str, lang: str) -> str:
    payload = {
        "context": context.model_dump(mode="json", sort_keys=True),
        "style": style,
        "lang": lang,
    }
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]
```

**关键属性**：
- 同一张照片同视角：solve 出来的 constellations/stars /center /field byte-level 一致 → key 一致 → 命中
- `context` 字段顺序无关（`sort_keys=True`）
- 中文字段名 ensure_ascii=False，编码一致即可命中
- 16 hex 字符（64 bit），LRU key 长度可控

### 5.2 LRU

- 容量：256 项（默认）
- TTL：600s（10min，与 P2-15 一致）
- `cache_bust=true` → 不查、不写、直接走 AI
- degraded 状态（error）**不**写缓存（避免错误传播）

### 5.3 缓存命中路径

```
fetchPhotoStory 入参 → _signature → LRU.get(key)
  ├─ 命中 → 一次性 yield title + char ×N + done（cached:true）
  └─ miss → ai_provider.chat_stream(user_content)
            → 累积 title/char 写 LRU（degraded 时跳过）
            → 透传 SSE 帧给前端
```

---

## 6. 错误处理

### 6.1 错误分类

| 来源 | 触发 | SSE 事件 / HTTP | UI |
|---|---|---|---|
| `AI_PROVIDER_TIMEOUT` | AgentArts HTTP 超时 | `event:error`（HTTP 200） | 错误态 |
| `AI_PROVIDER_5XX` | AgentArts HTTP 5xx | `event:error`（HTTP 200） | 错误态 |
| `AI_PARSE_ERROR` | 输出无法解析为 title + 段落 | `event:error`（HTTP 200） | 错误态 |
| `AI_DISABLED` | `AI_API_KEY` 未配 | `event:error`（HTTP 200） | 错误态（文案「AI 未配置」） |
| `AI_CIRCUIT_OPEN` | 熔断器打开 | `event:error`（HTTP 200） | 错误态（文案「服务暂不可用」） |
| `STORY_TIMEOUT` | `STORY_TOTAL_TIMEOUT` 兜底 | `event:error`（HTTP 200） | 错误态 |
| `RATE_LIMITED` | 客户端 IP 触发限流 | HTTP 429 | HTTP 错误处理 |
| `EMPTY_CONTEXT` | context.constellations 空 | HTTP 400 | HTTP 错误处理 |

### 6.2 错误传播规则

1. **error 事件后不发 done**：客户端可正确判定流结束
2. **error 事件后立即关流**：避免前端继续等待
3. **不重试**：前端手动点「重试」按钮才重新 fetch
4. **不写缓存**：error 路径不污染 LRU

---

## 7. Prompt 文件

### 7.1 文件位置

`docs/prompts/story-photo.md`（Markdown，用户复制粘贴到 AgentArts 服务后台）

### 7.2 文件结构骨架

```markdown
# 星语天象 · 照片故事系统提示词

## 角色
你是「星语天象」的星空叙事者...

## 输入
用户 content 是结构化 JSON，含:
- style: "myth" | "science"
- constellations[]: 命中的星座/星宿（abbr / tradition / name / latin / mansion）
- bright_stars[]: 亮星（bayer / name / name_zh / magnitude）
- center: 天球中心
- field: 视场范围

## 输出格式
标题（≤20字）\n\n
段落1（150-300字）\n\n
段落2（150-300字）\n\n
段落3（150-300字，可选）\n\n
（标题与第一段之间用单个 \n 分隔，由后端首 \n 切分）

## 视角切换
- style:"myth" → 神话叙事口吻
- style:"science" → 现代天文科学口吻

## 写作要求
- 开头先点出本片最重要的元素（亮度 / 视场中心 / 置信度最高）
- 配角元素（其他星座/亮星）以「同时本片还含...」一笔带过
- 不要堆砌全部元素，挑 3-5 个最有故事感的展开
```

### 7.3 后端拼接 user_content（不动 ai_provider.py 内部）

```python
# services/photo_story.py（示意）
def _build_user_content(req: PhotoStoryRequest) -> str:
    parts = [
        f"style: {req.style}",
        f"lang: {req.lang}",
        "",
        "# 这张照片命中的元素",
        f"constellations: {json.dumps([c.model_dump() for c in req.context.constellations], ensure_ascii=False)}",
        f"bright_stars: {json.dumps([s.model_dump() for s in req.context.bright_stars], ensure_ascii=False)}",
    ]
    if req.context.center:
        parts.append(f"center_ra: {req.context.center.ra}, dec: {req.context.center.dec}")
    if req.context.field:
        parts.append(f"field: {req.context.field.width_deg}x{req.context.field.height_deg} deg")
    parts.extend([
        "",
        "请按系统提示词的要求，讲一个 3 段的星空故事。",
    ])
    return "\n".join(parts)
```

ai_provider.py 的 `chat_stream` 调 AgentArts `chat_stream` 时，**仅** user_content 入参，system prompt 由 AgentArts 服务后台注入。

---

## 8. 测试策略

### 8.1 后端

| 测试文件 | 内容 | 数量（估） |
|---|---|---|
| `test_story_photo.py`（改写） | 入参校验、context 序列化、缓存命中、cache_bust、SSE 协议（沿用 P2-16）、error 路径 | 14 |
| `test_atlas_story.py`（新增） | 原 test_story.py 中 atlas 部分 + fallback 路径 | 8 |
| `test_photo_story.py`（新增） | `_build_user_content()` 单元、 `_signature()` 哈希稳定性、context 排序无关 | 6 |

### 8.2 前端

| 测试文件 | 内容 | 数量（估） |
|---|---|---|
| `story.store.test.ts`（改写） | `fetchPhotoStory` 签名、缓存命中、并发保护（P0-5 沿用）、degraded 不缓存 | 6 |
| `StoryPanel.test.ts`（改） | solveId 触发、chip 切换不重 fetch、error 态、cache_bust 触发 | 7 |
| `story.api.test.ts`（新增） | 请求 shape 校验、SSE 解析（含 char / error） | 5 |

### 8.3 手测剧本

1. 上传猎户样图 → 等待 solve → 故事面板自动出现 3 段神话故事
2. 切 chip → 故事不变（仅星点连线切换）
3. 点「重新讲述」→ 故事刷新（cache_bust）
4. 关闭 `AI_API_KEY` → 故事面板显示「故事暂不可用」（error 态）
5. 上传同一张照片 → 命中缓存（前端 `cached:true`）
6. 上传不同照片 → miss，AI 全新生成

---

## 9. 边界 case

| 场景 | 处理 |
|---|---|
| `constellations` 空 | 400 `EMPTY_CONTEXT`（不发 SSE） |
| `bright_stars` 空 | 仍生成故事，但 prompt 强调「本片无亮星」 |
| 同一张照片同视角二次请求 | 缓存命中（`_signature` 一致） |
| 同一张照片不同视角 | miss（style 入 key） |
| 切 chip 不触发 | scanStore.solveId 不变，StoryPanel watcher 不触发 |
| AI 返回空字符串 | error `AI_PARSE_ERROR` |
| AI 返回超长 (>3000 字) | 截断到 3000 字 + done（避免内存膨胀） |
| 视场中心 / field 缺省 | prompt 不带视场描述，AI 不依赖此字段 |
| 用户中途断网（AbortController） | P0-5 沿用，store 静默丢弃（不写 error） |

---

## 10. 变更日志

- 2026-09-03 v1.0 — 初版，覆盖原 `/api/story`（per-constellation），新增 `/api/atlas-story`；photo-level context；无 fallback；SSE 字符级沿用 P2-16