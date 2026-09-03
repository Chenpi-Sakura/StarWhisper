# 星语天象 StarWhisper — M2 设计规格

> 版本：v0.6（基于 M1 spec v0.5 增量）| 日期：2026-08-23 | M2 启动日 8.24
> 关联：`docs/specs/2026-08-21-starwhisper-design.md`（M1 spec v0.5，本文件仅描述 M2 增量）

> **v0.6.1 落地声明：** §4.2 / §4.3 / §4.5 / §6.2 / §6.5 / §9 / §11.1 已并入 v0.6.1 修订；M2 实施以本文正文为准，§16 保留作为变更日志索引。正文与 §16 不再冲突。

---

## 0. M2 范围与边界

### 0.1 一句话目标

替换 M1 mock 全链路为真实 astrometry 求解 + WCS SIP 像素投影，补齐 Canvas 描出/闪烁/缓旋转，加入 AI 故事与星座图鉴完整页，支持 HEIC 与 EXIF Orientation。

### 0.2 入 M2

| 模块 | 内容 |
|---|---|
| 真实求解 | `services/astrometry.py`（analyse → scale hint → solve 调参 → race/crop） |
| WCS 投影 | `astropy.WCS(fits.Header(...))` + `SkyCoord(ra, dec, frame="icrs")` + `world_to_pixel(sky)`（含 SIP）；Y_FLIP 由回归脚本锁定 |
| 并发控制 | `SolveSlot` 类（用户请求级 `active=3, queued=5`）；race/crop 内部不再 acquire；超额 HTTP 429 `BUSY` |
| Canvas 动画升级 | overlay 连线描出（rAF，1.2s）+ 星点闪烁；atlas 缓回旋 ±2° sin(2π t / 12s) |
| AI 故事 | `services/ai_provider.py` 抽象 + OpenAI 兼容实现 + 5 星座预设兜底；`POST /api/story` |
| 故事面板 | `StoryPanel.vue`（标题/分段/重讲/换风格/降级徽章） |
| 星座图鉴 | `ConstellationView.vue` 列表 + 详情（5 星座），复用 atlas Canvas |
| HEIC 支持 | `pillow-heif` 服务端解码为内存 JPEG |
| EXIF 方向 | **服务端 `ImageOps.exif_transpose` 统一转正**；响应 orientation=1；前端不再旋转 |
| 端到端真实样图 | 用一张真实 orion 样图跑通，坐标回归校准（误差 < 2px） |

### 0.3 不入 M2

- 观星指数（Open-Meteo + Bortle + 月相 + 评分）→ M3
- 分享卡 / 海报导出 → M3/M4
- 多语种 UI（i18n）→ M4
- 异步任务/进度推送（轮询 / SSE）→ M4（如需）

### 0.4 M2/M3 边界

| 项 | M2 | M3 |
|---|---|---|
| astrometry 真实接入 + WCS | ✓ | 不变 |
| Canvas 描出/闪烁/旋转 | ✓ | 不变 |
| AI 故事接口与面板 | ✓ | 不变 |
| 星座图鉴完整页 | ✓ | 不变 |
| HEIC / EXIF 方向 | ✓ | 不变 |
| 观星指数页（首页） |  | ✓ |
| 浏览器定位 + 城市兜底 |  | ✓ |
| Open-Meteo 聚合 |  | ✓ |
| 月相计算（astral） |  | ✓ |
| Bortle 光污染查表 |  | ✓ |

---

## 1. 设计决策汇总（M2 增量）

| 决策项 | 结论 |
|---|---|
| 真实求解流程 | analyse 优先；有 EXIF → scale hint 单次精确解；无 EXIF → race(4 段焦距 60-500/500-1500/1500-3500/3500-6000 arcminwidth) + 宽边≥6000 追加 crop |
| WCS 投影 | `astropy.WCS(fits.Header(...))` + `SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")` + `world_to_pixel(sky)`；astropy≥5.0 已 0-based，禁止再 -1 |
| 并发 | `SolveSlot` 用户请求级（active=3, queued=5）；race/crop 共用一槽；客户端断开 try/finally 防泄漏；超额立即 429 `BUSY` |
| 超时 | 后端 60s（对齐上游 solve）；前端 65s；race 单段 35s |
| FOV 校验时机 | **analyse 之后、solve 之前**（仅 EXIF 路径）；已解出不再校验（避免浪费 16s） |
| AI Provider | base provider 抽象；OpenAI 兼容实现；可切换 DeepSeek / 盘古 / OpenAI |
| AI Key | 服务端环境变量 `AI_API_KEY`；前端不持有 |
| AI 降级 | 5 星座 × 2 风格预设；provider 失败时返回 `degraded:true`；503 仅当 preset 文件缺失 |
| AI max_tokens | 1000（300 汉字 + 标题 + JSON 余量） |
| AI 超时 | 统一 30s |
| HEIC | `pillow-heif` 注册解码；前端只送原始 .heic，转换在服务端 |
| EXIF 方向 | **服务端 `ImageOps.exif_transpose` 统一转正**；Orientation≠1 的 JPEG 也必重编码；前端不再旋转；响应 `exif_orientation=1` |
| Canvas 缓回旋 | atlas 模式 ±2° sin(2π t / 12s)（M1 决策延续）；overlay 模式不旋转 |
| 样图 banner | `?mock=1` URL 或 `/api/health` 返回 `astrometry:"mock"|"down"` 时挂；真引擎健康时不挂 |
| 故事风格 | `myth`（神话）/ `science`（科普）；可切换 |
| 重讲 | 同 (abbr, style) 重新请求（附 `Cache-Bust: 1` header）；前端 store 缓存层 + 后端 LRU 10min；**不缓存 `degraded:true`** |
| storyStore 状态 | 故事状态完全归 `storyStore`（cache / loading / fetchStory / evict）；scanStore 只保留 `selectedStyle` |
| 图鉴数据 | 复用 `server/data/constellations.json`；新增 `GET /api/constellations` 列表 |
| /api/health | M2 新建（非 M1 不变）；返回 `{ ok, astrometry: "up"|"mock"|"down", ai_provider: "up"|"disabled"|"down", ai_model }` |
| 错误格式 | 沿用 M1 `{ ok, code, message, advice? }`；代理超时改 200 + `{ok:false, code:"TIMEOUT"}`（非 504 无 JSON） |
| M2 覆盖范围 | **仅猎户 8 星**（附录 A ICRS）；其余 4 星座图鉴可浏览，ScanView 不识别 |

---

## 2. 文件结构（M2 新增/变更）

```
server/
├── config.py                     # 改：AI_API_KEY / AI_API_BASE / AI_MODEL / ASTROMETRY_TIMEOUT / MAX_CONCURRENCY / MAX_QUEUE
├── routers/
│   ├── identify.py               # 改：接 astrometry 服务层（替代 fixture 直返）
│   ├── constellation.py          # M1 不变
│   ├── constellations.py         # 新增：GET /api/constellations 列表
│   └── story.py                  # 新增：POST /api/story
├── services/
│   ├── astrometry.py             # 新增：策略层（analyse + 调参 + race + WCS 计算）
│   ├── ai_provider.py            # 新增：base provider 抽象 + OpenAI 兼容实现
│   ├── story_fallback.py         # 新增：5 星座 × 2 风格静态预设
│   └── constellation.py          # M1 不变 + 新增 list_constellations()
├── data/
│   ├── preset_stories.json       # 新增：5 星座 × 2 风格 兜底文案
│   ├── bayer_index.json          # 新增：atlas stars → (RA, Dec) 反查表（用于 WCS world_to_pixel 输入）
│   └── fixtures/solve_orion.json # 改：用真实解算的 8 星坐标回归（误差 < 2px）
└── tests/
    ├── test_astrometry.py        # 新增：analyse/race/crop/WCS 单元 + 集成（httpx mock 上游）
    ├── test_story.py             # 新增：provider 抽象 + 降级 + 风格切换
    └── test_concurrency.py       # 新增：Semaphore ≤3 + 429 BUSY

web/
├── src/
│   ├── App.vue                   # 改：ConstellationView 不再占位
│   ├── types.ts                  # 改：新增 StoryResponse / AtlasListItem / Orientation 枚举
│   ├── views/
│   │   ├── ScanView.vue          # 改：集成 StoryPanel + HEIC 拦截提示
│   │   ├── IndexView.vue         # M2 仍占位（M3 接入）
│   │   └── ConstellationView.vue # 改：列表 + 详情双栏，复用 StarCanvas atlas 模式
│   ├── components/
│   │   ├── StarCanvas.vue        # 改：overlay 描出 + 星点闪烁；atlas 缓旋转
│   │   ├── StoryPanel.vue        # 新增：标题 + 段落 + 重讲/换风格/加载态/降级徽章
│   │   └── common/               # M1 不变
│   ├── stores/
│   │   ├── scan.ts               # 改：仅新增 selectedStyle（删 activeStory / storyLoading / exifOrientation）
│   │   ├── story.ts              # 新增：fetchStory(abbr, style) + 缓存 + Cache-Bust + 不缓存 degraded
│   │   └── atlas.ts              # 新增：图鉴列表与选中
│   ├── api/
│   │   ├── solve.ts              # 沿用 M1（超时/取消不变）
│   │   └── story.ts              # 新增：fetchStory + isStoryProviderDown 判定
│   ├── utils/
│   │   ├── exif.ts               # v0.6.1 退化：可选状态徽章，不参与绘制（不写 8 向矩阵）
│   │   └── heic.ts               # 新增：客户端 MIME 探测 + 提示文案
│   └── style/star-atlas.css      # 改：新增 .story-panel / .atlas-grid / .heic-hint
└── tests/
    ├── StarCanvas.animate.test.ts # 新增：rAF 描出断言（lineWidth 递增 / shadowBlur 脉冲 / atlas ±2°）
    ├── StoryPanel.test.ts        # 新增：props 渲染 / 重讲 emit / 降级标识
    └── story.store.test.ts       # 新增：fetchStory + 缓存命中 + 不缓存 degraded:true + Cache-Bust header
```

---

## 3. API 契约（M2 增量）

### 3.1 POST /api/identify/solve（升级）

