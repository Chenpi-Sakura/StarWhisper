# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目一句话

StarWhisper（星语天象）—— 拍照识星座 + 星座动起来 + AI 讲神话。2026 华为云 OPC 创意大赛参赛作品。**当前里程碑：M2（真实解算 + AI 故事 + atlas 多 tradition 落地）**。

详细 spec 见 `docs/specs/`，实施计划见 `docs/plans/`，项目背景见 `docs/PROJECT_BRIEF.md`。

---

## 外部服务依赖（硬依赖，先读这段）

**StarWhisper 无法独立运行。** 识图主链路（`POST /api/identify/solve`）必须有一个自建的 astrometry 求解服务在线，它**不在本仓库内**，是另外两个仓库：

```
StarWhisper (:8000)
    └─ HTTP → astrometry-api-server (:8010)     /root/Projects/astrometry/astrometry-api-server
                 └─ go.mod replace → astrometry-go-client   /root/Projects/astrometry/astrometry-go-client
                          └─ exec solve-field → astrometry.net 0.98 + 4100 索引（12 个，339M）
```

| 仓库 | 地址 |
|---|---|
| astrometry-api-server | `git@gitcode.com:chenpi_1/astrometry-api-server.git` |
| astrometry-go-client | `git@gitcode.com:chenpi_1/astrometry-go-client.git` |

两个仓库必须**同级放置**（server 的 `go.mod` 用相对路径 `replace => ../astrometry-go-client`）。

**⚠️ 关键事实：`GET /api/health` 的 `astrometry` 字段只看配置**（`ASTROMETRY_MOCK` 真假），
**不探测上游真实连通性**（见 `server/routers/health.py` 的 docstring）。
解算服务全挂时 StarWhisper 依然返回 `ok: true, astrometry: up`。**别拿它判断依赖死活。**

判断依赖是否真的可用，用体检脚本：

```bash
bash scripts/check_deps.sh          # 识图依赖缺任一项 → exit 1
bash scripts/check_deps.sh --quiet  # 只报失败项
```

它会真探测：服务通不通、跑的是哪份 commit、解算器是不是 0.98（**不是 apt 的 0.93**）、
索引齐不齐、tmux 托管是否还在。`scripts/deploy.sh` 的预检会调它，**依赖不通直接中止部署**。

启停解算服务（不在本仓库）：

```bash
cd /root/Projects/astrometry
./astrom_service.sh status    # 状态
./astrom_service.sh deploy    # 改了解算服务代码后：测试 → 编译 → 重启
./astrom_service.sh verify    # 完整健康检查 + 端到端冒烟解算
```

> 2026-10-06 变更：解算服务已**彻底去 Docker 化**（解算器 0.98 直接跑在宿主机 `/opt/astrometry/0.98/`，
> 进程由 tmux 会话 `astrometry-api` 托管），路径也从 `/root/service/` 迁到了 `/root/Projects/astrometry/`。
> 详见 `docs/EXTERNAL_DEPS.md` 与 `/root/Projects/astrometry/docs/README.md`。

---

## 仓库布局

