# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## ⚠️ 每次 commit 必做

`作品提交文件夹/04码道使用证明/` 目录下放的是 **OPC 大赛提交物**（运行截图 / 实操演示 / 改进前后对比 / spec 修订说明 / M2 执行情况等 png），由本会话每次实现新功能后**手动更新**。

**规则**：每次 commit 前必须检查此目录是否有新截图/新内容；如有，**必须**把这些 png 一起 commit 进去（保留大赛提交物的连续性）。

git 操作建议：
```bash
git add "作品提交文件夹/04码道使用证明/"*.png
# 然后再正常 add 代码改动
```

---

## 项目一句话

StarWhisper（星语天象）—— 拍照识星座 + 星座动起来 + AI 讲神话。2026 华为云 OPC 创意大赛参赛作品。**当前里程碑：M2（真实解算 + AI 故事 + atlas 多 tradition 落地）**。

详细 spec 见 `docs/specs/`，实施计划见 `docs/plans/`，项目背景见 `docs/PROJECT_BRIEF.md`。

---

## 仓库布局

```
server/                  FastAPI + Python 3.11+ + pytest
  main.py                入口；routers + CORS + traditions 启动加载
  config.py              .env 自动加载 + ASTROMETRY_SERVICE_URL / MOCK 开关 / 超时
  routers/               路由层（HTTP 边界）
    identify.py          POST /api/identify/solve（核心：JPEG 重压 + 上游解算 + 失败映射）
    story.py             AI 故事流式接口
    traditions.py        /api/traditions 多 tradition 数据
    health.py            /api/health（astrometry + ai_provider 状态）
    constellation.py     /api/constellation/{abbr}
    constellations.py    /api/constellations
  services/              业务逻辑层（无 FastAPI 依赖，方便单测）
    astrometry.py        WCS 投影（astropy）
    traditions.py        多 tradition 星表 + find_nearest + build_star_catalog
    jpeg_recompress.py   公网 ≤4MB 约束的服务端 PIL libjpeg 自适应重压
    ai_provider.py       OpenAI 兼容 + AgentArts 双 provider
    story_fallback.py    AI 不可用时的离线预设故事
    constellation.py     星座详情
  data/                  constellations.json + fixtures
  tests/                 pytest（26 个用例：identify + jpeg_recompress + traditions + e2e）

web/                     Vue 3 + Vite + TS + Pinia + vitest + jsdom
  src/
    stores/scan.ts       选图 + solve() 主流程
    views/               ScanView / ConstellationView / StoryView
    components/          StarCanvas（overlay 像素映射 + 动画）
    api/solve.ts         fetch 封装（AbortSignal.timeout 65s）
    utils/               exif / heic
  public/samples/        离线 mock fixture + 样图
  tests/                 vitest（72 个用例）
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
pnpm test                # vitest run（72 个用例）
pnpm test -- utils.exif  # 跑文件名包含 utils.exif 的
pnpm dev                 # :5173（已配 /api 代理到 :8000）
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

### AI 故事流

`server/services/ai_provider.py` 抽象层：
- `AgentArtsProvider`（华为云智能体，AK/SK 签名）
- `OpenAICompatibleProvider`（DeepSeek 等）
- 都没配时 `DisabledProvider` 兜底 → `story_fallback.py` 离线预设

路由 `server/routers/story.py` 是 SSE 流式响应。

---

## 测试基础设施

- 后端 26 测试：identify 14 + jpeg_recompress 12 + 各种 router/service 单元
- 前端 72 测试：jsdom + setup polyfill（URL.createObjectURL）
- e2e：test1/test2/test3 三张真实星图（`assets/test*.jpg`），test1 是 D610 MPO 24MP 长焦样图

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
| `docs/specs/2026-08-21-starwhisper-design.md` | 整体产品设计 |
| `docs/specs/2026-08-23-starwhisper-design-m2.md` | M2 增量设计 |
| `docs/specs/2026-08-25-atlas-tradition-design.md` | tradition 多源星表设计 |
| `docs/plans/2026-08-24-starwhisper-m2-impl.md` | M2 实施计划 |
| `docs/PROJECT_BRIEF.md` | 产品背景 + 评分口径 |
| `server/requirements.txt` | 后端依赖 |

---

## 已知边界 case

- 服务端 JPEG 重压：极端 case 全部 quality 都还超 target → 兜底返回 last_bytes + warning 字段（不让公网用户 5xx）
- astrometry.net 解算时间与文件大小**无关**（由视场 + 星点密度决定）。test1 重压后仍 ~22s 是 D610 50mm 中长焦视场小，索引必须搜更细分子库
- Tradition 数据在 startup 加载，损坏 JSON 不会重试（log 提示需重启）
- 大量前端单测需要 jsdom polyfill（`web/tests/setup.ts`）
