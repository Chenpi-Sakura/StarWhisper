"""AI Provider 抽象层（spec §5 + §16.4 + AgentArts 增量全部落地）。

- AIProvider：抽象基类，定义 chat / health。
- OpenAICompatibleProvider：DeepSeek / 字节 / OpenAI 统一走 OpenAI Chat Completions
  协议。httpx AsyncClient 采用模块级单例 + aclose() 释放连接池。
- AgentArtsProvider：华为云 AgentArts 智能体运行时接入（API Key Bearer 认证 +
  流式事件聚合；body 优先官方 `inputs.query`，400/422 时回退顶层 `query`）。
  **平台只有 `query` 一个入参、没有 system 角色位**，故 system prompt 需拼进
  query 才会生效（见 `AGENTARTS_SYSTEM_IN_QUERY`）。
- DisabledProvider：未配置 AI_API_KEY 时启用；chat() 抛 RuntimeError 触发 fallback。
  health() 始终返回 False；**不抛 503**（spec §16.4 修订）。
- make_provider：优先 AgentArts（API_KEY + BASE_URL + RUNTIME_NAME 三要素非空）→
  OpenAI 兼容 → Disabled。
- max_tokens=1000（spec §16.4，由原 600 调整），timeout 默认 30s。
"""
from __future__ import annotations

import json
import ssl
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable

import httpx
import truststore

from config import (
    AI_API_BASE,
    AI_API_KEY,
    AI_MODEL,
    AGENTARTS_API_KEY,
    AGENTARTS_BASE_URL,
    AGENTARTS_RUNTIME_NAME,
    AGENTARTS_SYSTEM_IN_QUERY,
)


class AIProvider(ABC):
    """AI 服务提供方抽象基类。"""

    name: str

    @abstractmethod
    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """发送对话请求，返回模型生成的纯文本。"""

    async def chat_stream(
        self,
        system: str,
        user: str,
        on_delta: Callable[[str], None],
        *,
        timeout: float = 30.0,
    ) -> str:
        """流式发送对话请求；每收到一段增量文本调一次 on_delta(text)。

        默认实现走 chat() 聚合 + 一次性回调（不是真流式，但接口兼容）。
        支持真流式的 provider（AgentArts）需重写本方法。返回值为聚合后全文。
        """
        text = await self.chat(system, user, timeout=timeout)
        on_delta(text)
        return text

    @abstractmethod
    async def health(self) -> bool:
        """探测 provider 可用性；返回 True/False。"""


class OpenAICompatibleProvider(AIProvider):
    """DeepSeek / 字节 / OpenAI 统一走 OpenAI Chat Completions。

    客户端为模块级单例，避免每实例重复创建连接池；aclose() 在进程关闭时
    统一释放底层 httpx 连接池（spec §5.1）。
    """

    _CLIENT: httpx.AsyncClient | None = None

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        name: str = "openai-compatible",
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        if OpenAICompatibleProvider._CLIENT is None:
            OpenAICompatibleProvider._CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
            )
        self._client = OpenAICompatibleProvider._CLIENT

    @classmethod
    async def aclose(cls) -> None:
        """应用关闭时统一释放底层 httpx 连接池。"""
        if cls._CLIENT is not None:
            await cls._CLIENT.aclose()
            cls._CLIENT = None

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """调用 /chat/completions，返回首个 choice 的 content。"""
        r = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": 1000,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    async def _iter_stream_deltas(
        self,
        system: str,
        user: str,
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[str]:
        """P1-6：/chat/completions stream=True 的 SSE 增量解析。

        逐行解析 `data: {...}`，取 choices[0].delta.content yield；
        `data: [DONE]` 终止。非流式降级：服务端不支持 stream 时会整体
        一次返回，delta 退化为单段——调用方无感。
        """
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": 1000,
                "stream": True,
            },
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
                    continue
                try:
                    obj = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if content:
                    yield content

    async def chat_stream(
        self,
        system: str,
        user: str,
        on_delta: Callable[[str], None],
        *,
        timeout: float = 30.0,
    ) -> str:
        """真流式：逐 SSE chunk 调 on_delta（覆盖基类的聚合假流式）。"""
        all_text: list[str] = []
        async for delta in self._iter_stream_deltas(system, user, timeout=timeout):
            all_text.append(delta)
            on_delta(delta)
        return "".join(all_text)

    async def health(self) -> bool:
        """GET /models 探测可用性，5s 超时，状态 200 视为 up。"""
        try:
            r = await self._client.get(
                f"{self._base_url}/models",
                timeout=5.0,
            )
            return r.status_code == 200
        except Exception:
            return False


class DisabledProvider(AIProvider):
    """未配置 AI_API_KEY 时启用：强制走 fallback preset。

    chat() 抛 RuntimeError("AI_PROVIDER_DISABLED")，路由层捕获后查 preset
    返回 `degraded:true`；**不返 503**（spec §16.4 修订）。
    """

    name = "disabled"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        raise RuntimeError("AI_PROVIDER_DISABLED")

    async def health(self) -> bool:
        return False