```
server/                  FastAPI + Python 3.11+ + pytest
  main.py                入口；routers + CORS + traditions 启动加载
  config.py              .env 自动加载 + ASTROMETRY_SERVICE_URL / MOCK 开关 / 超时
  routers/               路由层（HTTP 边界）
    identify.py          POST /api/identify/solve（核心：JPEG 重压 + 上游解算 + 失败映射）
    story.py             AI 故事流式接口
    artwork.py           POST /api/artwork（起 job）+ GET /api/artwork/{id}（轮询）
    traditions.py        /api/traditions 多 tradition 数据
    health.py            /api/health（astrometry + ai_provider 状态）
    constellation.py     /api/constellation/{abbr}
    constellations.py    /api/constellations
  services/              业务逻辑层（无 FastAPI 依赖，方便单测）
    astrometry.py        WCS 投影（astropy）
    traditions.py        多 tradition 星表 + find_nearest + build_star_catalog
    jpeg_recompress.py   公网 ≤4MB 约束的服务端 PIL libjpeg 自适应重压
    ai_provider.py       OpenAI 兼容 + AgentArts 双 provider（含真流式 SSE）
    story_fallback.py    AI 不可用时的离线预设（按 tradition 取 traditions 内嵌 brief）
    constellation.py     星座详情
    weather.py           Open-Meteo 观星指数四档（优/良/一般/差）
    image_prompt.py      星纹 prompt 模板（定稿结构：故事在前、规则在后）
    image_gen.py         MiniMax 文生图 client + 进程内 job 表（闸门/熔断/缓存/mock）
  data/                  traditions/{western,chinese}/<abbr>.json + fixtures
  tests/                 pytest（214 个用例：identify + jpeg_recompress + traditions
                         + story + index/astro 时刻 — story 覆盖 P0/P1/P2 全部修复路径）

web/                     Vue 3 + Vite + TS + Pinia + vitest + jsdom
  scripts/gen-cities.mjs 生成 public/data/cn-cities.json（DataV 行政区划，`pnpm gen:cities`，一次联网）
  public/data/           运行时按需 fetch 的静态数据（cn-cities.json：3237 条省/市/区县前缀表）
  src/
    stores/              scan / atlas / story（fetchStoryStream 真 SSE）/ stargaze / toast
                         / artwork（星纹 job 轮询状态机）
    views/               ScanView / ConstellationView / IndexView（观星指数）
    components/          StarCanvas（overlay + atlas 三模式）/ StoryPanel / ArtworkPanel
                         / SampleStrip（样图速测）
                         / AtlasStoryStatic / AtlasTraditionTabs
                         / index（IndexGauge/TrendBars/MoonCard/CitySearch）
                         / common（PlateBox/StarBtn/StarChip）
    data/                samples.ts（样图速测元数据：视场/体积/预计耗时/预期命中）
    api/                 solve.ts / story.ts（streamStory）/ health.ts / atlas.ts
                         / stargaze.ts / geocoding.ts（在线兜底，限 countryCode=CN）
    utils/               exif / heic / stargazeRange（区间选择）/ cityTrie（中文城市前缀树）
  public/samples/        离线 mock fixture + 样图 + 样图速测素材（quick-test{1,2}{,-thumb}.jpg，
                         由 scripts/prepare_quick_samples.py 生成）
  tests/                 vitest（279 个用例，覆盖 store/router/组件/数据产物四类）
```

---

## 常用命令

### 后端

```bash
# 一次性依赖（已有 .venv）
server/.venv/Scripts/python.exe -m pip install -r server/requirements.txt
# piexif 是测试用额外依赖（test_jpeg_recompress.py 用到）
server/.venv/Scripts/python.exe -m pip install piexif

# 全部测试
cd server && .venv/Scripts/python.exe -m pytest -q

# 单个测试
cd server && .venv/Scripts/python.exe -m pytest tests/test_jpeg_recompress.py -v
cd server && .venv/Scripts/python.exe -m pytest tests/test_identify.py::test_oversize_jpeg_is_recompressed_for_upstream -v

# 启服务（mock 模式，跳真实上游）
cd server && ASTROMETRY_MOCK=1 .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 启服务（真实上游 117.72.38.57:8010）
cd server && .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 健康检查
curl http://127.0.0.1:8000/api/health
```

### 前端

```bash
cd web
pnpm install
pnpm test                # vitest run（279 个用例）
pnpm test -- utils.exif  # 跑文件名包含 utils.exif 的
pnpm dev                 # :5173（已配 /api 代理到 :8000）
pnpm gen:cities          # 重新生成中国城市前缀数据（一次联网，改城市表时才需要）
pnpm build               # vue-tsc --noEmit + vite build
```

---

## 关键架构事实

### 上游调用模型

`server/routers/identify.py` 是 thin proxy：
- 接到 multipart → 校验 20MB / 格式
- **JPEG + >4MB → `services/jpeg_recompress.py` 重压**（PNG 透传，JPEG 失败兜底保留原图）
- POST 给 `ASTROMETRY_SERVICE_URL/solve`（默认 `http://117.72.38.57:8010`）
- 把上游 `solved/ra/dec/wcs_header` 组装成 spec §3.1 的 SolveResult
- 失败映射：超时 → 200 TIMEOUT，4xx → 200 UPSTREAM_BAD_REQUEST（透传 status + body 前 200 字符），连接失败 → 502 ASTROMETRY_DOWN，未解出 → 200 SOLVE_FAILED

**`docs/API.md` 是上游接口的事实源**——所有上游字段含义、`solved` 业务判断标准、4MB 限制根因都在那里。修改前先读。

### 公网 4MB 约束（必读）

`docs/API.md §1 关键约束 1`：公网 `117.72.38.57:8010` ≤4MB 成功，≥5MB 失败（HTTP 400 "Failed to parse form"）。根因是上行带宽 ~530KB/s × 10s timeout ≈ 5MB 临界。

