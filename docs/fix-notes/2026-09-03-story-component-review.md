# 星座故事组件现状调研与问题清单

> 调研时间：2026-09-03 · 只做调查与报告，**未改动任何代码**
> 范围：`server/routers/story.py`、`server/services/ai_provider.py`、`server/services/story_fallback.py`、
> `web/src/api/story.ts`、`web/src/stores/story.ts`、`web/src/components/StoryPanel.vue`、
> `web/src/components/AtlasStoryStatic.vue`、`web/src/views/ScanView.vue`、`web/src/views/ConstellationView.vue`

---

## 1. 实现全貌

### 1.1 两条互不往来链路

| | 链路 A（AI 生成） | 链路 B（静态预设） |
|---|---|---|
| 入口 | `ScanView.vue:539` 识别成功后展开 | `ConstellationView.vue:174` 图鉴页常驻 |
| UI 组件 | `StoryPanel.vue` | `AtlasStoryStatic.vue` |
| 状态 | Pinia `stores/story.ts` | Pinia `stores/atlas.ts` |
| 接口 | `POST /api/story/stream`（SSE） | 无（`/api/constellation/{t}/{abbr}` 顺带下发） |
| 数据源 | AgentArts 智能体运行时 | `server/data/traditions/**/{abbr}.json` 内嵌 `stories` |
| 视角切换 | 写 `scan.selectedStyle` → watch 触发重拉 | 组件内 `ref<StoryStyle>`，纯本地 |
| 「重新讲述」 | 有（fresh，绕缓存重打 AI） | 无 |

**关键事实：图鉴页 397 个星座完全不接 AI，只展示静态预设；识别页则相反，AI 失败才回落预设。**
NOTA 板上「重新讲述 / 生成分享卡」两个 chip 是纯装饰，点了没反应。

### 1.2 后端链路（链路 A）

```
POST /api/story/stream  (routers/story.py:266)
  ├─ _check_request()        style 白名单 → 400 INVALID_STYLE；abbr 跨 tradition 校验 → 404
  ├─ 缓存命中？               TTLCache(maxsize=96, ttl=600)，一次性 yield 全部事件
  ├─ _build_prompt()         SYSTEM_PROMPT + USER_TEMPLATE + myth_pool_rule(tradition)
  ├─ provider.chat_stream()  sync on_delta → asyncio.Queue → async generator 桥接
  ├─ 边界检测                 buffer 里出现 "\n\n" 就 flush；首段首行 = title
  ├─ 失败/无 title            get_preset() → 推 preset 段落 + done(degraded:true)
  └─ 成功                     _cache_put() + done 事件
```

- Provider 优先级：`AgentArts`（AK + BASE_URL + RUNTIME_NAME 全非空）→ `OpenAI 兼容` → `Disabled`
- 当前 `.env` 已配 AgentArts 四项，**线上走的是 AgentArts 真流式路径**
- 降级契约：AI 不可用 → `degraded:true` + preset，**不返 503**；`degraded` 不写缓存

### 1.3 数据现状（实测统计）

| tradition | 星座数 | 含 `stories` | myth / science | 空段落块 | abbr 冲突 |
|---|---|---|---|---|---|
| western | 88 | 88 | 88 / 88 | 0 | \ |
| chinese | 309 | 309 | 309 / 309 | 0 | 与 western 交集 = 0 |

即：**397 星座 × 2 视角的预设故事已 100% 铺满**，不存在"未撰写"占位。
星表字段 `bayer / name / magnitude` 在 3681 条记录中零缺失（但代码无防护，见 P2-13）。
单星座最大星数 70（`chinese/xuan_yuan.json`）。

### 1.4 测试现状

- `server/tests/test_story.py`：**22 用例全绿**（3.85s）
- `web/tests/story.stream.test.ts` + `StoryPanel.test.ts` + `story.store.test.ts`：mock fetch，覆盖三态与聚合
- **缺口**：下述 P0-1 / P0-2 / P0-3 / P0-5 全部无用例覆盖

---

## 2. 问题清单

### P0（影响线上观感或功能正确性）

#### P0-1 AgentArts 把 system prompt 整段丢弃，tradition 神话池规则从未生效