**变化点：**
- 后端从 fixture 直返改为调 astrometry 策略层（详见 §4）
- 请求字段：增加 `image` 接受 HEIC；服务端用 `pillow-heif` 解码为内存 JPEG
- 响应：保持 M1 schema；**`stars_overlay[].pixel_x/y` 由 WCS `world_to_pixel` 计算**（不再用 fixture 写死坐标）
- 新增失败码：`ASTROMETRY_DOWN`（502）/ `BUSY`（429）/ `FOV_OUT_OF_RANGE`（业务失败 `ok:false`）/ `HEIC_DECODE_FAILED`（422）

**HTTP:** POST | multipart | field: `image`（JPG/PNG/HEIC，≤20MB）

**成功 HTTP 200（v0.6.1 示例，含真实 WCS 投影坐标；fixture 同样使用真解算坐标，误差 < 2px）：**

```json
{
  "ok": true,
  "solved": true,
  "ra": 92.93, "dec": -2.81,
  "pixel_scale": 23.90, "rotation": 283.66,
  "field_width": 39.94, "field_height": 26.66,
  "solve_time": 16.5,
  "image_width": 6016, "image_height": 4016,
  "exif_orientation": 1,
  "constellations": [
    { "abbr": "ori", "name": "猎户座", "latin": "Orion",
      "confidence": 0.875, "hit_stars": 7, "total_bright_stars": 8 }
  ],
  "stars_overlay": [
    // ★ pixel_x/y 由 §4.2 WCS.world_to_pixel(sky) 投影得出；以下为示意坐标，
    //   真实回归值由 scripts/wcs_regression.py 校准（误差 < 2px）。
    //   fixture/solve_orion.json 必须写入真解算坐标，禁止沿用此示意值。
    { "bayer": "Beta Ori", "name": "参宿七", "magnitude": 0.13,
      "pixel_x": 3421, "pixel_y": 2018, "constellation": "ori" }
  ],
  "overlay_lines": [
    ["Alpha Ori", "Gamma Ori"], ["Alpha Ori", "Lambda Ori"], ["Lambda Ori", "Gamma Ori"],
    ["Alpha Ori", "Zeta Ori"], ["Gamma Ori", "Delta Ori"], ["Delta Ori", "Epsilon Ori"],
    ["Epsilon Ori", "Zeta Ori"], ["Delta Ori", "Beta Ori"], ["Zeta Ori", "Kappa Ori"], ["Beta Ori", "Kappa Ori"]
  ]
}
```

**业务失败 HTTP 200（solved:false）：**

| code | 触发 | advice |
|---|---|---|
| `SOLVE_FAILED` | 索引命中但未解出（星点不足/光害） | "星点模糊或光害过强, 请用更澄澈的夜空照片重试。" |
| `TIMEOUT` | 上游 60s 截断 | "请尝试视野稍窄的星空区域照片。" |
| `FOV_OUT_OF_RANGE` | fov_width > 70° 或 < 1.1° | "请使用普通镜头星空照片, 避开全天鱼眼。" |

**协议错误 HTTP 4xx/5xx：**

| HTTP | code | message | advice |
|---|---|---|---|
| 413 | UPLOAD_TOO_LARGE | 图片超过 20MB 限制 | null |
| 400 | UNSUPPORTED_FORMAT | 仅支持 JPG、PNG、HEIC 格式 | null |
| 422 | HEIC_DECODE_FAILED | HEIC 文件无法解码 | "HEIC 文件损坏或编码异常" |
| 429 | BUSY | 引擎繁忙，请稍后 | "约 30s 后可重试" |
| 502 | ASTROMETRY_DOWN | 星图解析引擎暂不可用 | "请稍后重试或换一张照片" |
| 500 | INTERNAL | 服务端异常 | null |

### 3.2 GET /api/constellation/{abbr}

**M1 不变。** 仍读 `server/data/constellations.json`；大小写不敏感；404 `JSONResponse(status_code=404)`。

### 3.3 POST /api/story（新增）

**HTTP:** POST | `application/json`
**请求：**

```json
{ "abbr": "ori", "style": "myth", "lang": "zh" }
```

**成功 HTTP 200（AI 正常）：**

```json
{
  "ok": true,
  "abbr": "ori",
  "style": "myth",
  "title": "猎户的永恒守望",
  "paragraphs": ["...", "...", "..."],
  "provider": "openai-compatible",
  "model": "deepseek-chat",
  "latency_ms": 1820,
  "cached": false,
  "degraded": false
}
```

**降级 HTTP 200（AI 失败走 preset）：**

```json
{
  "ok": true,
  "abbr": "ori",
  "style": "myth",
  "title": "猎户的永恒守望",
  "paragraphs": ["...预设文案..."],
  "provider": "fallback",
  "model": "preset",
  "latency_ms": 0,
  "cached": false,
  "degraded": true,
  "degraded_reason": "AI_PROVIDER_TIMEOUT"
}
```

**协议错误：**

| HTTP | code | message | advice |
|---|---|---|---|
| 404 | CONSTELLATION_NOT_FOUND | 未收录此星座 | 沿用 M1 404 文案 |
| 400 | INVALID_STYLE | style 必须是 myth 或 science | null |
| 503 | STORY_DISABLED | 服务端未配置 AI_API_KEY 且预设缺失 | null |

**字段说明：**
- `cached`：同一 `(abbr, style)` 在 10 分钟内命中后端 LRU 缓存
- `degraded:true`：AI 失败但返回了预设故事；前端 StoryPanel 显示「离线故事」徽章
- `degraded_reason`：`AI_PROVIDER_TIMEOUT` / `AI_PROVIDER_5XX` / `AI_PROVIDER_PARSE_ERROR`

### 3.4 GET /api/constellations（新增）

**HTTP 200：**

```json
{
  "ok": true,
  "items": [
    { "abbr": "ori", "name": "猎户座", "latin": "Orion",
      "glyph": "✶", "season": "冬季",
      "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
      "bright_stars": 8 },
    { "abbr": "cyg", "name": "天鹅座", "latin": "Cygnus", "glyph": "✦", "season": "夏季", "caption": "...", "bright_stars": 6 },
    { "abbr": "sco", "name": "天蝎座", "latin": "Scorpius", "glyph": "✶", "season": "夏季", "caption": "...", "bright_stars": 7 },
    { "abbr": "leo", "name": "狮子座", "latin": "Leo", "glyph": "✶", "season": "春季", "caption": "...", "bright_stars": 7 },
    { "abbr": "and", "name": "仙女座", "latin": "Andromeda", "glyph": "✶", "season": "秋季", "caption": "...", "bright_stars": 6 }
  ]
}
```

**用途：** 星座图鉴列表页（M1 是占位「即将揭晓」，M2 落地）。

### 3.5 GET /api/health（M2 新建）

> M1 main.py 未实现 `/api/health`（M1 README 中的 `curl /api/health` 是占位）；M2 新建。

**HTTP 200：**

```json
{
  "ok": true,
  "astrometry": "up",
  "ai_provider": "up",
  "ai_model": "deepseek-chat"
}
```

**字段值：**

- `astrometry`: `"up"` | `"mock"` | `"down"`
  - `up`   — 上游 `/health` 正常
  - `mock` — `ASTROMETRY_MOCK=1` 环境变量启用
  - `down` — 上游不可达或响应非 200
- `ai_provider`: `"up"` | `"disabled"` | `"down"`
  - `up`       — provider.health() == True
  - `disabled` — 未配置 `AI_API_KEY`
  - `down`     — provider.health() == False
- `ai_model`: 当前 provider 的模型名（disabled 时为 `null` 或 `"none"`）

**前端用法：** ScanView banner 切换条件（详见 §16.2.2）：

```typescript
const showMockBanner = computed(() =>
  route.query.mock === '1' ||
  health.astrometry === 'mock' ||
  health.astrometry === 'down'
)
```

---

## 4. 真实 astrometry 策略层

### 4.1 流程总览（v0.6.1：SolveSlot + 4 段 race）

```
[1] 接收 multipart image
    ├─ 格式校验（JPG/PNG/HEIC）+ 20MB 校验
    └─ normalize_image（详见 §9.1）：
        - HEIC → JPEG bytes
        - Orientation ≠ 1 的 JPEG → 重编码 JPEG bytes
        - Orientation 1 的 JPEG/PNG → 原样透传
[2] SolveSlot.acquire()（用户请求级 active=3, queued=5，详见 §4.3）
    └─ 超额 → 立即 429 BUSY
    ★ race/crop 内部不再 acquire_slot
[3] 调用 /analyse（httpx, timeout 10s）
    ├─ {success:true, has_exif:true, ...scale_low/high...} → step 3b
    ├─ {success:true, has_exif:true, fov...}                 → step 3b（FOV 预检）
    └─ {success:false, has_exif:false}                      → step 4b（race）
[3b] ★ FOV 预检（仅 EXIF 路径）：超 [1.1°, 70°] → 立即 {ok:false, code:"FOV_OUT_OF_RANGE"}
[4a] 单次精确解（有 EXIF）：
       POST /solve {scale_low, scale_high, scale_units=arcminwidth,
                     downsample_factor=4, depth_low=50, depth_high=100}
       timeout 60s
[4b] 并发 race（无 EXIF，4 段并行）：
       60-500 / 500-1500 / 1500-3500 / 3500-6000 arcminwidth
       单段 timeout 35s
       取最快 solved:true 胜出；全失败 → step 4c
       ★ 4 段均在已 acquire 的用户级槽位内执行，不再单独 acquire
[4c] 若宽边 ≥ 6000px，追加 center-crop 1/2 后重跑 step 4b（race）
    crop 顺序写死：裁切坐标 → += (crop_x0, crop_y0) → 用原图 height Y_FLIP
[5] 上游响应统一映射（详见 §4.4）：
    solved:true     → WCS(fits.Header(wcs_header)) + SkyCoord + world_to_pixel → pixel_x/y
                       （Y_FLIP 由 §16.1.2 回归脚本锁定的模块常量）
    solved:false    → { code: SOLVE_FAILED }
    raw_output 含 "timed out" 或 error "solve operation timed out" → { code: TIMEOUT }
    HTTP 连接失败/非 JSON → GET /api/health；仍失败 → { code: ASTROMETRY_DOWN, http: 502 }
    ★ 已解出不再校验 FOV（避免浪费 16s 解算）
[6] 计算 hit_stars / confidence（命中亮星数 / 内置星表亮星数）
[7] 拼装 SolveResult 返回（响应 exif_orientation=1）
```