由 `server/services/jpeg_recompress.py` 服务端保障（不靠 web 端压缩）：
- PIL libjpeg 自适应降级 `[q90, q85, q80]`，硬下限 q70
- 不 resize（丢 81% 星点）、不压 PNG/FITS（破坏像素）、保留 EXIF（含 APP1 marker，丢 FocalLength 会让上游走 race 路径慢 2-3×）
- 12 个单测在 `tests/test_jpeg_recompress.py` 守护

**不要在 web 端尝试压缩 JPEG**——之前实测试过：canvas Skia 与 mozjpeg-wasm 与 native libjpeg 在 chroma quantization / DCT 实现上有像素细节差异，相机长焦大图（test1 D610 MPO、test2 50MP）即便 EXIF 完整保留，astrometry.net source extractor 仍会拒绝（实测 canvas q80-q95 全 SOLVE_FAILED，PIL q70-q95 全成功）。

### EXIF Orientation 流程

`docs/API.md` 强调：上游用 raw bytes 解算，坐标系是 raw 像素。浏览器 `<img>` 自动按 EXIF 转正显示 → canvas 看到的是显示坐标系。
- 前端 `web/src/utils/exif.ts` 读 EXIF Orientation → 随 FormData 传 `orientation` 字段
- 后端 `server/routers/identify.py` 的 `_apply_exif_orientation` 按 8 种矩阵把上游 raw 坐标变换到显示坐标系
- `image_width/height` 也按 orientation 5/6/7/8 对调

### Tradition 反查

`server/services/traditions.py` 是多 tradition 星表（western + chinese）的统一入口：
- `build_star_catalog()` 返回去重后的合并星表
- `find_nearest(ra, dec, max_sep_deg, top_k)` 用 astropy SkyCoord 球面距离反查
- 命中星座（距离最近）作为 `constellations[0]`，包含 `tradition` / `abbr` / `name` / `latin` / `confidence` / `visible_stars`

### 城市搜索（观星指数页）

分两层，**本地优先**：
- `web/src/utils/cityTrie.ts`：中文城市前缀树（省/地级市/区县 3237 条），数据来自
  `web/public/data/cn-cities.json`（`pnpm gen:cities` 生成），首次聚焦搜索框才 fetch
- 本地 0 命中且输入 ≥2 字 → `api/geocoding.ts` 在线兜底（限 `countryCode=CN`，覆盖镇/景区如「冷湖」）
- UI 是自绘下拉 `components/index/CitySearch.vue`（不用 `<datalist>`）：「查阅」取高亮项或首条

### AI 故事流

**photo-level 故事（ScanView）**：
- `POST /api/story`：接 photo-level context（constellations[] + bright_stars[] + center + field + capture）
- `bright_stars` 与 atlas 路径一样受 `STORY_PROMPT_MAX_STARS` 截断（按星等取最亮 N 颗）。
  漏截断时实测 79°×59° 广域图会把 1709 颗星全塞进 prompt（user_content 174KB → 截断后 1.8KB）
- `capture` 来自前端 EXIF：`captured_at`（`YYYY-MM-DD HH:MM`）+ `place`（区县级地名）。
  原始经纬度**不出浏览器**——`utils/place.ts` 用 cn-cities.json 反查成地名才进 prompt；
  后端 `_PhotoCapture` 对两个字段做形态白名单，不合规即丢弃（不 422）
- 触发：scanStore.solveId 变化（每次新解算自动讲一次）
- 切 chip（activeAbbr）不影响 story
- 风格：myth / science（user content 携带 style，单一 AgentArts prompt）
- 不提供 fallback：AI 失败 → SSE `event:error`，UI 错误态
- 缓存：sha1(canonical_json({context, style, lang}))[:16]，TTL 10min
- 提示词：`docs/prompts/story-photo.md`（用户粘贴到 AgentArts 后台）

**atlas 故事（ConstellationView 详情页）**：
- `POST /api/atlas-story`：保留原 `/api/story` 语义
- 触发：ConstellationView 详情页加载
- 风格：myth / science
- 保留 preset degraded fallback（atlas 体验需要降级兜底）
- 缓存：`(tradition, abbr, style)` 三维，TTL 10min

### 星纹配图（AI 文生图）

`POST /api/artwork` 接故事正文 → 立即返回 `job_id`；`GET /api/artwork/{id}` 轮询到
`ready/error`。**必须走 job 而不是同步返回**：MiniMax `/v1/image_generation` 是同步
接口且没有异步任务查询端点，实测单次 32–38s，挂在 HTTP 上会占住 worker 几十秒，
连带拖慢故事与观星指数（单机只有一个事件循环）。触发点在 `ArtworkPanel.vue`：
故事流跑完才发起（prompt 的内容就是这段故事），指纹去重避免重复烧钱。

