# 星语天象 StarWhisper — AgentArts 智能体接入设计规格

> 版本：v0.3 | 日期：2026-08-24 | 阶段：M2 收尾 / M2.5 前置
> 关联：`docs/specs/2026-08-23-starwhisper-design-m2.md`（M2 spec §5 AI Provider 抽象层，本文件为其增量）
> 上游：AgentArts「智能体运行时」API `POST /runtimes/{runtime_name}/invocations`（v0.3 起采用真实 API Key 认证）

---

## 0. 背景与目标

### 0.1 一句话目标

把 AI 星座故事的生成通道从「直连 OpenAI 兼容大模型」切换为「调用华为云 AgentArts 平台上的『星座叙事官』智能体」，输出契约、解析逻辑、降级链路与前端响应体**全部保持 M2 现有契约不变**；AgentArts 不可用时自动回退 OpenAI 兼容直连，再回退 preset 兜底。

### 0.2 v0.3 变更声明（相对 v0.2）

| 变更项 | v0.2 假设 | v0.3 真实接口 |
|---|---|---|
| 鉴权方式 | 工作负载身份 AK/SK 签名（HMAC） | **API Key Bearer**：`Authorization: Bearer <API Key>`（智能体身份认证服务工作负载身份 API Key） |
| 调用 Host | `defaultgw-...huaweicloud-agentarts.com` | `711fce29f10c45d59ad4cf79bb8994b0.studio.agentarts.cn-southwest-2.huaweiapaas.com` |
| 运行时名称 | `bd0524687f54ea686f5e060bd2862cf` | `agent-arts-28042cb9e41440408f7164ad77237581` |
| 请求 Body | 顶层 `query` 优先优先 | **官方样例 `{"inputs":{"query":...}, "plugin_configs":[...]}` 优先**；400/422 回退顶层 `query` |
| 会话 ID | 32 位小写 hex | 不变（uuid4().hex） |
| 响应结构 | `event/content/createdTime/latency`（content 未锁定） | **锁定两形态**：官方 `{event, data:{text,...}}`（`data.text`）+ 简版 `{event, content}`；终止 `event=="end"` 或 `data.node_type=="End"` |
| 密钥管理 | `.env` 存 AK/SK | `.env` 存 **`AGENTARTS_API_KEY`**（API Key），`AGENTARTS_AK/SK` 移除 |

### 0.3 真实调用路径（平台已签发，2026-08-24 有效）

```
POST https://711fce29f10c45d59ad4cf79bb8990b0.studio.agentarts.cn-southwest-2.huaweiapaas.com
     /runtimes/agent-arts-28042cb9e41440408f7164ad77237581/invocations
Authorization: Bearer <AGENTARTS_API_KEY>
x-hw-agentarts-session-id: <1~32 位小写/数字/中划线>
Content-Type: application/json

{ "inputs": { "query": "<用户问题文本>" }, "plugin_configs": [] }
```

> 对话有效期 7 天，超期需重新生成调用路径 —— 部署时须**可配置**，避免硬编码。

### 0.4 入本 spec

| 模块 | 内容 |
|---|---|
| AgentArts Provider | `AgentArtsProvider(AIProvider)` 实现（API Key Bearer + 流式聚合） |
| 调用路径配置 | 完整 invoke URL / host 走环境变量或 `.env`，不硬编码 |
| `.env` 管理 | 根目录 `.env`（已 .gitignore）存 `AGENTARTS_API_KEY/RUNTIME_NAME/AGENT_ID/BASE_URL`；`.env.example` 模板入库 |
| 流式输出 | 后端经 httpx 流式读取上游事件 → 聚合全文本 → **SSE 转发前端（打字机）** |
| 前端打字机 | 新增 `POST /api/story/stream`（SSE）；`POST /api/story` 非流式契约保持不变 |
| 工厂优先级 | `make_provider()`：AgentArts 已配置 → 优先；否则 OpenAI 兼容；否则 Disabled |
| 降级 | AgentArts 任何失败 → 下一级 provider / preset，不返 503 |
| 测试 | Provider 单测（MockTransport 流式桩）+ story/stream 集成 + health 三态 |

### 0.5 不入本 spec