### 4.2 WCS 投影（关键决策，v0.6.1 修订）

```python
# server/services/astrometry.py
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
import json
from pathlib import Path

# Y_FLIP 由 scripts/wcs_regression.py 锁定为常量，禁止运行时探测
# 真解回归：known stars ICRS → world_to_pixel → 与 fixture 比对
#   max(diffs_no_flip) < 2px → Y_FLIP = False
#   max(diffs_flip)    < 2px → Y_FLIP = True
#   否则 → RegressionError，禁止进入主链路
Y_FLIP: bool = False  # T1 第一天回归后改为 True/False 锁死

_BAYER_INDEX = json.loads(
    Path(__file__).parent.parent.joinpath("data/bayer_index.json").read_text(encoding="utf-8")
)

def project_stars(wcs_header: dict, image_height: int) -> list[dict]:
    """从上游 wcs_header 投影猎户 8 星 ICRS → 原图像素坐标（Y_FLIP 锁死）"""
    wcs = WCS(fits.Header(wcs_header))  # 上游 wcs_header 是 dict[str, str]，先转 Header
    out: list[dict] = []
    for entry in _BAYER_INDEX.values():
        sky = SkyCoord(ra=entry["ra"] * u.deg, dec=entry["dec"] * u.deg, frame="icrs")
        x, y = wcs.world_to_pixel(sky)   # astropy ≥ 5.0 已 0-based；禁止再 -1
        pixel_x = round(float(x), 2)     # 保留 2 位亚像素精度
        pixel_y = round(float(y), 2)
        if Y_FLIP:
            pixel_y = image_height - 1 - pixel_y
        out.append({
            "bayer": entry["bayer"],
            "name": entry["name"],
            "magnitude": entry["magnitude"],
            "pixel_x": pixel_x,
            "pixel_y": pixel_y,
            "constellation": entry["abbr"],
        })
    return out
```

**关键注意事项（v0.6.1）：**

- `WCS(fits.Header(...))` 是唯一正确构造方式；**禁止 `WCS(wcs_header_dict=...)`**（不存在）
- `SkyCoord(ra, dec, frame="icrs")` + `world_to_pixel(sky)` 是 SIP 兼容路径；**禁止 `wcs_world2pix`**（无 SIP）
- astropy ≥ 5.0 `world_to_pixel` 已是 **0-based**，禁止再 `−1`（否则整体偏 1px，与「误差 < 2px」验收打架）
- `Y_FLIP` **不赌 CTYPE**（CTYPE 是天球轴，不是像素 Y）。由 `scripts/wcs_regression.py` 在 T1 第一天锁定为模块常量
- `bayer_index.json` 来源：**手写 BSC/HYG 摘录**（见附录 A），禁止"从 constellations.json 生成"——后者只有 viewBox x/y，无 ICRS RA/Dec
- **必须用完整 `wcs_header`**（含 SIP `A_* / B_*` + `AP_ORDER / BP_ORDER`），禁止 `center + pixel_scale + rotation` 简化仿射
- 视场外的星仍写坐标（pixel_x/y 可负或超图幅），Canvas clipping 自然裁切
- **M2 仅覆盖猎户 8 星**（附录 A）；其余 4 星座在 ScanView 显示"仅识别猎户座"提示，详见 §7

### 4.3 并发控制（v0.6.1 重写：用户请求级信号量）

```python
# server/services/astrometry.py
import asyncio
from contextlib import asynccontextmanager

class SolveSlot:
    """用户请求级信号量；race/crop 内部不再 acquire_slot"""
    def __init__(self, max_active: int = 3, max_queue: int = 5):
        self._sem = asyncio.Semaphore(max_active)
        self._active = 0
        self._queued = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        queued = False
        async with self._lock:
            if self._active >= 3 and self._queued >= 5:
                raise BusyError()
            self._queued += 1
            queued = True
        try:
            await self._sem.acquire()
            async with self._lock:
                self._queued -= 1
                queued = False
                self._active += 1
            try:
                yield
            finally:
                async with self._lock:
                    self._active -= 1
                self._sem.release()
        except BaseException:
            # 客户端断开（asyncio.CancelledError）或异常路径
            # 兜底：_queued 未减则减，保证不泄漏
            async with self._lock:
                if queued:
                    self._queued -= 1
                    queued = False
            raise

class BusyError(Exception):
    """429 BUSY 触发条件"""

_SLOT = SolveSlot(max_active=3, max_queue=5)
```

**调用约定：**

```python
async def solve_endpoint(image_bytes: bytes):
    async with _SLOT.acquire():           # 仅外层一次
        result = await _solve_internal(image_bytes)   # race 4 段 + crop 都在内部，不再 acquire
        return result
```

- 单实例进程内上限 3（**用户请求级**，不是 httpx 级）
- 排队上限 5（超出立即 429，不挂死前端）
- `try/finally + 标志位 queued` 保证客户端断开（`CancelledError`）也能清理 `_queued`，不泄漏
- **禁止 `_SEMAPHORE._waiters`**（私有字段，Python 版本可能为 None，且 check-then-acquire 有竞态）
- 多进程部署时各自独立持有 SolveSlot（开发期单实例够用）

### 4.4 失败映射（详细）

| 上游响应 | 上游特征 | 我们的响应 |
|---|---|---|
| `{solved:true, wcs_header, ra, dec, ...}` | 正常 | 200 + SolveResult |
| `{solved:false, raw_output:"Field 1 did not solve..."}` | 索引命中但未解出 | 200 `{ok:false, code:"SOLVE_FAILED", advice:"..."}` |
| `{solved:false, error:"solve operation timed out"}` | 上游 60s 截断 | 200 `{ok:false, code:"TIMEOUT", advice:"..."}` |
| HTTP 连接失败 / 5xx / 非 JSON | 网络/上游故障 | GET /health；仍故障 → 502 `{code:"ASTROMETRY_DOWN"}` |
| 客户端 60s 内无响应 | 后端代理超时 | 504（前端 fallback 到 65s 自身 timeout） |
| fov_width > 70° 或 < 1.1° | 索引不覆盖 | 200 `{ok:false, code:"FOV_OUT_OF_RANGE", advice:"..."}` |
| 并发超额 | Semaphore 满 + 排队满 | 429 `BUSY` |
| HEIC 解码失败 | pillow-heif 抛异常 | 422 `HEIC_DECODE_FAILED` |

**重要：** `raw_output` 不可信（spec §3.0 警示）。看到 `solved:false` 必须额外检查 `error` 字段是否含 "timed out" 才映射为 TIMEOUT；否则一律 SOLVE_FAILED。

### 4.5 FOV 范围校验（v0.6.1 前移：analyse 之后、solve 之前）

```python
# server/services/astrometry.py
class FovOutOfRangeError(Exception):
    """FOV_OUT_OF_RANGE 触发条件"""

def check_fov_range_pre(field_width: float | None, field_height: float | None) -> None:
    """仅在 EXIF 路径下调用；无 EXIF 不预检（不知道 FOV）"""
    if field_width is None or field_height is None:
        return  # 无 EXIF，跳过预检
    max_fov = max(field_width, field_height)
    if max_fov > 70 or max_fov < 1.1:
        raise FovOutOfRangeError(f"FOV={max_fov:.2f}° 超出 1.1°–70°")
```

**调用时机（v0.6.1 重排）：**

```
[1] 格式校验 + 解码（§9.1 normalize_image）
[2] 取用户级槽位（§4.3 SolveSlot）
[3] /analyse；成功拿到 scale_hint 且 has_exif → step 3b
[3b] ★ FOV 预检（仅 EXIF 路径）；越界 → 立即 {ok:false, code:"FOV_OUT_OF_RANGE"}
[4a/b/c] 真实解算
[5] 解析响应
[6] ★ 已解出不再校验 FOV（避免浪费 16s 解算时间；含 79° 边缘命中场景）
[7] 拼装 SolveResult
```

- 越界 → 业务失败 `FOV_OUT_OF_RANGE`（HTTP 200, ok:false），**不进入 solve**
- advice: "请使用普通镜头星空照片, 避开全天鱼眼"
- **已解出不再校验**——避免事后否决浪费算力

### 4.6 上游解算时间观测

`solve_time` 字段直接透传上游值（秒，浮点）。前端 `scanStore.result.solve_time` 存入；StoryPanel 可选展示（"AI 用时 1.8s, 求解用时 16.5s"）。

---

## 5. AI Provider 抽象（PREFERENCE_11 binding）

### 5.1 接口定义

```python
# server/services/ai_provider.py
from abc import ABC, abstractmethod
from typing import Literal, Optional
import os

StoryStyle = Literal["myth", "science"]

class AIProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str: ...
    @abstractmethod
    async def health(self) -> bool: ...

class OpenAICompatibleProvider(AIProvider):
    """DeepSeek / 盘古 / OpenAI 统一走 OpenAI Chat Completions 格式"""
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
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
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
                "max_tokens": 600,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self._base_url}/models", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

class DisabledProvider(AIProvider):
    """未配置 AI_API_KEY 时使用，强制走 fallback"""
    name = "disabled"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        raise RuntimeError("AI_PROVIDER_DISABLED")

    async def health(self) -> bool:
        return False

def make_provider() -> AIProvider:
    api_key = os.getenv("AI_API_KEY")
    if api_key:
        return OpenAICompatibleProvider(
            base_url=os.getenv("AI_API_BASE", "https://api.deepseek.com/v1"),
            api_key=api_key,
            model=os.getenv("AI_MODEL", "deepseek-chat"),
        )
    return DisabledProvider()
```

### 5.2 Prompt 模板（中文）

**system：**

```
你是「星语天象 StarWhisper」的星座叙事官。
任务：用 {style_zh} 视角讲述 {constellation_zh}（{latin}），3-4 段共 220-300 字。
要求：
- 神话视角：讲述希腊/中国/民间神话来源，富有画面感
- 科普视角：解释天文结构、观测季节、深空摄影要点
- 段落分明，每段 60-90 字，不堆砌术语
- 文末不加「希望你喜欢」「祝观星愉快」之类废话
- 不编造星名/坐标；如不确定请用「传说中」等限定词
- 输出仅含标题 + 段落正文，不要 JSON / Markdown 标记
```