三条不可回退的事实（都是实测出来的）：

1. **图生图这条路不存在。** `subject_reference[].type` 只有 `character`（人像）一个取值，
   语义是「身份注入」而非「图像改写」，没有 strength/denoise 任何权重参数。实测把真实
   星空照当参考喂进去，输出星位全变；同 seed 加/不加参考的平均像素差仅 5.43/255，
   低于两次随机生成之间 11.9 的一半。所以「把用户这张照片变生动」用这个接口做不到。
2. **prompt 结构是五臂对照实验选出来的**（见 `services/image_prompt.py` 模块注释）：
   故事正文放最前、【画风】/【画面性质】/【严禁】压在后。模型对最后读到的内容权重最高，
   而故事点名十几个星名会持续把画面拽向「带标注的星图」。正面表述是**加法**，删掉禁令
   会让连线更多。
3. **方差是固有属性，靠拒绝采样而不是调措辞解决。** 最优臂单张干净率实测约 1/4，
   所以 `IMAGE_GEN_N=4` 一次出多张让用户挑（¥0.025/张，至少一张干净 ≈ 99%）。
4. **`n` 不影响耗时，但分辨率影响。** 同 prompt 实测 n=1 三次 32.8/33.6/32.6s，
   n=4 三次 32.9/34.3/61.0s——上游内部并行出图，约 33s 是固定往返。**不要**为了
   "省时间"把 n 调小，那是纯亏（时间不变、命中率从 99% 掉回 25%）。耗时跟**像素数**
   走：1024² ≈33s、1280×720 ≈20s、1920×1080 ≈35s。
5. **出图尺寸默认 1920×1080，不是 `aspect_ratio` 预设。** `aspect_ratio=16:9` 上游只给
   1280×720，铺成整页底纹会发糊；`image-01` 支持显式 `width`/`height`（[512,2048] 且 8
   的倍数），1920×1080 与旧的 1024×1024 耗时持平而像素翻倍。`IMAGE_GEN_WIDTH/HEIGHT`
   任一为 0 才退回 `IMAGE_GEN_ASPECT`。曾硬编码 `aspect_ratio: "1:1"`，铺满页面后观感
   很差，`test_image_gen.py` 里有回归断言。
6. **上游 1026（内容审核）是偶发误判，不是文本的确定属性。** 一条完全干净的七夕
   故事（织女牛郎鹊桥）被拒，同一条 prompt 重打 10 次全部通过。因此
   `IMAGE_UNSAFE_CONTENT` 在 `image_gen._run()` 里：不计入熔断失败次数（它不是服务
   故障，否则连来三个敏感故事会让全站图片"暂时不可用" 60s），并静默重投一次。
   上游 `status_msg`（会点名被拒措辞）只进服务端日志，不进给前端的 message。

**星纹铺底的层级**：配图不画在图版内部，而是 `App.vue` 里 `.bg-art` 这一层
（`position: fixed; z-index: 0`，与 `.bg-atlas` 同层、DOM 在其后，故压在星图水印之上、
`.frame`(z 1) / `.masthead`(z 50) 之下），托盘浮在它上面。因此 `.scan-view.has-art
:deep(.plate)` 要把纸底从 `--paper-hi` 改成 `rgba(244,236,212,0.8)`——0.62 时黑夜空
会把托盘压成灰泥。底图用 `multiply` + `brightness(2.05)`：不先提亮，大片近黑的夜空
会把整页压暗到不可读。

**给 PlateBox 绑响应式 `:class` 会让整块图版消失。** `PlateBox` 在 `onMounted` 里
`root.classList.add('go')` 手动加类跑入场动画（`.anim{opacity:0}` → `.anim.go` 才可见）。
父组件若在它身上绑响应式 class，Vue 重写 `className` 时会把 `go` 抹掉，`opacity` 回到 0，
表现是"内容全没了但 DOM 还在"。响应式 class 只能绑在调用方自己的根元素上。
`tests/ScanView.test.ts` 里有这条回归测试。

另外：上游返回的是 **24 小时过期**的签名 URL，只能当场看/当场存，不能入库当素材地址；
画面不烧 `aigc_watermark`，改由 UI 固定标注「艺术演绎 · AI 生成，非科学星图」——
生成图必须与真实 overlay 视觉隔离，这是「知识准确性第一原则」的一部分。

---