class AgentArtsProvider(AIProvider):
    """华为云 AgentArts 智能体运行时接入。

    - 认证：API Key Bearer（智能体身份认证服务工作负载身份 API Key）。
    - Body：官方形态 `{"inputs": {"query": "..."}}`；400/422 时回退顶层
      `{"query": "..."}`（兼容旧运行时）。
    - 会话 ID：每次调用 uuid4().hex（32 位小写/数字，符合 1~32 位约束）。
    - 流式响应：聚合 `event=="message"` 的 content；终止于 `event=="done"`。
    - SSL：使用独立 client（不复用 OpenAI 单例，预留差异化配置空间）。
    """

    name = "agentarts"

    # AgentArts 独立 client 池（不复用 OpenAI 单例，因 SSL 配置不同）
    _CLIENT: httpx.AsyncClient | None = None

    def __init__(
        self,
        api_key: str,
        base_url: str,
        runtime_name: str,
        name: str = "agentarts",
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._runtime_name = runtime_name
        if AgentArtsProvider._CLIENT is None:
            # truststore 让 Python 走系统 trust store（Windows cert store），
            # 等价于 curl 用 Schannel；避免依赖 certifi 自带 CA bundle（会缺
            # 平台的中间证书）。
            AgentArtsProvider._CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            )
        self._client = AgentArtsProvider._CLIENT

    @classmethod
    async def aclose(cls) -> None:
        """应用关闭时释放 AgentArts 独立 client 池。"""
        if cls._CLIENT is not None:
            await cls._CLIENT.aclose()
            cls._CLIENT = None

    # ---- 消息块文本提取 ----

    @staticmethod
    def _extract_text(event: dict) -> str:
        """从消息块事件提取文本增量。

        平台真实结构：`event.content` 为字符串（start/summary_response/done 等事件 content
        为非字符串，跳过）。仅当 event 是 message 类事件时提取。
        """
        content = event.get("content")
        if isinstance(content, str) and content:
            return content
        return ""

    # ---- 流式事件解析 ----

    @staticmethod
    def _parse_event(line: str) -> dict | None:
        """解析单行流式事件 → 事件 dict；无法解析或为心跳返回 None。

        支持 `data: {json}` 前缀；返回整个事件对象（含 event/data/content）。
        """
        data_part = line
        if line.startswith("data:"):
            data_part = line[len("data:"):].strip()
        if not data_part or data_part in {"[DONE]", "ping"}:
            return None
        try:
            obj = json.loads(data_part)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    # ---- 主流程 ----

    async def _iter_message_deltas(
        self,
        system: str,
        user: str,
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[str]:
        """发送一次请求，逐 message event yield content 增量。

        async def + yield 是 async generator（Python 包装）；调用方用
        `async for delta in provider._iter_message_deltas(...)` 迭代。

        P0-1 修复：平台只有 `inputs.query` 一个入参、没有 system 角色位。
        `AGENTARTS_SYSTEM_IN_QUERY=1`（默认）时把 system prompt 拼进 query，
        否则 myth_pool_rule 等按 tradition 分流的约束不会生效。
        """
        url = f"{self._base_url}/runtimes/{self._runtime_name}/invocations"
        session_id = uuid.uuid4().hex
        if AGENTARTS_SYSTEM_IN_QUERY and system:
            query = f"[系统设定]\n{system}\n\n[用户请求]\n{user}"
        else:
            query = user
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "x-hw-agentarts-session-id": session_id,
        }

        # 官方 body 形态优先；400/422 回退顶层 query（兼容旧运行时）。
        bodies = [
            json.dumps({"inputs": {"query": query}}).encode("utf-8"),
            json.dumps({"query": query}).encode("utf-8"),
        ]
        r: httpx.Response | None = None
        for i, body_bytes in enumerate(bodies):
            req = self._client.build_request(
                "POST", url, headers=headers, content=body_bytes, timeout=timeout
            )
            r = await self._client.send(req, stream=True)
            if r.status_code in (400, 422) and i < len(bodies) - 1:
                await r.aclose()
                continue
            break
        assert r is not None
        try:
            r.raise_for_status()
            async for line in r.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                event = self._parse_event(line)
                if event is None:
                    continue
                if event.get("event") == "done":
                    break
                if event.get("event") == "message":
                    text = self._extract_text(event)
                    if text:
                        yield text
        finally:
            await r.aclose()

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """调 chat_stream + 聚合 on_delta，返回完整文本。"""

        all_text: list[str] = []

        def _collect(text: str) -> None:
            all_text.append(text)

        await self.chat_stream(system, user, _collect, timeout=timeout)
        return "".join(all_text)

    async def chat_stream(
        self,
        system: str,
        user: str,
        on_delta: Callable[[str], None],
        *,
        timeout: float = 30.0,
    ) -> str:
        """真流式：每次平台推一个 message event 就同步调 on_delta(text)。

        on_delta 是同步回调——它是 chat_stream 推文本的唯一出口。
        调用方负责将 delta 传给下游（router 用 queue 桥接）。
        """
        all_text: list[str] = []
        async for delta in self._iter_message_deltas(system, user, timeout=timeout):
            all_text.append(delta)
            on_delta(delta)
        return "".join(all_text)

    async def health(self) -> bool:
        """配置齐全即视为 up（API_KEY/base_url/runtime_name 三要素非空）。"""
        return bool(self._api_key and self._base_url and self._runtime_name)