**user：**

```
星座：{constellation_zh} ({latin})
风格：{style_zh}
主要星：
- {bayer} {name_zh}，星等 {magnitude}
...
连线：{lines_count} 条
季节：{season}
```

**标题行解析：** 期望 LLM 首行为 `标题：xxx` 或 `# xxx`；后端解析首行作为 `title`，其余按空行分段为 `paragraphs[]`。解析失败回退到 `title = "{星座中文}的故事"` + 整段为单 paragraph。

### 5.3 降级（preset_stories.json）

5 星座 × 2 风格 = 10 段预设，JSON 结构：

```json
{
  "ori": {
    "myth":    { "title": "猎户的永恒守望", "paragraphs": ["...", "..."] },
    "science": { "title": "猎户座：冬季星空中的一把钥匙", "paragraphs": ["..."] }
  },
  "cyg": { "myth": {...}, "science": {...} },
  "sco": { "myth": {...}, "science": {...} },
  "leo": { "myth": {...}, "science": {...} },
  "and": { "myth": {...}, "science": {...} }
}
```

降级触发条件：
- `AIProvider.health() == False`
- `chat()` 抛 Timeout / 5xx / JSON 解析失败
- LLM 输出无法解析（首行无标题标记）

降级响应仍返回 `{ok:true, degraded:true, provider:"fallback"}`，前端 StoryPanel 显示红色「离线故事」徽章。

### 5.4 缓存策略

**后端：** 进程内 LRU `(abbr, style) -> StoryResponse`，TTL 10 分钟（避免重复 token 消耗）

```python
from cachetools import TTLCache
_STORY_CACHE: TTLCache = TTLCache(maxsize=64, ttl=600)

def get_cached(abbr: str, style: str) -> Optional[dict]:
    return _STORY_CACHE.get((abbr, style))

def set_cached(abbr: str, style: str, payload: dict) -> None:
    _STORY_CACHE[(abbr, style)] = payload
```

**强制刷新：** 用户点「重讲」时附 header `Cache-Bust: 1`，后端跳过缓存直接重发 LLM。

**前端：** Pinia `storyStore.cache: Map<string, StoryResponse>` 同 key 不重发；`evict(abbr, style)` 清单项。

### 5.5 provider 配置矩阵

| 供应商 | `AI_API_BASE` | `AI_MODEL` | 说明 |
|---|---|---|---|
| DeepSeek（默认） | `https://api.deepseek.com/v1` | `deepseek-chat` | 中文优秀，价格低 |
| 华为云盘古 | `https://pangu.{region}.modelarts-paas.com/v1/infers/v1` | `pangu-nlp-4` | 需专用 token 格式（非 Bearer）—— M2.5 再适配 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | 备选，海外评审使用 |
| 智谱 GLM-4 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 备选 |

盘古的鉴权与 OpenAI 不兼容（华为云使用 IAM 签名），M2 仅实现 OpenAI 兼容基类；盘古适配放 M2.5 或后续。

---

## 6. Canvas 动画升级

### 6.1 overlay 描出 + 闪烁

**描出动画（1.2s 一次性）：**

```typescript
// StarCanvas.vue 中 drawOverlay 内的描出逻辑（伪代码）
const startTs = performance.now()
const DUR = 1200
function frame(now: number) {
  const t = Math.min(1, (now - startTs) / DUR)
  const eased = 1 - Math.pow(1 - t, 3)  // easeOutCubic
  for (const line of lines) {
    const lineT = clamp((t - line.delay) / (1 - line.delay), 0, 1)
    const w = lineT * 2  // 0 → 2
    const a = lineT * 0.9  // 0 → 0.9
    ctx.strokeStyle = `rgba(212,160,23,${a})`
    ctx.lineWidth = w
    ctx.beginPath()
    ctx.moveTo(...)
    ctx.lineTo(...)
    ctx.stroke()
  }
  if (t < 1) rafId = requestAnimationFrame(frame)
}
rafId = requestAnimationFrame(frame)
```

- 每条线段错峰 80ms 起始 → 连线呈「生长」感
- `lineWidth` 0 → 2，`alpha` 0 → 0.9（金墨）

**星点闪烁（持续循环）：**

```typescript
function twinkleFrame(now: number) {
  const phase = (now / 1600) * Math.PI * 2  // 1.6s 周期
  const blur = 6 + 4 * Math.sin(phase)
  ctx.shadowBlur = blur
  ctx.shadowColor = 'gold'
  // ... 画星点
  if (visible) rafId = requestAnimationFrame(twinkleFrame)
}
```

- `shadowBlur = 6 + 4 * sin(t * 2π / 1.6)`
- 仅 `done` 状态启用；`empty` 状态 opacity 0.2 不闪烁
- 标签页隐藏（`document.visibilityState === 'hidden'`）停 rAF

**reduced-motion：** 直接终态，无描出无闪烁（`window.matchMedia('(prefers-reduced-motion: reduce)').matches`）。

### 6.2 atlas 缓回旋（v0.6.1 改回 M1 决策：±2°）

```typescript
// StarCanvas.vue atlas 模式
const ROT_AMP_RAD = 2 * Math.PI / 180   // ±2°（M1 决策延续）
const ROT_PERIOD_MS = 12000             // 12s/周
function atlasFrame(now: number) {
  const t = (now - startTs) / ROT_PERIOD_MS
  const theta = ROT_AMP_RAD * Math.sin(2 * Math.PI * t)  // sin 缓回旋
  ctx.save()
  ctx.translate(contentW / 2, contentH / 2)
  ctx.rotate(theta)
  ctx.translate(-contentW / 2, -contentH / 2)
  // 画网格 + 双同心圆 + 连线 + 星点
  ctx.restore()
  if (visible) rafId = requestAnimationFrame(atlasFrame)
}
```

- `θ = 2° × sin(2π t / 12s)`：**±2° 缓回旋**，不会倒过来像屏保（M1 决策延续）
- 用户切回 overlay 模式停旋转；再切回 atlas 重置 startTs
- reduced-motion：不旋转（直接终态）
- IntersectionObserver：标签页隐藏或元素离屏停 rAF

### 6.3 overlay 不旋转（沿用 M1）

spec §6.1 已明确 overlay 模式不旋转（WCS 已投影对齐）。M2 沿用此约束，不引入旋转。

### 6.4 性能守则

- 保留 `shadowBlur`（避免 CSS filter 整 canvas 重绘）
- 描出阶段一次性 rAF（1.2s 后停止）
- 闪烁/旋转阶段持续 rAF，60fps
- prefers-reduced-motion：跳过所有动画
- visible 状态：`IntersectionObserver` + `document.visibilitychange`，隐藏时 `cancelAnimationFrame`
- 切换 mode 时清理旧 rafId，避免叠加

### 6.5 EXIF Orientation（v0.6.1 改服务端处理；前端不旋转）

**关键决策：** 现代浏览器对 JPEG `<img>` **已按 EXIF Orientation 自动显示**；前端再做 CSS `rotate` + Canvas `setTransform` 会转两次。M2 改为服务端 `ImageOps.exif_transpose` 统一正向化，**前端不旋转**。

**服务端实现（详见 §9.1 normalize_image）：**

```python
# server/routers/identify.py
from PIL import Image, ImageOps

def normalize_image(content: bytes) -> tuple[bytes, int, int, int]:
    """服务端统一正向化：EXIF Orientation 1-8 → 1（HEIC 必转 JPEG；Orientation ≠ 1 的 JPEG 必重编码；Orientation 1 的 JPEG/PNG 原样透传）"""
    img = Image.open(BytesIO(content))
    transposed = ImageOps.exif_transpose(img)
    width, height = transposed.size
    # 判断是否真正"转正过"——对象身份变化 或 格式非 JPEG/PNG
    changed = transposed is not img or img.format in ("HEIF", "HEIC")
    if changed:
        buf = BytesIO()
        # ★ Orientation ≠ 1 的 JPEG 也必须重编码送上游：避免浏览器按 EXIF 显示 + solver 看到未旋转像素 → overlay 偏 90°
        transposed.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue(), 1, width, height
    # Orientation 1 的 JPEG/PNG 原样透传，禁止压缩丢星（spec §8）
    return content, 1, *img.size
```

**前端约定：**

- 不再读取 EXIF Orientation；不再做 CSS `rotate` 或 Canvas `setTransform` 旋转
- `utils/exif.ts` 退化为**可选提示**（仅用于"这张照片是 iPhone 竖拍"之类的状态徽章，**不参与绘制**）
- 不写 8 向矩阵测试（无旋转逻辑）
- 响应 `exif_orientation` 恒为 `1`；前端可省略该字段处理

**T7 工时缩减：** 3h → 0.5h（仅写读失败兜底 + ScanView 提示文案）。

---

## 7. AI 故事面板（StoryPanel.vue）

### 7.1 UI 结构

```
┌─ PlateBox (.story-panel) ─────────────────────�
│ 标题：猎户的永恒守望                            │
│ 风格：[神话] [科普]      ↻ 重讲                  │
│ ──────────────────────────────                 │
│ 第一段...                                       │
│ 第二段...                                       │
│ 第三段...                                       │
│ ──────────────────────────────                 │
│ [离线故事] 徽章（degraded=true 时显示）           │
│ 提供方：openai-compatible · 1.8s                │
└─────────────────────────────────────────────────┘
```

### 7.2 Props 与 Emits

```typescript
interface Props {
  abbr: string
  style: 'myth' | 'science'
  story: StoryResponse | null
  loading: boolean
}

interface Emits {
  (e: 'changeStyle', style: 'myth' | 'science'): void
  (e: 'regenerate'): void
}
```

### 7.3 交互

- **重讲**：emit `regenerate` → scanStore 清 story 缓存 + storyStore.evict → 重新 fetch
- **换风格**：emit `changeStyle` → scanStore.setStyle → StoryPanel props.style 更新 → 自动重新拉取
- **加载态**：3 行脉冲骨架（PlateBox 内置 skeleton class）
- **错误态**：provider 故障且无 fallback → 显示「故事暂不可用」+ 重试按钮
- **降级标识**：`degraded=true` 时显示红色「离线故事」徽章 + 鼠标悬停 tooltip 显示 `degraded_reason`