## 测试基础设施

- 后端 214 测试：identify + jpeg_recompress + traditions + story (P0/P1/P2 全覆盖) + index/astro
- 前端 279 测试：jsdom + setup polyfill（URL.createObjectURL）；含城市数据产物校验与搜索交互
- e2e：test1/test2/test3 三张真实星图（`assets/test*.jpg`），test1 是 D610 MPO 24MP 长焦样图

### 样图速测（ScanView idle / error 态）

评审与测试者手边常没有星图，故把两张**已实测可解算**的真实星图挂到识别页旁边，点一下即
= 选图 + 解算。链路要点：

- 素材由 `scripts/prepare_quick_samples.py` 生成，**直接 import 服务端生产函数**
  `services.jpeg_recompress.recompress_jpeg_to_target`（同 4MB target / 同 q90→q85→q80 阶梯 /
  同保留 EXIF）。因此样图与"用户上传原图经服务端重压后发给上游"的产物等价，
  **不存在样图专用后门**：前端仍照常读 EXIF Orientation 并传 `orientation` 字段。
- 全尺寸 `quick-testN.jpg` 参与解算；`quick-testN-thumb.jpg`（480px，已 exif_transpose 转正）
  仅供列表展示，绝不用作上传源。
- 2026-09-14 真实上游实测：test1 19.9s / test2 13.0s。**不要拿视场 >40° 且星点稀疏的图当样图**
  （曾用 test4 广域 54°×36°，上游 51.3s 已贴近 `ASTROMETRY_TIMEOUT=60`，演示体验差，已移除）。
- `web/tests/quickSamples.test.ts` 读磁盘校验素材完整性（存在 / JPEG magic / ≤4MB /
  元数据 size 文案与真实体积一致）——重压或换图后须重跑脚本，否则该测试会红。

### 故事组件关键事实（P0/P1/P2 之后）

- `POST /api/story/stream` 是唯一生产前端走的接口，`POST /api/story` 非流式保留向后兼容
- 端到端总时长预算：`STORY_TOTAL_TIMEOUT`（默认 45s）；前端 `STORY_STREAM_TIMEOUT_MS`（60s 兜底）
- 流式降级流程：AI 失败 → 先发 `reset` 清空半截内容 → 再 yield preset 全量
- 缓存三维 key：`(tradition, abbr, style)`；degraded:true 不写缓存
- 熔断（`STORY_CB_THRESHOLD` 连续失败 + `STORY_CB_COOLDOWN`）：冷却期内直接 preset 跳过 AI
- 限流（`STORY_RATE_LIMIT`/WINDOW 按客户端 IP）：超限返 429 `RATE_LIMITED`
- 调试期产物：报告 `docs/fix-notes/2026-09-03-story-component-review.md`

跑单个 e2e 验证（需启真实上游）：
```bash
cd server && .venv/Scripts/python.exe -m uvicorn main:app --port 8000 &
curl -s -X POST -F "image=@assets/test1.jpg" http://127.0.0.1:8000/api/identify/solve
```

---

## 关键设计文档指针

| 文档 | 何时读 |
|---|---|
| `docs/API.md` | 改 identify / 上游调用 / 4MB 约束时 |
| `docs/EXTERNAL_DEPS.md` | 改依赖部署形态 / 解算服务不可用 / 换机器时（先读）|
| `docs/specs/2026-08-21-starwhisper-design.md` | 整体产品设计 |
| `docs/specs/2026-08-23-starwhisper-design-m2.md` | M2 增量设计 |
| `docs/specs/2026-08-25-atlas-tradition-design.md` | tradition 多源星表设计 |
| `docs/plans/2026-08-24-starwhisper-m2-impl.md` | M2 实施计划 |
| `docs/PROJECT_BRIEF.md` | 产品背景 + 评分口径 |
| `docs/plans/2026-09-12-city-search-trie.md` | 改城市搜索 / 城市数据 / 前缀树时 |
| `server/requirements.txt` | 后端依赖 |

---

## 已知边界 case

- 服务端 JPEG 重压：极端 case 全部 quality 都还超 target → 兜底返回 last_bytes + warning 字段（不让公网用户 5xx）
- astrometry.net 解算时间与文件大小**无关**（由视场 + 星点密度决定）。test1 重压后仍 ~22s 是 D610 50mm 中长焦视场小，索引必须搜更细分子库
- Tradition 数据在 startup 加载，损坏 JSON 不会重试（log 提示需重启）
- 大量前端单测需要 jsdom polyfill（`web/tests/setup.ts`）