`ai_provider.py:296` — `chat_stream()` 调 `self._iter_message_deltas(user, timeout=timeout)`，
`_iter_message_deltas` 的请求体只有 `{"query": user}`（`ai_provider.py:243`）。
形参 `system` 收下后**从未使用**。

后果：
- `SYSTEM_PROMPT` 里的"3-4 段 220-300 字""不编造星名""不要 JSON/Markdown"全部没送进模型
- `myth_pool_rule(tradition)`（66fe6c6「神话池按 tradition 分流，剥离中西混说」的核心产物）
  **只存在于 system prompt**，于是中国星官的"用二十八宿/星官名、引张衡苏轼"规则彻底失效
- 风格控制只剩 `USER_TEMPLATE` 里的"视角：神话/科普"一行

#### P0-2 两套解析算法分叉，且非流式实现与 spec §646 不符

| | `/api/story`（非流式） | `/api/story/stream`（流式） |
|---|---|---|
| 标题 | `split("\n\n")[0]` **整块** | 第一块的第一行 |
| 前缀清洗 | 剥 `标题：` / `Title:` / `# ` | **不剥**（会带出「标题：xxx」） |
| 无 `\n\n` 时 | `title = body = 全文`（标题与正文重复） | 首行标题 + 余下正文 |

spec §646 明确写「期望 LLM **首行**为标题」——**非流式实现是偏离 spec 的那一方**。
实测同一份输出在两条接口会得到不同 title/paragraphs。
（缓解：非流式接口生产环境未调用，见 P2-15。）

#### P0-3 AI 中途失败 → 两个故事被拼接显示

后端：流已 yield 了 N 段后 `chat_stream` 抛错 → `story.py:376-400` 在**不通知前端**的情况下
继续 yield preset 的 title + paragraphs。
前端：`stores/story.ts:81` 是 `streamParagraphs.value.push(...)`，**从不清空**。

结果：用户看到「AI 生成的半截段落」+「完整离线预设段落」首尾相接的缝合怪，
且 `done` 里 `degraded:true` 只带来一个"离线故事"徽章。

#### P0-4 首屏流式期间面板一片空白；切星座时先显示上一个星座的故事

`StoryPanel.vue:19-31` 把 `streaming` 直接判为 `'ready'`，但模板 97 行的渲染条件是
`v-else-if="story.current"`。于是：
- 首次加载：`current` 为 null 且 `streaming=true` → 三个分支全落空 → **整段 SSE（最长 30s+）期间面板空白**，连骨架屏都没有
- 切换星座/视角：`streamParagraphs` 已清空但 `current` 仍是上一个故事的 → `displayParagraphs`
  回退到 `current.paragraphs`，**先显示旧故事，再被新流式内容顶掉**

#### P0-5 并发流无中止，段落交错

`fetchStoryStream` 没有 `AbortController`，`watch` 里异步调用不做竞态保护。
连点「神话/科普」tab 或快速换星座 → 两个 SSE 同时往同一个 `streamParagraphs` 数组 push，
段落按到达顺序交错，最终 `current` 由后到的 `done` 决定。

### P1（健壮性 / 成本 / 资源）

#### P1-6 OpenAI 兼容 provider 没有真流式
`OpenAICompatibleProvider` 未重写 `chat_stream`，基类实现是"聚合全文 → 一次 `on_delta`"。
一旦 AgentArts 配置失效回落 DeepSeek，SSE 立刻退化成"憋 30 秒一次性吐完"，打字机效果消失。

#### P1-7 没有端到端超时，可能挂死
- 前端 `streamStory` 无 `AbortSignal`、无超时、无 `reader.cancel()`（对比 `api/solve.ts` 有 65s 超时）
- 后端 `httpx.Timeout(30.0)` 是**每 chunk 读超时**，不是总时长；上游只要持续吐心跳，请求可以无限拖下去
- 组件卸载时连接不释放

#### P1-8 客户端断开后 AI 调用变孤儿
`story.py:369-373` 的 `finally` 只 `await chat_task`，**不 cancel**。
用户中途切页 / 关标签页，AgentArts 那次调用仍在跑完，白烧配额。

#### P1-9 无熔断：AI 故障时每次请求都要等满超时才降级
`degraded:true` 刻意不缓存（spec §5.4），但没有对应"短期熔断"。
AgentArts 挂掉期间，每个请求都要走完 30s 超时才回落预设 —— 用户看到的是 30 秒空白（叠加 P0-4）。