### 7.4 数据流

```
[ScanView done 状态]
  用户点击 StarChip (activeAbbr)
    → scanStore.selectConstellation(abbr)
    → StoryPanel 监听 activeAbbr/style 变化
      → storyStore.fetchStory(abbr, storyStore.currentStyle)
          → POST /api/story { abbr, style }
          → 命中缓存 (前端 storyStore 或后端 LRU) 直接返回
      → 渲染 title / paragraphs / provider / latency_ms
```

---

## 8. 星座图鉴完整页（ConstellationView.vue）

### 8.1 页面结构

```
┌────────────────────────────────────────────────────────┐
│  App.vue 报头 + tab [星空识别] [观星指数] [星座图鉴*]      │
├────────────────────────────────────────────────────────┤
│  ┌─ .atlas-list ──┐  ┌─ .atlas-detail ─────────────────┐ │
│  │ ✶ 猎户座        │  │  ✶ 猎户座（Orion）              │ │
│  │   冬季 · 8 亮星  │  │  「冬夜之王。腰带三星之下...」   │ │
│  │ ✦ 天鹅座        │  │  ┌─────────────────────────┐   │ │
│  │   夏季 · 6 亮星  │  │  │ StarCanvas atlas 模式     │   │ │
│  │ � 天蝎座        │  │  │ （双同心圆 + 缓旋转 12s） │   │ │
│  │   夏季 · 7 亮星  │  │  └─────────────────────────┘   │ │
│  │ ✶ 狮子座        │  │  亮星：                         │ │
│  │   春季 · 7 亮星  │  │  · 参宿四 参宿五 参宿六 参宿七... │ │
│  │ ✶ 仙女座        │  │                                │ │
│  │   秋季 · 6 亮星  │  │                                │ │
│  └─────────────────┘  └────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

### 8.2 数据源

- **列表**：GET /api/constellations（atlasStore.loadList 一次性拉取）
- **详情**：复用 GET /api/constellation/{abbr}（atlasStore.select 拉详情）

### 8.3 交互

- 默认选中第一个（orion）
- 点击列表项：右侧 atlas 重绘（缓旋转停止 → 重置 startTs → 重新旋转）
- atlas 模式沿用 §6.2 缓旋转
- 选中星座有键盘焦点时，左右方向键切换上一个/下一个
- 列表项显示 glyph（✶/✦ 等 Unicode 符号）+ 中文名 + 季节 + 亮星数

---

## 9. HEIC / EXIF 方向

### 9.1 服务端正向化与解码（v0.6.1 重写：修正 JPEG 透传 bug）

```python
# server/routers/identify.py
from io import BytesIO
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # 模块导入时注册一次；HEIF 格式由 PIL 接管

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}


def normalize_image(content: bytes) -> tuple[bytes, int, int, int]:
    """服务端统一正向化，返回 (jpeg_or_png_bytes, exif_orientation, width, height)

    v0.6.1 关键修复：
    - Orientation ≠ 1 的 JPEG 必须把转正后的图送上游（再编码 q95 可接受）
      否则浏览器按 EXIF 显示 + solver 看到未旋转像素 → overlay 偏 90°
    - Orientation 1 的 JPEG / PNG 原样透传（禁止压缩丢星，spec §8）
    - HEIC 一律转码为 JPEG（HEIF 格式 PIL 不直出，solver 只认 JPEG/PNG）
    """
    img = Image.open(BytesIO(content))
    transposed = ImageOps.exif_transpose(img)
    width, height = transposed.size
    # changed 判定：对象身份变化（Orientation ≠ 1 时 PIL 返回新对象）或格式是 HEIF
    changed = transposed is not img or img.format in ("HEIF", "HEIC")
    if changed:
        buf = BytesIO()
        transposed.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue(), 1, width, height
    # Orientation 1 的 JPEG/PNG 原样送上游，禁止压缩丢星
    return content, 1, *img.size
```

**关键约定：**

- `pillow-heif>=0.16` 加入 `server/requirements.txt`
- 转换在内存完成，不落盘
- 响应 `exif_orientation` **恒为 `1`**（已转正）
- `image_width/height` 必须是**送进 solve 那张图**的尺寸，与 WCS NAXIS 一致

### 9.2 前端拦截升级

- `<input accept=".jpg,.jpeg,.png,.heic,.heif">`
- utils/heic.ts：探测 MIME（`image/heic` / `image/heif`），允许通过；非白名单仍 toast
- 服务端 422 `HEIC_DECODE_FAILED`：编码损坏或格式异常
- **HEIC 不一定无 EXIF**：相册原图有 Orientation；仅微信/截图剥 EXIF 才走 race 路径

### 9.3 客户端 EXIF（v0.6.1 改为可选提示，不再参与绘制）

- 前端 **不读取 EXIF Orientation**，不做 CSS / Canvas 旋转（详见 §6.5）
- `utils/exif.ts` 退化为**可选状态徽章**（如"这张照片是 iPhone 竖拍"），不写 8 向矩阵测试
- 旋转由服务端 `normalize_image` 一次完成

---

## 10. 异常与降级（M2 增量）

| 场景 | 用户看到 | 降级 |
|---|---|---|
| 求解失败 SOLVE_FAILED | errorCard + advice | 重试 |
| 求解超时 TIMEOUT | errorCard + 「视野稍窄」advice（200 ok:false，非 504 无 JSON） | 重试 |
| FOV 超 1.1°–70° FOV_OUT_OF_RANGE | errorCard + 「请使用普通镜头星空照」advice（前置于 solve） | 换图 |
| Astrometry 不可达 502 | toast + 「引擎暂不可用」 | 稍后重试 |
| 并发超额 429 BUSY | toast + 「引擎繁忙」 + 30s 后重试（用户请求级 SolveSlot） | 自动 |
| HEIC 解码失败 422 | toast + 「HEIC 文件损坏」 | 转换格式重试 |
| 服务端 exif_transpose 失败 | 422 HEIC_DECODE_FAILED | 转换格式重试 |
| AI 故事 provider 失败 | 离线故事徽章 + 预设文案（`degraded:true`；非 503） | 自动 |
| AI 故事超时（30s） | 离线故事徽章 | 自动 |
| StoryPanel 网络错误 | 「故事暂不可用」+ 重试按钮 | 手动 |
| 上游 astrometry 5xx | 502 ASTROMETRY_DOWN | GET /health 重试 |

---

## 11. 状态管理扩展（M2）

### 11.1 scanStore（M1 + M2 增量，v0.6.1 收敛字段）

**新增字段（仅保留 selectedStyle）：**

```typescript
selectedStyle: 'myth' | 'science'  // 默认 'myth'；UI 风格切换
```

**新增 actions：**

```typescript
setStyle(style: 'myth' | 'science'): void  // 切换风格 → StoryPanel 监听 + storyStore 重新拉取
```

**v0.6.1 删除项：**

- ~~`activeStory: StoryResponse | null`~~：故事状态完全归 `storyStore`（§11.2）
- ~~`storyLoading: boolean`~~：同上
- ~~`exifOrientation: number`~~：服务端 `normalize_image` 统一转正，前端不再读 EXIF
- ~~`applyExifOrientation()` action~~：同上

### 11.2 storyStore（新增）

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { StoryResponse } from '../types'

export const useStoryStore = defineStore('story', () => {
  const cache = ref<Map<string, StoryResponse>>(new Map())
  const loading = ref(false)

  function key(abbr: string, style: string): string {
    return `${abbr}::${style}`
  }

  async function fetchStory(abbr: string, style: string): Promise<StoryResponse> {
    const k = key(abbr, style)
    const hit = cache.value.get(k)
    if (hit) return hit
    loading.value = true
    try {
      const r = await fetch('/api/story', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abbr, style, lang: 'zh' }),
      })
      const data: StoryResponse = await r.json()
      cache.value.set(k, data)
      return data
    } finally {
      loading.value = false
    }
  }

  function evict(abbr: string, style: string): void {
    cache.value.delete(key(abbr, style))
  }

  return { cache, loading, fetchStory, evict }
})
```

### 11.3 atlasStore（新增）

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

interface AtlasListItem {
  abbr: string; name: string; latin: string
  glyph: string; season: string
  caption: string; bright_stars: number
}

