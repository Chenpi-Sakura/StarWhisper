# 星语天象 StarWhisper

> 「拍照识星座 · 星座动起来 · AI 讲神话」—— 2026 华为云 OPC 创意大赛参赛作品。
> 当前里程碑：**M2（真实解算 + AI 故事 + atlas 多 tradition 落地）**。

## 1. 项目简介

StarWhisper 让用户拍下的星空"开口说话"——上传一张星空照片，后端把图转给上游 astrometry.net 解算，
再用 astropy 做 WCS 投影把命中星座、亮星、连线的**像素坐标**算出来，前端叠加到照片上；
最后由 AI 按神话 / 科普两种视角讲述这片天空背后的故事。

当前已打通 **「选图 → 真实解算 → 星座 overlay → 星图鉴 → AI 故事」** 完整闭环，
支持 western（89 星座）与 chinese（310 星官）两套 tradition。

设计与实现文档见：

- 开发指南（含架构事实与已知边界）：`CLAUDE.md`
- 上游接口事实源（改 identify 前必读）：`docs/API.md`
- 项目简报与评分口径：`docs/PROJECT_BRIEF.md`
- 设计规格：`docs/specs/` ｜ 实施计划：`docs/plans/` ｜ 修复记录：`docs/fix-notes/`

## 2. 仓库结构

版本控制只跟踪**代码、测试与文档**。比赛交付物料、PPT 工程、工具索引一律不入库。

```
server/                       FastAPI 后端（Python 3.11+，pytest）
├── main.py                   入口；routers + CORS + traditions 启动加载
├── config.py                 .env 自动加载 + 上游地址 / MOCK 开关 / 超时
├── routers/                  HTTP 边界
│   ├── identify.py           POST /api/identify/solve（重压 + 上游解算 + 失败映射）
│   ├── story.py              AI 故事（SSE 流式）
│   ├── atlas_story.py        星图鉴故事
│   ├── atlas_nota.py         识读小笺
│   ├── traditions.py         /api/traditions 多 tradition 数据
│   ├── constellations.py     /api/constellations
│   ├── constellation.py      /api/constellation/{abbr}
│   ├── index.py              观星指数
│   └── health.py             /api/health（上游 + AI provider 状态）
├── services/                 业务逻辑（无 FastAPI 依赖，方便单测）
│   ├── astrometry.py         WCS 投影（astropy）
│   ├── traditions.py         多 tradition 星表 + find_nearest
│   ├── jpeg_recompress.py    公网 ≤4MB 约束的 PIL libjpeg 自适应重压
│   ├── ai_provider.py        OpenAI 兼容 + AgentArts 双 provider（含真流式 SSE）
│   ├── story_fallback.py     AI 不可用时的离线预设
│   ├── constellation.py      星座详情
│   └── weather.py            Open-Meteo 观星指数四档
├── data/
│   ├── traditions/western/   89 个星座 json
│   ├── traditions/chinese/   310 个星官 json
│   ├── raw/                  celestial_data 原始数据（构建输入）
│   ├── fixtures/             mock 与 e2e fixture
│   ├── bayer_index.json
│   └── bortle_cities.json
├── scripts/                  星表构建与校验（build_* / enrich_* / validate / wcs_regression）
├── tests/                    pytest（28 个文件，265 通过 / 32 需联网 deselect）
└── .venv/                    唯一的 Python 虚拟环境（gitignored）

web/                          Vue 3 + Vite + TS + Pinia + vitest + jsdom
├── scripts/gen-cities.mjs    生成 public/data/cn-cities.json（一次联网）
├── public/
│   ├── data/cn-cities.json   3237 条中文城市前缀表
│   └── samples/              离线 mock fixture + 样图 + 样图速测素材
├── src/
│   ├── stores/               scan / atlas / story / stargaze / toast
│   ├── views/                ScanView / ConstellationView / IndexView
│   ├── components/           StarCanvas / StoryPanel / SampleStrip / index/* / common/*
│   ├── api/                  solve / story / health / atlas / stargaze / geocoding
│   └── utils/                exif / heic / stargazeRange / cityTrie
└── tests/                    vitest（35 个文件，278 个用例）

docs/                         全部文档（specs / plans / fix-notes / business / manual / backlog / prompts）
assets/                       真实星图样张 + 中西星名对照数据（被测试与构建脚本引用）
concepts/                     设计原型 HTML
scripts/                      部署与样图素材准备
_archive/                     比赛交付物料 + PPT 工程（本地留底，不入库）
```

## 3. 环境准备

```bash
# 后端：唯一虚拟环境在 server/.venv
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install piexif          # 测试用额外依赖（test_jpeg_recompress.py）

# 前端
cd web && pnpm install
```

## 4. 常用命令

### 后端