def make_provider() -> AIProvider:
    """工厂：AgentArts（API_KEY+BASE_URL+RUNTIME_NAME 非空）→ OpenAI 兼容 → Disabled。"""
    if AGENTARTS_API_KEY and AGENTARTS_BASE_URL and AGENTARTS_RUNTIME_NAME:
        return AgentArtsProvider(
            api_key=AGENTARTS_API_KEY,
            base_url=AGENTARTS_BASE_URL,
            runtime_name=AGENTARTS_RUNTIME_NAME,
        )
    if AI_API_KEY:
        return OpenAICompatibleProvider(
            base_url=AI_API_BASE,
            api_key=AI_API_KEY,
            model=AI_MODEL,
        )
    return DisabledProvider()


SYSTEM_PROMPT = """你是「星语天象（StarWhisper）」的星座叙事官。任务：用 {style_zh} 视角讲述 {constellation_zh}（{latin}），3-4 段共 220-300 字。

要求：
- 神话视角（庄严古雅）：{myth_pool_rule}
- 科普视角（词条简说）：词条释义式、严谨、客观，不使用情绪化描写，类似百科条目开头；解释天文结构、观测季节、深空摄影要点

段落分明，每段 60-90 字，不堆砌术语。
文末不加「希望你喜欢」「祝观星愉快」之类废话。
不编造星名 / 坐标；如不确定请用「传说中」等限定词。
输出仅含标题 + 段落正文，不要 JSON / Markdown 标记。
"""


USER_TEMPLATE = """星座：{constellation_zh} ({latin})
视角：{style_zh}
主星列表：
{primary_stars}
"""


# ---- atlas-nota (图鉴“导读”段) 专用 prompt ----
# 区别于 atlas-story（myth/science 二档 / 220-300 字 / 多段），atlas-nota 单档
# “星图导读”，输出 100-200 字中文一段，不含 Markdown / 列表 / JSON。仅这段进
# atlas-nota 路由的 user prompt，由 ATLAS_NOTA_USER_TEMPLATE 模板填空。
ATLAS_NOTA_SYSTEM_PROMPT = """你是「星语天象（StarWhisper）」的星座导读官。用一段 100-200 字中文短文介绍 {constellation_zh}（{latin}）。
包含：神话起源或文化背景、最显著的观测特征（最亮星/形状）、观测时间提示。
风格：通俗、雅致、有画面感，不要 Markdown、不要列表、不要 JSON。
注意：开头不要重复星座名称（如「仙女座」「猎户座」），直接进入正文描述。"""

ATLAS_NOTA_USER_TEMPLATE = "请介绍星座：{constellation_zh}（{latin}），传统={tradition}，季节={season}，最亮星 {brightest_name}（{brightest_mag}ᵐ）。"


STYLE_ZH = {"myth": "神话", "science": "科普"}

# 神话池：按 tradition 限定来源（避免双体系并陈）。
# 仅给正向引导，不做硬性禁止——AI 输出由 prompt 自然引导即可。
_MYTH_POOL: dict[str, str] = {
    "western": "以古希腊诗人 / 《天球图说》之韵律起笔，词章庄严古雅，多用「然」「乃」「遂」等文言虚词；"
               "讲述希腊 / 罗马 / 北欧 / 欧洲民间神话传说（如俄里翁、赫拉克勒斯、奥菲斯等），富有画面感。"
               "主星以 Bayer 编号 + 西方名引用（如「α Ori（Betelgeuse，红超巨星）」）。",
    "chinese": "以《史记·天官书》《楚辞》《步天歌》之韵律起笔，词章庄严古雅，多用「乃」「遂」「盖」等文言虚词；"
               "讲述中国古代天象——二十八宿、三垣、相关历史典故、诗词意象（如杜甫、苏轼咏星诗）。"
               "主星用中国古代星官名（参宿四、天津四、心宿二、牛郎、织女 等）；用中国人名原名（张衡、祖冲之、苏轼）。",
}


def myth_pool_rule(tradition: str) -> str:
    """根据 tradition 取对应的神话池说明。未知 tradition 回落 western。"""
    return _MYTH_POOL.get(tradition, _MYTH_POOL["western"])