export const useAtlasStore = defineStore('atlas', () => {
  const list = ref<AtlasListItem[]>([])
  const selected = ref<string>('ori')
  const detail = ref<any>(null)
  const loading = ref(false)

  async function loadList(): Promise<void> {
    if (list.value.length > 0) return
    const r = await fetch('/api/constellations')
    const data = await r.json()
    list.value = data.items
  }

  async function select(abbr: string): Promise<void> {
    selected.value = abbr
    loading.value = true
    try {
      const r = await fetch(`/api/constellation/${abbr}`)
      detail.value = await r.json()
    } finally {
      loading.value = false
    }
  }

  return { list, selected, detail, loading, loadList, select }
})
```

---

## 12. M2 交付清单（v0.6.1 与 §2/T7 对齐）

### 后端
- [ ] `services/astrometry.py` 策略层（analyse + 调参 + race 4 段 + crop + WCS 投影 + Y_FLIP 锁定常量）
- [ ] `SolveSlot` 类（用户请求级 active=3, queued=5）；race/crop 内部不再 acquire；try/finally 防 `_queued` 泄漏
- [ ] 上游失败映射（SOLVE_FAILED / TIMEOUT / ASTROMETRY_DOWN / FOV_OUT_OF_RANGE / HEIC_DECODE_FAILED）；代理超时改 200 TIMEOUT（非 504）
- [ ] FOV 预检前移（analyse 之后、solve 之前，仅 EXIF 路径）；已解出不再校验
- [ ] `services/ai_provider.py` 抽象 + OpenAI 兼容实现（max_tokens=1000, timeout=30s）+ DisabledProvider（走 preset degraded:true，非 503）
- [ ] `services/story_fallback.py` + `data/preset_stories.json`（5 星座 × 2 风格）
- [ ] `routers/story.py` POST /api/story（含 10min LRU 缓存 + Cache-Bust header；**不缓存 degraded:true**）
- [ ] `routers/constellations.py` GET /api/constellations 列表
- [ ] `routers/health.py` GET /api/health（**M2 新建**，非"M1 不变"；返回 astrometry: up|mock|down）
- [ ] `normalize_image`（pillow-heif + `ImageOps.exif_transpose` + JPEG 透传 bug 已修；响应 orientation=1）
- [ ] `data/bayer_index.json`（猎户 8 星 ICRS J2000 RA/Dec；附录 A 手写，禁止从 constellations.json 生成）
- [ ] `data/fixtures/solve_orion.json` 用真实 WCS 坐标回归（误差 < 2px）
- [ ] 单元测试：test_astrometry / test_story / test_concurrency / test_health

### 前端
- [ ] `utils/exif.ts` **可选状态徽章**（不参与绘制，不写 8 向矩阵）
- [ ] `utils/heic.ts`（MIME 探测 + 提示文案）
- [ ] `utils/env.ts`（`route.query.mock === '1'` 读取；**禁止** `import { env }` 假装有 `ASTROMETRY_MOCK`）
- [ ] `stores/health.ts`（启动拉 `/api/health`；缓存 `astrometry` / `ai_provider`）
- [ ] `types.ts` 新增 StoryResponse / AtlasListItem
- [ ] `StarCanvas.vue`：overlay 描出 1.2s + 星点闪烁 + **atlas 缓回旋 ±2° sin(2π t / 12s)** + IntersectionObserver
- [ ] `StoryPanel.vue`：标题/段落/重讲/换风格/加载态/降级徽章
- [ ] `storyStore`（cache / loading / fetchStory / evict / Cache-Bust:1；**不缓存 degraded:true**）+ `atlasStore`
- [ ] `scanStore` 仅 `selectedStyle`（**删** activeStory / storyLoading / exifOrientation）
- [ ] `api/story.ts`：fetchStory + cache evict
- [ ] `ConstellationView.vue`：列表 + 详情双栏，复用 atlas 模式
- [ ] `ScanView.vue` 集成 StoryPanel + HEIC 提示 + **banner 切换**（`?mock=1` 或 health.astrometry === "mock"|"down"）
- [ ] `style/star-atlas.css` 新增 .story-panel / .atlas-grid / .heic-hint
- [ ] 测试：StarCanvas.animate（±2° 断言）/ StoryPanel / story.store

### 端到端
- [ ] 真实样图回归（误差 < 2px；Y_FLIP 已由 `scripts/wcs_regression.py` 锁定）
- [ ] HEIC 样图跑通（用 iPhone 拍摄的真 .heic，Orientation 6；服务端转正后 solver 看到正向像素）
- [ ] AI 故事生成（猎户 × 2 风格，每段 220-300 字；其余 4 星座图鉴可浏览）
- [ ] 全链路 PPT 截图（识别 → 故事 → 图鉴）

### 不入 M2（推 M3/M4）
- 观星指数 / 浏览器定位 / Open-Meteo / 月相 / Bortle
- 分享卡 / 海报导出
- 多语种 UI / 国际化
- 其余 4 星座的 WCS 投影（仅猎户覆盖，详见 §1 决策表"M2 覆盖范围"）

---

## 13. 排期与里程碑（8.24 – 8.28）

| Task | 日期 | 工时估算 | 关键交付 |
|---|---|---|---|
| T1: astrometry 策略层 + WCS | 8.24 | 8h | services/astrometry.py + SolveSlot + project_stars + bayer_index + wcs_regression 锁定 Y_FLIP |
| T2: 并发 + 失败映射 + HEIC + exif_transpose | 8.25 | 4h | SolveSlot 集成 + 上游映射 + pillow-heif + normalize_image（JPEG 透传 bug 已修）|
| T3: AI provider + 故事接口 | 8.25-26 | 6h | ai_provider.py + story_fallback + story router + LRU 缓存（不缓存 degraded:true）|
| T4: Canvas 描出 + 闪烁 + atlas 缓回旋 | 8.26 | 5h | StarCanvas.vue 升级 + animate test（atlas ±2° sin）|
| T5: StoryPanel + storyStore | 8.26-27 | 4h | StoryPanel.vue + storyStore（含 Cache-Bust:1）+ scanStore 仅 selectedStyle |
| T6: 星座图鉴完整页 | 8.27 | 4h | ConstellationView.vue + atlasStore |
| T7: HEIC 提示 + utils/exif 可选状态 | 8.27 | 0.5h | utils/exif.ts 可选提示（不写 8 向矩阵）+ ScanView 集成 |
| T8: 端到端回归 + 演示数据 | 8.28 | 4h | 猎户 8 星真解回归（误差 < 2px）+ HEIC 样图 + 5 星座 × 2 风格故事 + 截图 |

**风险缓冲：** 8.28 下午为回归与录屏窗口；如 T3 延迟，AI 故事降级为纯 preset，不阻塞主链路演示。

---

## 14. 风险与对策（v0.6.1 更新：删 exif.ts 8 向矩阵测试；新增 Orientation 6 JPEG 风险）

| 风险 | 影响 | 对策 |
|---|---|---|
| 上游 astrometry 服务不稳定 | 主链路翻车 | T1 早期验证 `/api/health`；不可达时切回 fixture（`ASTROMETRY_MOCK=1` 显式开关）|
| astropy 安装复杂 / 体积大 | 后端部署困难 | 仅装 astropy + pillow-heif；不用完整 scipy |
| 真实解算坐标与 fixture 漂移 > 2px | M2 验收失败 | fixture 与真实解算并存；`scripts/wcs_regression.py` 用 `max(diffs)` 锁定 Y_FLIP 常量 |
| WCS API 用错（如 `WCS(wcs_header_dict=...)`）| 实施翻车 | §4.2 正文已锁定正确写法：`WCS(fits.Header(...))` + `SkyCoord` + `world_to_pixel(sky)` |
| Y 翻转猜错（赌 CTYPE）| overlay 整体颠倒 | §4.2 正文 + §16.1.2 回归脚本锁定 Y_FLIP；禁止运行时探测 |
| SolveSlot `_queued` 在客户端断开时泄漏 | 用户反复点"开始识别"后排队错乱 | §4.3 `try/finally + queued 标志位` 兜底 |
| crop 后 WCS 在裁切坐标系（不补偿偏移）| 星点堆在原图中心 | §4.5 crop 顺序写死：裁切坐标 → `+= (crop_x0, crop_y0)` → 原图 height Y_FLIP |
| Orientation 6/8 JPEG（iPhone 竖拍）solver 看到未旋转像素 | overlay 偏 90° | §9.1 `normalize_image` 用 `changed = transposed is not img` 判定；Orientation ≠ 1 一律重编码 |
| 504 无 JSON → 前端 `r.json()` 解析失败 | 误报 FETCH_ERROR | §4.4 代理超时改 200 + `{ok:false, code:"TIMEOUT"}` |
| `?mock=1` banner 真引擎下未拆 | 演示穿帮 | §16.2.2 banner 仅 `?mock=1` 或 health.astrometry === "mock"|"down" 时挂 |
| AI 故事 token 消耗大 | 评审演示成本 | 10 分钟 LRU 缓存 + 预设兜底；**不缓存 degraded:true**；演示一次后所有命中缓存 |
| DeepSeek / 盘古 Key 配置遗漏 | 部署后故事模块失效 | DisabledProvider + preset degraded:true（**非 503**）；README 写清 Key 注入步骤 |
| 8.24–8.28 仅 5 天，工期紧 | T 延迟 | T3 AI 故事降级为纯 preset 可独立验收；T7 已缩到 0.5h |

---

## 15. 与 M1 spec 的差异

本章列 M2 spec 与 M1 spec v0.5 的变更点（仅作索引，不重复 M1 内容）：

- §3.0 外部依赖：M1 仅声明 mock；M2 §4 展开真实策略层 + 失败映射
- §3.1 POST /api/identify/solve：M1 返回 fixture；M2 §3.1 真实求解 + HEIC + 新失败码
- §3.2 GET /api/constellation/{abbr}：M1+M2 不变
- §3.3 POST /api/story：M1 未有；M2 新增
- §3.4 GET /api/constellations：M1 未有；M2 新增
- §3.5 GET /api/health：M1 未实现（README 占位）；M2 新建（astrometry: up\|mock\|down / ai_provider: up\|disabled\|down）
- §6.1 双模式：M1 overlay 静态终态；M2 §6.1 描出 + 闪烁 + §6.2 atlas 缓旋转
- §6.2 性能：M1 仅占位；M2 §6.4 新增 IntersectionObserver / visible 暂停
- §7 M1 交付清单：M2 §12 重写 M2 交付清单；M1/M2 边界表移至 §0.4
- §10 星座数据规格：M1 单源约定不变；M2 新增 bayer_index.json / preset_stories.json

---

> **下一步：** M2 spec 审查通过后，按 T1–T8 顺序产出 `docs/plans/2026-08-24-starwhisper-m2-impl.md` 实施计划（task-by-task 形式，沿用 M1 plan 的 checkbox 风格），每 task 配测试与 commit 策略。

---

## 16. v0.6.1 修订日志（2026-08-23）

> **同步声明：** 本节提出的 7 项 P0 + 14 项 P1 修订，已全部并入 M2 spec 正文（§4.2 / §4.3 / §4.5 / §6.2 / §6.5 / §9 / §11.1 / §0.2 / §1 / §2 / §10 / §13）；本节作为变更日志保留，正文不再与之冲突。后续 §16.1.x 给出"已落地"的最终代码与判定细节。

> 范围不动（§0–§3、§5、§7、§8、§12、§14 保留）；本节修订 §4 策略层 / §6 Canvas / §9 HEIC-EXIF / §11 store 归属 / §10 / §13 排期；M2 实施前必须吃透本节。

### 16.1 P0：会把主链路做反（7 项）

#### 16.1.1 §4.2 WCS 投影 API 错误

**问题：** 原 spec 写的 `WCS(wcs_header_dict=wcs_header)` 与 `wcs.world_to_pixel(ra, dec)` 均不存在。

**修订：**

```python
# server/services/astrometry.py
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u