- 观星指数、i18n、分享卡（仍归 M3 / M4）。
- AgentArts 平台上的**工作流**方案（本 spec 只接智能体；工作流差异点见 §7 备选说明）。
- 盘古 IAM 签名适配；本 spec 仅 **API Key Bearer**。
- 前端的 OpenAI 直连（`?mock=1` fixture 保留，属 M1 演示链路，不受影响）。

---

## 1. 设计决策汇总

| 决策项 | 结论 |
|---|---|
| 接入形态 | AgentArts **智能体**（对话型）。系统提示词在平台侧配置；后端把 `user prompt` 作为 `query` 传入 |
| 会话模型 | 每次调用生成新 `x-hw-agentarts-session-id` = 小写 hex(uuid4 的 hex 表示，32 位小写+数字，合法）；无状态并发安全 |
| 运行模式 | API 无 `X-Invoke-Mode` 要求则不发；响应已确认流式 |
| Body 格式 | **顶层 `{ "query": "<full user prompt>" }`**（以平台 curl 样例为准） |
| 鉴权 | **API Key Bearer**：`Authorization: Bearer <AGENTARTS_API_KEY>`（v0.3 起采用智能体身份认证服务工作负载身份 API Key） |
| 响应解析 | 流式事件逐条聚合：官方结构 `{event, data:{text,...}}`，优先取 `data.text`（字符串）；终止于 `event=="end"` 或 `data.node_type=="End"` |
| 输出契约 | **不因换上游而改**：首行标题 + `\n\n` 分段，220–300 字；解析继续复用 `_parse_title_paragraphs` |
| 前端展示 | 打字机逐段渲染：SSE 转发事件 `title → paragraph(i)`；缓存命中/降级时一次性返回（无流） |
| health 语义 | `up` = AgentArts 配置齐全（API_KEY + runtime_name + base_url 三要素非空）；不发起真实调用 |
| 失败降级 | AgentArts 异常（鉴权失败/超时/解析/5xx）→ story 捕获 → 下一 provider 或 preset → `degraded:true` |
| 超时 | invoke 请求 30s（沿用 M2 §5；上游为长任务流式时可按事件间隔续命） |

---

## 2. AgentArts 上游协议（真实，实现依据）

### 2.1 调用端点

```text
POST {AGENTARTS_BASE_URL}/runtimes/{AGENTARTS_RUNTIME_NAME}/invocations
```

- Host：`711fce29f10c45d59ad4cf79bb8994b0.studio.agentarts.cn-southwest-2.huaweiapaas.com`（区域 endpoint，随部署变化，必须走配置）
- `AGENTARTS_RUNTIME_NAME`：`agent-arts-28042cb9e41440408f7164ad77237581`

### 2.2 请求 Header

| Header | 必选 | 取值 |
|---|---|---|
| `Authorization` | 是 | `Bearer <AGENTARTS_API_KEY>`（API Key，见 §4.3） |
| `Content-Type` | 是 | `application/json` |
| `x-hw-agentarts-session-id` | 是 | 32 位小写 hex（uuid4().hex），1~32 位小写字母/数字/中划线合法 |
| `X-Request-Id` | 否 | uuid4，链路追踪 |

### 2.3 请求 Body

**优先官方结构** `{"inputs": {"query": ...}, "plugin_configs": [...]}`；若平台返 400/422，回退控制台 curl 的顶层 `{"query": ...}` 形态（实测 v0.3 默认接受官方结构）。

```json
{ "inputs": { "query": "<推理出的 user prompt 全文>" }, "plugin_configs": [] }
```

### 2.4 响应（流式数据单元）

上游**流式**返回，每行一个 JSON 对象，官方结构：

| 字段 | 类型 | 描述 |
|---|---|---|
| `event` | string | 数据单元类型；终止事件为 `end` |
| `data` | Object | 消息块内容；`data.text` 为字符串或 `null`；`data.node_type == "End"` 也是终止信号 |
| `createdTime` | long | 消息块时间戳（ms），可追踪延迟 |
| `latency` | Object | 耗时：`plugin` / `model` / `overall` |

### 2.5 解析策略（官方结构已锁定，兼容策略作为兜底）

1. httpx 以**流式**读取：`client.build_request()` + `client.send(req, stream=True)`，按行解析；`r.aclose()` 在 `finally` 中释放连接；
2. 逐事件聚合：`_extract_text(event)` 优先取 `data.text`（字符串非空才收）；兼容历史 `content.text/message/content` 字符串字段；
3. 终止条件：`event == "end"` 或 `data.node_type == "End"`；EOF 兜底；
4. 聚合完整文本后，story 路由继续走 `_parse_title_paragraphs` 拆分标题/段落。

> `_extract_text` 的兼容实现保证了上游结构微调时无需改业务代码；P0 联调项已落地（v0.3 真实响应已锁定 `data.text`）。

---

## 3. 平台侧智能体配置（已完成建号，2026-08-24）

| 项 | 值 |
|---|---|
| 智能体名称 | starwhisper-storyteller（星语天象·星座叙事官） |
| AgentArts Agent ID | `c9ebe998-aa7a-4a9b-93ce-352c67be1e8f` |
| 运行时名称 | `agent-arts-28042cb9e41440408f7164ad77237581` |
| 调用域名 | `711fce29f10c45d59ad4cf79bb8994b0.studio.agentarts.cn-southwest-2.huaweiapaas.com` |
| 形态 | 对话型智能体（单智能体），`query` 入参 |
| 模型 | 平台侧选中文对话模型（DeepSeek 系 / 盘古 N2 系均可） |
| 有效期 | 对话有效 7 天；调用路径/凭证需支持运行时刷新（配置化） |

平台侧 System Prompt 已在 v0.1 §3.2 给出，创建时可直接粘贴（标题首行、`\n\n` 分段、220-300 字、禁 JSON/Markdown、不编造星名/坐标、文末无客套）。

---

## 4. 后端改动设计

### 4.1 `.env` 与 `config.py` 新增配置

**`.env.example`（入库模板，根目录）**：

```dotenv
# ---- AgentArts 智能体运行时（v0.3 API Key 鉴权）----
# API Key 由华为云「智能体身份认证服务·工作负载身份」签发；仅存服务端 .env，不入 git
AGENTARTS_API_KEY=
# 智能体标识（追踪/调试用，可不填）
AGENTARTS_AGENT_ID=
# 运行时名称（agent-arts- 开头）
AGENTARTS_RUNTIME_NAME=
# AgentArts 区域 endpoint（不含 /runtimes 前缀）
AGENTARTS_BASE_URL=https://711fce29f10c45d59ad4cf79bb8994b0.studio.agentarts.cn-southwest-2.huaweiapaas.com
# 留空 = 未启用 AgentArts（回退 OpenAI 直连 / preset）
```

**`config.py` 新增**（沿用现有 `os.getenv` 风格；`.env` 加载由启动命令 `set -a; source .env` 或 python-dotenv 完成——**本项目不新增依赖**，由部署脚本导出）：

```python
AGENTARTS_API_KEY = os.getenv("AGENTARTS_API_KEY", "")
AGENTARTS_AGENT_ID = os.getenv("AGENTARTS_AGENT_ID", "")
AGENTARTS_RUNTIME_NAME = os.getenv("AGENTARTS_RUNTIME_NAME", "")
AGENTARTS_BASE_URL = os.getenv("AGENTARTS_BASE_URL", "")
```

启用判定：`bool(AGENTARTS_API_KEY and AGENTARTS_BASE_URL and AGENTARTS_RUNTIME_NAME)`（`AGENT_ID` 仅用于追踪日志，不参与启用判定）。

### 4.2 `services/ai_provider.py` 新增 `AgentArtsProvider`

```python
class AgentArtsProvider(AIProvider):
    """AgentArts 智能体运行时接入（spec §2）。

    - API Key Bearer 鉴权（智能体身份认证服务工作负载身份 API Key，见 §4.3）
    - 流式读取上游事件并聚合为完整文本
    - 复用模块级 httpx.AsyncClient 单例；aclose() 由 main.py 释放
    """

    name = "agentarts"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        runtime_name: str,
        agent_id: str = "",
        name: str = "agentarts",
    ) -> None: ...

    @staticmethod
    def _extract_text(event: dict) -> str:
        """从消息块事件提取文本增量。

        官方结构：data.text（字符串或 null）优先；兼容历史 content.text/message/content。
        无法识别时返回空串（该事件不贡献文本）。
        """

    @staticmethod
    def _parse_event(line: str) -> dict | None:
        """解析单行流式事件 → 事件 dict；心跳/[DONE] 返回 None。"""

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """调用 /runtimes/{runtime_name}/invocations。

        - system 参数忽略（平台侧已配置 system prompt）
        - 优先用官方 inputs.query 结构；400/422 时回退控制台 curl 的顶层 query
        - 新会话：每次 uuid4().hex 作为 session id
        - 流式聚合所有消息块文本后返回
        - client.send(req, stream=True) + finally aclose() 避免连接泄漏
        """
        ...

    async def health(self) -> bool:
        """配置齐全即视为 up（API_KEY/base_url/runtime_name 三要素非空）。"""
        ...
```

### 4.3 API Key Bearer 鉴权（v0.3）

v0.3 起，智能体运行时 API 不再做 HMAC 签名，改用平台签发的 **API Key Bearer** 鉴权：

```
Authorization: Bearer <AGENTARTS_API_KEY>
```

API Key 由华为云「智能体身份认证服务·工作负载身份」签发；通过 `.env` 的 `AGENTARTS_API_KEY` 注入，仅存服务端，不入 git。`AGENTARTS_AK/SK` 已废弃。

### 4.4 `make_provider()` 工厂优先级

```python
def make_provider() -> AIProvider:
    # 1) AgentArts 已配置（API_KEY + BASE_URL + RUNTIME_NAME 三要素非空） → 优先
    if AGENTARTS_API_KEY and AGENTARTS_BASE_URL and AGENTARTS_RUNTIME_NAME:
        return AgentArtsProvider(
            api_key=AGENTARTS_API_KEY,
            base_url=AGENTARTS_BASE_URL,
            runtime_name=AGENTARTS_RUNTIME_NAME,
            agent_id=AGENTARTS_AGENT_ID,
        )
    # 2) 其次 OpenAI 兼容直连
    if AI_API_KEY:
        return OpenAICompatibleProvider(...)
    # 3) 兜底 preset
    return DisabledProvider()
```

### 4.5 health 语义（`routers/health.py`）

- `AgentArtsProvider.health()` 返回配置就绪（§4.2 四要素非空）。
- `ai_model` 字段在 AgentArts 场景回显 `agentarts` 或运行时名。
- `ai_provider` 三态保持 `up | disabled | down` 不变。

### 4.6 流式响应与前端打字机

**设计（v0.3 决策）**：`POST /api/story` 保持非流式契约（缓存/降级/兼容测试不动），**新增** `POST /api/story/stream` 提供 SSE 打字机流：

| 场景 | 行为 |
|---|---|
| AgentArts 成功 | `text/event-stream`：先发 `event:title`（标题），再逐段 `event:paragraph`，最后 `event:done`（含完整 payload 元数据） |
| 命中缓存 | 直接 `event:title` + 各 `event:paragraph`（瞬间发完，前端无打字等待）；末尾 `event:done` 带 `cached:true` |
| 降级 preset | 同上一次性发完；`event:done` 带 `degraded:true` |
| 上游失败 | `event:error`（含 message），前端转 degraded 态 |

**前端动作面**：
- `api/story.ts` 新增 `streamStory(req, onEvent)`：`fetch` + `ReadableStream` 解析 SSE；
- `stores/story.ts` 新增 `streaming` 状态与 `title/paragraphs` 累积；
- `StoryPanel.vue` 打字机逐段渲染（每收到 `paragraph` 事件插入段落，标题即刻显示）；
- `types.ts` 新增 `StoryStreamEvent` 联合类型；
- 前端测试补 stream 分支（mock `fetch` 返回 `ReadableStream`）。

**测试策略（前端）**：
- store：流式累积 title/段落、done 落库、error 转 degraded；
- 组件：打字机渲染与既有三态不回归。

### 4.7 明确不改的部分

- `routers/story.py` 非流式路径：请求/响应 body 契约、缓存、Cache-Bust、404/400——全部不变。
- 输出解析 `_parse_title_paragraphs`——零改动（AgentArts 文本按同一契约产出）。
- 前端既有 `StoryResponse` 类型与 `StoryPanel` 静态渲染路径保留（降级/缓存一次性渲染复用）。

---

## 5. 测试策略

### 5.1 后端（新增 `server/tests/test_agentarts.py`，沿用绝对路径导入 + monkeypatch.setattr 风格）

| 用例 | 方法 | 断言 |
|---|---|---|
| 请求头/鉴权存在 | `httpx.MockTransport` 捕获请求断言 `Authorization: Bearer <key>` 非空、`x-hw-agentarts-session-id` 长度 ≤32 且小写 | header 齐备 |
| 流式多事件聚合 | MockTransport 返回多行 JSON 事件（含终态） | `chat()` 返回拼接文本 |
| content 结构兼容 | `_extract_text` 对 `{text}` / `{message}` / 字符串 content | 可提取 |
| 鉴权失败降级 | MockTransport 返回 401 | story 走 preset `degraded:true` |
| 超时降级 | MockTransport 抛 `TimeoutException` | `degraded_reason=AI_PROVIDER_TIMEOUT` |
| 空文本解析失败 | 流终态无文本 | 抛 `AI_PROVIDER_PARSE_ERROR` → preset |
| 工厂优先级 | monkeypatch `config.AGENTARTS_*` | `make_provider()` 返回 `AgentArtsProvider` |
| 工厂回退 | `AGENTARTS_*` 空 + `AI_API_KEY` 有 | 返回 `OpenAICompatibleProvider` |
| health 配置态 | 配置齐全 / 缺 RUNTIME_NAME | `up` / `down` |
| `/api/story/stream` SSE | TestClient + mock provider | 流式 `event:title/paragraph/done` 序列正确 |
| 既有 story 非流式回归 | 既有 9 用例 | 不回归 |

### 5.2 前端（`web/tests/` 增量）

| 用例 | 方法 | 断言 |
|---|---|---|
| `streamStory` 解析 SSE | mock fetch ReadableStream | 回调按事件顺序触发 |
| store 流式累积 | mock api | title/段落累积正确、done 落库 |
| StoryPanel 打字机 | mock fetch + mount | 逐段插入渲染、标题即时显示 |
| 既有三态回归 | 既有 StoryPanel/story.store 用例 | 不回归 |

---

## 6. 交付清单

- [ ] `.env.example`（根目录模板，入库）+ `.env`（本地，gitignore 生效）
- [ ] `config.py`：新增 4 个 `AGENTARTS_*` 环境变量（`AGENTARTS_AK/SK` 已废弃，删除）
- [ ] `services/ai_provider.py`：`AgentArtsProvider`（API Key Bearer 鉴权 + 流式聚合 + `_extract_text`）+ `_CLIENT` 单例复用
- [ ] `services/ai_provider.py`：`make_provider()` 三优先级工厂
- [ ] `routers/story.py`：新增 `POST /api/story/stream` SSE 端点（复用 prompt 构造与解析）
- [ ] `routers/health.py`：AgentArts 配置态映射
- [ ] `server/tests/test_agentarts.py`：§5.1 全部用例；既有 48 用例回归
- [ ] 前端：`api/story.ts` `streamStory` + `types.ts` `StoryStreamEvent`
- [ ] 前端：`stores/story.ts` 流式累积 + `StoryPanel.vue` 打字机
- [ ] 前端测试：§5.2 用例；既有 ~37 用例回归
- [ ] **P0 联调**：拿真实流式响应样例锁定 `event`/`content` 结构，补回归测试
- [ ] 本地端到端：`.env` 配置后 `POST /api/story/stream` 实链验证打字机

---

## 7. 备选方案与后续

- **工作流方案**：若平台侧希望入参结构化（`abbr / style / primary_stars`），可改为工作流开始节点字段；本 spec 不实施，仅预留。
- **健康探测真实化**：如产品要求 health 反映真实可用性，可将 `health()` 升级为发一次最小 invoke（query 固定短文本），命中 200 即 up；成本可控时启用。
- **SSE 与现有 `/api/story` 合并**：若产品确定走流式为主，可将流式并入 `/api/story`（按 `Accept: text/event-stream` 分流），前端与缓存策略再统一；v0.3 暂以双端点隔离，风险最小。

---

## 附录 A（v0.3 真实调用记录）

> 2026-08-24 联调落地：
> 1. 真实调用 host：`711fce29f10c45d59ad4cf79bb8994b0.studio.agentarts.cn-southwest-2.huaweiapaas.com`
> 2. 真实运行时：`agent-arts-28042cb9e41440408f7164ad77237581`
> 3. 鉴权：API Key Bearer（不再用 HMAC）
> 4. 响应结构：`{event, data:{text, node_type}, createdTime, latency}`；`data.text` 为字符串，`event=="end"` 或 `data.node_type=="End"` 终止
> 5. 流式调用：`client.send(req, stream=True)` + `r.aclose()` 在 `finally` 中释放连接