```bash
# 全部测试
cd server && .venv/Scripts/python.exe -m pytest -q

# 单个测试文件 / 用例
cd server && .venv/Scripts/python.exe -m pytest tests/test_jpeg_recompress.py -v
cd server && .venv/Scripts/python.exe -m pytest tests/test_identify.py::test_oversize_jpeg_is_recompressed_for_upstream -v

# mock 模式启动（跳过真实上游）
cd server && ASTROMETRY_MOCK=1 .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 真实上游启动（默认 http://117.72.38.57:8010）
cd server && .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 健康检查
curl http://127.0.0.1:8000/api/health
```

### 前端

```bash
cd web
pnpm test          # vitest run（278 个用例）
pnpm dev           # :5173（已配 /api 代理到 :8000）
pnpm build         # vue-tsc --noEmit + vite build
pnpm gen:cities    # 重新生成中国城市前缀数据（一次联网，改城市表时才需要）
```

## 5. 配置（环境变量）

后端启动时自动加载**仓库根目录**的 `.env`（模板见 `.env.example`）。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ASTROMETRY_SERVICE_URL` | `http://117.72.38.57:8010` | 上游解算服务 |
| `ASTROMETRY_MOCK` | `0` | `=1` 时走 mock，跳过真实上游 |
| `ASTROMETRY_TIMEOUT` | `60` | 上游解算超时（秒） |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔 |
| `AI_API_BASE` / `AI_MODEL` | DeepSeek 默认 | AI provider（OpenAI 兼容） |
| `AI_API_KEY` | 空 | 留空则 AI 故事走 preset 降级 |

## 6. 测试现状

| 套件 | 规模 | 状态 |
|---|---|---|
| 后端 pytest | 28 个文件 / 265 通过 / 32 deselect | ✅ 全绿 |
| 前端 vitest | 35 个文件 / 278 个用例 | ✅ 全绿 |

后端 32 个 deselect 是 `test_astro_times.py` 的联网用例：astropy 的 `IERS_Auto`
需要拉取最新地球自转表，**离线环境下预测值超过 30 天会直接抛
`ValueError: interpolating from IERS_Auto using predictive values that are more than 30.0 days old`**。
这不是代码缺陷，联网后自动恢复。

## 7. 关键技术约束

| 约束 | 说明 |
|---|---|
| **公网 4MB 上限** | 上游 `≤4MB` 成功、`≥5MB` 失败（HTTP 400）。由 `services/jpeg_recompress.py` 服务端保障：PIL libjpeg 自适应降级 `[q90, q85, q80]`，不 resize、保留 EXIF。**不要在 web 端压缩 JPEG**（见下） |
| **EXIF Orientation** | 上游按 raw bytes 解算，浏览器 `<img>` 却按 EXIF 转正显示。前端读 Orientation 随 FormData 上传，后端 `_apply_exif_orientation` 变换坐标，orientation 5/6/7/8 时宽高对调 |
| **不要在 web 端压 JPEG** | canvas Skia / mozjpeg-wasm 与 native libjpeg 在 chroma quantization 与 DCT 实现上有像素差异。相机长焦大图即便 EXIF 完整保留，上游 source extractor 仍会拒绝（实测 canvas q80–q95 全失败，libjpeg q70–q95 全成功） |
| **解算耗时与文件大小无关** | 由视场 + 星点密度决定。窄视场长焦图索引搜索更细分子库，仍需 ~20s |
| **fixture 双份字节一致** | `server/data/fixtures/solve_orion.json` 与 `web/public/samples/solve_orion.json` 必须保持同一 SHA256：`EE21DF79BC5A2A1986D9EFD06547BF386288AF5A02A0D49FCACD3FEE6AE08E3D`（已核对一致）。改一份必须同步另一份 |
| **样图速测素材** | `web/public/samples/quick-test*.jpg` 由 `scripts/prepare_quick_samples.py` 生成，**直接 import 服务端生产函数** `recompress_jpeg_to_target`，与用户上传路径产物等价，不存在样图专用后门。改动素材后必须重跑该脚本，否则 `web/tests/quickSamples.test.ts` 会红 |
| **tradition 启动加载** | 星表在 startup 载入，损坏 JSON 不重试（log 提示需重启） |

## 8. 评分对照

| 评分项 | 体现 |
|---|---|
| 创新易用 | 「识别 + 动效 + AI 叙事」三合一闭环，拍张照即可得到可读的天空故事 |
| 商业前景 | 轻量低成本、单机可运营、可插件化科普内容（见 `docs/business/`） |
| 技术架构 | Vue3 + FastAPI + astropy，一人可维护；真实上游解算 + 多 tradition 星表 |
| 功能完备 | 统一错误格式、6 态上传、样图速测、观星指数、星图鉴、AI 故事双风格 |
| 码道深度应用 | 全程 AI 辅助开发，提交 IDE 日志与使用痕迹 |