def project_stars(wcs_header: dict, image_height: int, y_flip: bool) -> list[dict]:
    """y_flip 由 orion.jpg 真解回归判定（见 §16.1.2）"""
    wcs = WCS(fits.Header(wcs_header))  # 上游 wcs_header 是 dict[str,str]，先转 Header
    out: list[dict] = []
    for entry in _BAYER_INDEX.values():
        sky = SkyCoord(ra=entry["ra"] * u.deg, dec=entry["dec"] * u.deg, frame="icrs")
        x, y = wcs.world_to_pixel(sky)       # astropy ≥ 5.0 已 0-based，禁止再 -1
        pixel_x = round(float(x), 2)        # 保留 2 位亚像素精度
        pixel_y = round(float(y), 2)
        if y_flip:
            pixel_y = image_height - 1 - pixel_y
        out.append({
            "bayer": entry["bayer"], "name": entry["name"],
            "magnitude": entry["magnitude"],
            "pixel_x": pixel_x, "pixel_y": pixel_y,
            "constellation": entry["abbr"],
        })
    return out
```

#### 16.1.2 §4.2 Y 翻转判定逻辑

**问题：** 原 spec 注释"CTYPE2=DEC 所以不翻 Y"——CTYPE 是天球轴，不是像素 Y。FITS 像素 Y 朝上、Canvas/PIL 朝下；不翻则上下颠倒。

**修订：** **不赌 CTYPE**。在 `services/astrometry.py` 加 `Y_FLIP` 配置项，由 orion.jpg 真解回归脚本判定（首次跑解算 → 与手工点过的 fixture 比对 → 整体颠倒则 `Y_FLIP = True`，误差 < 2px 即可锁定）。回归脚本：

```python
# scripts/wcs_regression.py
def lock_y_flip(solved_stars, fixture_stars, img_h, tol_px=2):
    """用 max(diffs) 判定 Y_FLIP，单颗星碰巧靠近中心也会触发翻转分支"""
    diffs_no_flip = [euclid(s, f) for s, f in zip(solved_stars, fixture_stars)]
    diffs_flip    = [euclid((s.x, img_h-1-s.y), f) for s, f in zip(solved_stars, fixture_stars)]
    if max(diffs_no_flip) < tol_px:
        return False  # 不翻
    if max(diffs_flip) < tol_px:
        return True   # 要翻
    raise RegressionError(
        f"两种朝向都不匹配: no_flip_max={max(diffs_no_flip):.1f}px, "
        f"flip_max={max(diffs_flip):.1f}px, tol={tol_px}px"
    )
# ★ Y_FLIP 锁定后写入 services/astrometry.py 模块常量，禁止每次请求探测
```

#### 16.1.3 §3 数据源：bayer_index.json 必须手写

**问题：** 原 spec 写"bayer_index.json 从 constellations.json 生成"——后者只有 viewBox x/y (640×460)，没有 RA/Dec；WCS 输入必须是 ICRS J2000。

**修订：** `data/bayer_index.json` 由 BSC/HYG 摘录猎户 8 星 J2000 ICRS RA/Dec，禁止"自动生成"。与 `constellations.json` 用 **Bayer 字符串** 对齐；CI 比对两边 Bayer 集合相等，缺一颗即挂。

**附录 A：猎户 8 星 ICRS J2000 RA/Dec（精度 4 位小数度）**

| Bayer | 中文名 | RA (deg) | Dec (deg) | mag |
|---|---|---|---|---|
| Alpha Ori | 参宿四（Betelgeuse） | 88.7929 | +7.4071 | 0.42 |
| Gamma Ori | 参宿五（Bellatrix） | 81.2829 | +6.3497 | 1.64 |
| Lambda Ori | 觜宿一（Meissa） | 83.7846 | +9.9342 | 3.39 |
| Zeta Ori | 参宿一（Alnitak） | 85.1896 | -1.9428 | 1.74 |
| Epsilon Ori | 参宿二（Alnilam） | 84.0533 | -1.2019 | 1.69 |
| Delta Ori | 参宿三（Mintaka） | 83.0017 | -0.2991 | 2.23 |
| Kappa Ori | 参宿六（Saiph） | 86.9392 | -9.6696 | 2.06 |
| Beta Ori | 参宿七（Rigel） | 78.6346 | -8.2017 | 0.13 |

其余 4 星座（cyg/sco/leo/and）首期仅做图鉴浏览（spec §8），暂不纳入 WCS 投影；M2.5 再补 RA/Dec。

#### 16.1.4 §4.3 Semaphore 按用户请求计

**问题：** race 内部 3 路 httpx 都 `acquire_slot()` 会让单用户占满整机；`_SEMAPHORE._waiters` 是私有字段（Python 版本差异可能为 None），check-then-acquire 有竞态。

**修订：**

```python
class SolveSlot:
    """用户请求级信号量；race/crop 内部不再 acquire"""
    def __init__(self, max_active: int = 3, max_queue: int = 5):
        self._sem = asyncio.Semaphore(max_active)
        self._active = 0
        self._queued = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        async with self._lock:
            if self._active >= 3 and self._queued >= 5:
                raise BusyError()
            self._queued += 1
        try:
            await self._sem.acquire()
            async with self._lock:
                self._queued -= 1
                self._active += 1
            try:
                yield
            finally:
                async with self._lock:
                    self._active -= 1
                self._sem.release()
        except BusyError:
            async with self._lock:
                self._queued -= 1
            raise

_SLOT = SolveSlot(max_active=3, max_queue=5)
```

race 的 3 个 httpx 调用不再 `async with _SLOT.acquire()`，仅外层 `solve()` 入口取一槽。

#### 16.1.5 §4.1 crop 后 WCS 偏移

**问题：** center-crop 1/2 后 WCS 在裁切坐标系；不补偿则星点堆在原图中心。

**修订：**

```python
async def solve_with_crop(image_bytes: bytes, full_w: int, full_h: int):
    """center-crop 1/2 后解算，WCS 像素坐标加偏移回到原图坐标系

    顺序写死（v0.6.1）：
    1. 在裁切坐标系中做 world_to_pixel（裁切图尺寸 = crop_w × crop_h）
    2. += (crop_x0, crop_y0) 回到原图坐标系
    3. 再用 原图 height 做 Y_FLIP 校正（不要在 crop 高度上先翻再加偏移）
    """
    crop_w, crop_h = full_w // 2, full_h // 2
    crop_x0 = (full_w - crop_w) // 2
    crop_y0 = (full_h - crop_h) // 2
    cropped = crop_center(image_bytes, crop_x0, crop_y0, crop_w, crop_h)
    result = await _solve_internal(cropped)
    if not result.solved:
        return None
    for star in result.stars:
        star.pixel_x = round(star.pixel_x + crop_x0, 2)   # [2] 加偏移回原图
        star.pixel_y = round(star.pixel_y + crop_y0, 2)   # [2] 加偏移回原图
        # [3] Y_FLIP 用原图 height（在 §4.2 project_stars 内统一处理）
    return result
```

#### 16.1.6 §9 EXIF 服务端正向化（删前端双层旋转）

**问题：** 现代浏览器对 JPEG `<img>` 已按 EXIF Orientation 自动显示；前端再 CSS rotate + Canvas setTransform 会转两次。Orientation 6/8 写反。

**修订：服务端统一正向化，前端不旋转：**

```python
# server/routers/identify.py（v0.6.1 修复版，§9.1 已落地）
from PIL import Image, ImageOps

def normalize_image(content: bytes) -> tuple[bytes, int, int, int]:
    """v0.6.1 关键修复：

    - Orientation ≠ 1 的 JPEG 必须把转正后的图送上游（再编码 q95 可接受）
      否则浏览器按 EXIF 显示 + solver 看到未旋转像素 → overlay 偏 90°
    - Orientation 1 的 JPEG / PNG 原样透传（禁止压缩丢星，spec §8）
    - HEIC 一律转码为 JPEG（HEIF 格式 PIL 不直出，solver 只认 JPEG/PNG）
    """
    img = Image.open(BytesIO(content))
    transposed = ImageOps.exif_transpose(img)
    width, height = transposed.size
    # changed 判定：对象身份变化（Orientation ≠ 1 时 PIL 返回新对象）或格式是 HEIF
    changed = transposed is not img or img.format in ("HEIF", "HEIC")
    if changed:
        buf = BytesIO()
        transposed.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue(), 1, width, height
    # Orientation 1 的 JPEG/PNG 原样送上游，禁止压缩丢星
    return content, 1, *img.size
```

**前端退化：** `utils/exif.ts` 仅读 Orientation 用于提示（HEIC 拍摄通常 1，相册原图有 Orientation）；绘制层不再旋转。响应 `exif_orientation` 恒为 1，前端 ScanView 可省略该字段处理。

**T7 工时缩减：** 从 3h → 0.5h（仅写"读失败 → 1"的兜底 + ScanView 提示文案）。

#### 16.1.7 §4.5 FOV 预检前移

**问题：** solved:true 之后才校验 FOV，会浪费 16s 解算时间再被丢；无 EXIF 本来也不知道 FOV，事后否决毫无意义。

**修订：**

```python
async def solve(image_bytes: bytes, has_exif: bool, exif_fov: float | None):
    # [1] 格式校验 + 解码（§9.1 normalize_image）
    # [2] 取用户级槽位（§16.1.4 SolveSlot）
    # [3] /analyse；成功拿到 scale_hint 且 has_exif → step 4a
    # [3b] ★ FOV 预检：exif_fov 超出 [1.1°, 70°] → 立即 {ok:false, code:"FOV_OUT_OF_RANGE"}
    # [4a/b/c] 真实解算
    # [5] 解析响应
    # [6] ★ 已解出不再校验 FOV，直接接受
    # [7] 拼装 SolveResult