#### P1-10 无鉴权无限流
`/api/story` 公网裸奔，任何人可无限次触发 AgentArts 调用。大赛演示环境一旦被扫，配额/费用直接见底。

#### P1-11 缓存命中返回的 `latency_ms` 是首次生成耗时
`story.py:193` 直接 `{**cached, "cached": True}`，`latency_ms` 沿用原始值（可能十几秒）。
监控/埋点口径失真。

### P2（设计债 / 死代码 / 文档漂移）

#### P2-12 请求不带 `tradition`，靠 abbr 跨 tradition「首命中」反查
`_find_constellation()` 遍历 `list_traditions()`（目录名排序，chinese 先于 western）返回首个命中。
**当前 abbr 零冲突所以没炸**，但这是隐式契约：一旦两个体系出现同名 abbr，
故事、神话池、缓存 key（只有 `(abbr, style)` 二维）会同时错位。

#### P2-13 Prompt 与数据访问无防护
- `_build_prompt` 把**全部**星点塞进 `primary_stars`（最多 70 颗，`chinese/xuan_yuan`），token 明显膨胀
- `s['bayer'] / s['name'] / s['magnitude']` 直接下标访问，缺任意一个键就是 `KeyError` → 500
  （当前 3681 条数据零缺失，纯靠数据洁癖兜着）

#### P2-14 输出无校验/清洗
模型若返回 Markdown（`**加粗**`、`- 列表`）会原样渲染；不校验 220-300 字；不校验段落数。

#### P2-15 死代码与冗余
- `POST /api/story`（非流式）与 `stores/story.ts` 的 `fetchStory` / `api/story.ts` 的 `postStory`：
  **生产链路零调用**，只有测试在用 —— 即 P0-2 里那份偏离 spec 的解析代码是纯维护负担
- `story.py:14` 顶层 `import json` 与 `_sse()` 内 `import json as _json` 重复
- `AGENTARTS_AGENT_ID` 收进 config、传进构造、存成 `self._agent_id`，**请求里从不发送**
- `story_fallback.clear_cache()` 会清空 `services.traditions._DATA` 全局缓存，生产误调即全量重载

#### P2-16 UI 双实现，交互能力不对等
`StoryPanel` 与 `AtlasStoryStatic` 各写一套 vtabs，样式规则不同（一个用 `::after ✦` + 背景切换，
一个用 `::before` 金条），一个有重讲按钮一个没有；`AtlasStoryStatic` 在视角缺失时
**静默回退到第一个视角**（`?? Object.values(stories)[0]`），掩盖数据缺口。

#### P2-17 文档漂移
- `CLAUDE.md:55` 写 `views/ScanView / ConstellationView / StoryView` —— **StoryView 不存在**
- `config.py:41` 注释仍写「降级到 `preset_stories.json`」—— 该文件已删
- spec / plan 多处仍写「5 星座 × 2 风格静态预设」，实际已 397 × 2 全量铺满
- `CLAUDE.md:50/97` 的测试数量（后端 26 / 前端 72）与当前实际不符

---

## 3. 建议的修复优先级（供后续决策，本次未实施）

1. **P0-1** 把 system prompt 并入 AgentArts 请求体（或下沉到智能体侧人设），否则 tradition 分流是空转
2. **P0-2** 抽出单一 `parse_story_text(text, fallback_title)` 供两条接口共用；删掉非流式接口或让它转调流式
3. **P0-3 + P0-5 + P0-4** 前端加 requestId/AbortController；降级事件显式 `reset`；`streaming` 且无内容时渲染骨架屏
4. **P1-7/8/9/10** 加总时长超时 + 断连 cancel + 失败熔断 + 简单限流
5. **P2** 收口两套 UI 为同一组件（图鉴页可选接 AI），清理死代码与文档

---

## 4. 附：本次调研执行的只读校验

- `pytest tests/test_story.py -q` → 22 passed
- 统计脚本遍历 `server/data/traditions/{western,chinese}/*.json` 得到 1.3 节数据表
- pydantic 2.13.4 下验证 `cacheBust: 1` → `True`（FE 传 number 可用，非 bug，但类型声明与后端 `bool` 不一致）