```

无 EXIF 不预检；解出来直接接受（含 79° 边缘命中场景）。

### 16.2 P0 产品（2 项）

#### 16.2.1 §6.2 atlas 缓回旋方向

**问题：** 原 spec 写 360°/12s 整周会让星座倒过来像屏保；M1 是 ±2° 缓回旋。

**修订：**

```typescript
// StarCanvas.vue atlas 模式（M2 改回 M1 决策）
const ROT_AMP_RAD = 2 * Math.PI / 180   // ±2°
const ROT_PERIOD_MS = 12000             // 12s/周
function atlasFrame(now: number) {
  const t = (now - startTs) / ROT_PERIOD_MS
  const theta = ROT_AMP_RAD * Math.sin(2 * Math.PI * t)
  ctx.save()
  ctx.translate(contentW / 2, contentH / 2)
  ctx.rotate(theta)
  ctx.translate(-contentW / 2, -contentH / 2)
  // ... 画网格 + 双同心圆 + 连线 + 星点
  ctx.restore()
  if (visible) rafId = requestAnimationFrame(atlasFrame)
}
```

#### 16.2.2 §6 ScanView 样图 banner 切换条件

**问题：** 真引擎接上后还挂着 M1 常驻 banner，演示直接穿帮。

**修订：banner 切换条件用前端可观测信号，禁止 `import { env }` 假装有 `ASTROMETRY_MOCK`：**

```typescript
// web/src/views/ScanView.vue（M2）
const route = useRoute()
const health = useHealthStore()

const showMockBanner = computed(() =>
  route.query.mock === '1' ||                            // 1. URL 显式 ?mock=1
  health.astrometry === 'mock' ||                        // 2a. 后端 mock 模式
  health.astrometry === 'down'                           // 2b. 上游 down
)
```

**后端 health 端点（M2 新建）：**

```python
# server/routers/health.py
@app.get("/api/health")
async def health():
    astrometry_state = "mock" if ASTROMETRY_MOCK else \
                       ("down" if not await _astrometry_health() else "up")
    ai_state = "disabled" if not os.getenv("AI_API_KEY") else \
               ("down" if not await _ai_health() else "up")
    return {
        "ok": True,
        "astrometry": astrometry_state,
        "ai_provider": ai_state,
        "ai_model": os.getenv("AI_MODEL", "deepseek-chat"),
    }
```

**前端 healthStore：** 启动时拉一次 `/api/health`，缓存 `astrometry` / `ai_provider` 字段；失败时默认 `"down"`。

### 16.3 P1 策略层与数据（7 项）

| # | 原 spec | 修订 |
|---|---|---|
| 1 | §4.1 race 三段 500-1500 / 1500-3500 / 3500-6000 | 补 <8° 长焦（60-500），对齐 `astrom_service.sh` 的 ranges：`60-500 / 500-1500 / 1500-3500 / 3500-6000` |
| 2 | §9.1 PNG 也被转 JPEG q95 | **只转 HEIC**；PNG/JPEG 原样送上游（禁止压缩丢星，与 spec §8 一致）|
| 3 | §9.2 "HEIC 默认无 EXIF" | 错。HEIC 相册原图有 Orientation；仅微信/截图剥 EXIF 才走 race |
| 4 | §3.1 image_width/height | 必须是 **送进 solve 那张图** 的尺寸，与 WCS NAXIS 一致 |
| 5 | §3.1 成功体示例 `pixel_x: 3421` | 标明「示意，非回归值」；fixture 用真 `world_to_pixel` |
| 6 | §4.4 504 无 JSON | 代理超时改返 200 `{ok:false, code:"TIMEOUT"}`；前端 `r.json()` 不会变 FETCH_ERROR |
| 7 | §3.5 GET /api/health "M1 不变" | 错。M1 main.py 未实现 health；M2 新建（M1 README 中的 `curl /api/health` 是占位）|

### 16.4 P1 AI 故事（5 项）

| # | 原 spec | 修订 |
|---|---|---|
| 1 | §5.1 DisabledProvider → 503 | health()=False、chat() 抛错；**上游不返 503**，preset 接管走 `degraded:true`；503 仅当 preset 文件缺失 |
| 2 | §5.2 `max_tokens: 600` | 改 `1000`（300 汉字 + 标题 + JSON 余量）|
| 3 | §5.4 超时 30s vs §10 20s | 统一 **30s**（前端 65s 内 30+20+15 余量）|
| 4 | §11.2 storyStore 缓存 | 增加 `Cache-Bust: 1` header 支持；**不缓存 `degraded:true`**（失败一次别让整场都是离线故事）|
| 5 | §11.1 scanStore `activeStory` | **删**。故事状态完全归 storyStore；scan 只留 `selectedStyle: 'myth' \| 'science'` |

### 16.5 P1 排期（1 项）

**§13 T1 fixture 回退显式化：** `ASTROMETRY_MOCK=1` 环境变量开关（不是"服务不行再想想"）；fixture 路径保持 `server/data/fixtures/solve_orion.json`，但前端 `/samples/solve_orion.json` 离线 mock 由 `?mock=1` URL 参数显式触发。

### 16.6 修订后的关键决策汇总

| 项 | v0.6 | v0.6.1 |
|---|---|---|
| WCS 构造 | `WCS(wcs_header_dict=...)` | `WCS(fits.Header(...))` |
| 星点投影输入 | `(ra, dec) float` | `SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")` |
| `world_to_pixel` 输出 | 1-based，再 -1 | 0-based，**不再减 1** |
| Y 翻转 | 注释"CTYPE 决定" | **回归脚本判定**（Y_FLIP 配置项）|
| bayer_index 来源 | "从 constellations 生成" | **手写 BSC/HYG** + 附录 8 星 |
| Semaphore 粒度 | 每路 httpx 都 acquire | **用户请求级**（race/crop 共一槽）|
| 排队判断 | `_SEMAPHORE._waiters` 私有字段 | **显式 active + queued 计数器** |
| Crop 偏移 | 无 | **pixel += (crop_x0, crop_y0)** |
| EXIF Orientation | 前端 CSS + Canvas 双层旋转 | **服务端 exif_transpose**，前端不转 |
| FOV 校验时机 | solved:true 之后 | **analyse 之后、solve 之前** |
| atlas 旋转 | 360°/12s 整周 | **±2° 缓回旋**（M1 决策延续）|
| 样图 banner | M1 常驻 | **`ASTROMETRY_MOCK=1` 或 ASTROMETRY_DOWN 时挂** |
| Race 范围 | 3 段（漏长焦）| **4 段**（60-500 补齐）|
| 格式转码 | 全转 JPEG | **只 HEIC**；JPEG/PNG 原样 |
| storyStore 缓存 | 所有结果都缓存 | **不缓存 degraded:true** |
| scanStore 状态 | 含 activeStory | **删**；归 storyStore |
| max_tokens | 600 | **1000** |
| AI 超时 | 30s / 20s 不一致 | **统一 30s** |
| 504 处理 | 504 无 JSON | **200 + {ok:false, code:TIMEOUT}** |
| /api/health | "M1 不变" | **M2 新建** |

### 16.7 与 v0.5 章节的交叉引用

- §4.1 → §16.1.4（Semaphore）+ §16.5（race 4 段）
- §4.2 → §16.1.1（WCS API）+ §16.1.2（Y 翻转）+ §16.1.3（bayer_index 附录 A）
- §4.5 → §16.1.7（FOV 前移）
- §5.1 / §5.2 / §5.4 → §16.4（AI 故事 5 项）
- §6.2 → §16.2.1（atlas ±2°）
- §6 ScanView banner → §16.2.2（ASTROMETRY_MOCK 切换）
- §6.5 → §16.1.6（删前端双层旋转）
- §9.1 / §9.2 → §16.1.6（服务端 exif_transpose）+ §16.3（HEIC 不一定无 EXIF）
- §3.1 → §16.3（image 尺寸 + 示例标注）
- §3.5 → §16.3（health 新建）
- §4.4 → §16.3（504 → 200 TIMEOUT）
- §11.1 → §16.4（删 activeStory）

### 16.8 v0.6.1 同步状态（2026-08-23 同步完成）

| 修订点 | 同步位置 |
|---|---|
| WCS API（`WCS(fits.Header(...))` + `SkyCoord` + `world_to_pixel(sky)`）| §4.2 正文 |
| Y_FLIP 回归脚本（`max(diffs)` 判定）| §4.2 正文 + §16.1.2 同步代码 |
| bayer_index 附录 A（猎户 8 星 ICRS J2000 RA/Dec）| §16.1.3 |
| SolveSlot 类（用户请求级 `active + queued`）| §4.3 正文 |
| SolveSlot try/finally 防 `_queued` 泄漏 | §4.3 正文 |
| crop 顺序写死（裁切坐标 → 加偏移 → 原图 height Y_FLIP）| §4.5 + §16.1.5 同步 |
| FOV 预检前移（analyse 之后、solve 之前）| §4.5 正文 |
| atlas 缓回旋（±2° sin）| §6.2 正文 |
| 样图 banner 切换（`?mock=1` + `/api/health` 的 `astrometry` 字段）| §1 决策表 + §16.2.2 同步 |
| normalize_image JPEG 透传 bug 修复（`changed` 判定）| §9.1 正文 + §16.1.6 同步 |
| scanStore 收敛（删 `activeStory` / `storyLoading` / `exifOrientation`）| §11.1 正文 |
| T7 工时 3h → 0.5h | §13 排期 |
| race 4 段（补 60-500 长焦）| §1 决策表 |
| 只转 HEIC（PNG/JPEG 原样）| §9.1 正文 |
| HEIC 不一定无 EXIF | §9.2 正文 |
| image 尺寸对齐 NAXIS | §9.1 正文 |
| 示例 pixel_x 标"示意" | §3.1 正文（标注） |
| 504 → 200 + `{ok:false, code:"TIMEOUT"}` | §10 异常表 |
| /api/health M2 新建（非"M1 不变"）| §1 决策表 + §16.2.2 同步 |
| DisabledProvider 走 preset degraded:true（非 503）| §16.4 决策表 |
| max_tokens 600 → 1000 | §1 决策表 |
| AI 超时统一 30s | §1 决策表 |
| storyStore 不缓存 degraded:true + Cache-Bust:1 | §11.2 正文 + §2 文件结构 |
| 4 段 race 单用户 4 核打满 → 接受演示期单用户 | §13 风险 |

> **T1 开工前必做：** 跑 `scripts/wcs_regression.py` 锁定 `Y_FLIP` 常量（写入 `services/astrometry.py` 模块顶部），再写后续代码。

> **下一步（v0.6.1 同步后）：** 按 T1–T8 出 `docs/plans/2026-08-24-starwhisper-m2-impl.md`。