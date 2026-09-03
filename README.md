# 星语天象 StarWhisper

> 「拍照识星座 · 星座动起来 · AI 讲神话」—— 2026 华为云 OPC 创意大赛参赛作品。
> 当前里程碑：**M1 工程骨架**（mock 全链路 + 官方样图对齐）。

## 1. 项目简介

StarWhisper 让用户拍下的星空"开口说话"——上传一张星空照片，自动识别画面内的星座并叠加连线，定位到具体星名后由 AI 讲述背后的神话故事。M1 阶段已打通 **「选图 → mock 识别 → 像素对齐 overlay」** 完整闭环，绑定官方样图 `orion.jpg` 用于评审演示。

详细设计与里程碑见：

- 设计规格：`docs/specs/2026-08-21-starwhisper-design.md`
- 实施计划：`docs/plans/2026-08-22-starwhisper-m1-scaffold.md`
- 项目简报：`docs/PROJECT_BRIEF.md`
- 上游 Astrometry 文档：`docs/API.md`

## 2. 仓库结构

```
server/                          # FastAPI 后端（Python 3.11+，pytest）
├── main.py                      # 入口，挂载 routers + CORS + 健康检查
├── config.py                    # ASTROMETRY_SERVICE_URL / CORS_ORIGINS
├── routers/
│   ├── constellation.py         # GET /api/constellation/{abbr}（大小写不敏感, 404 JSONResponse）
│   └── identify.py              # POST /api/identify/solve（M1 mock, 800ms delay, 400/413 校验）
├── services/constellation.py    # 内置星座星表查询
├── data/
│   ├── constellations.json      # 5 星座源文件（单源）
│   └── fixtures/solve_orion.json# M1 mock 样图 fixture（8 星 + 10 线）
└── tests/                       # pytest: 9 个用例

web/                             # Vue 3 + Vite + TS + pnpm + vitest
├── index.html
├── vite.config.ts               # 自定义 plugin 同步 constellations.json (dev + build)
├── vitest.config.ts             # jsdom + setup polyfill (URL.createObjectURL)
├── public/samples/              # 离线 mock fixture + 样图（与 server fixture hash 一致）
└── src/
    ├── main.ts                  # createApp + Pinia
    ├── App.vue                  # 报头 + 三 tab + StarToast
    ├── views/
    │   ├── ScanView.vue         # 6 状态全链路 + 照片叠层 + scan-atlas 切换
    │   ├── IndexView.vue        # 观星指数 M2 占位
    │   └── ConstellationView.vue# 星座图鉴 M2 占位
    ├── components/
    │   ├── StarCanvas.vue       # overlay（像素映射 + lineTo）+ scan-atlas（同心圆 + 网格）
    │   └── common/              # PlateBox / StarChip / StarBtn / StarToast
    ├── stores/                  # toast store + scan store（6 态 + 真 65s timeout）
    ├── api/solve.ts             # fetch 封装（AbortSignal.timeout 65s + mock 800ms）
    ├── data/constellations.json # plugin 从 server/data/ 拷贝
    ├── types.ts                 # SolveResult 正式 interface
    └── style/star-atlas.css     # 仿古星图册变量（羊皮纸 / 金墨 / 印章）
```

## 3. 启动方式

### 后端（FastAPI）

```bash
# 创建并激活项目虚拟环境（依赖 fastapi/uvicorn/httpx/python-multipart/pytest）
python -m venv server/.venv
server\.venv\Scripts\activate

# 在虚拟环境中一次性安装依赖
python -m pip install -r server/requirements.txt

# 运行测试
python -m pytest tests/ -q

# 启动（默认 :8000）
cd server && python -m uvicorn main:app --reload

# 验证
curl http://localhost:8000/api/health
curl http://localhost:8000/api/constellation/ori
```

### 前端（Vue3 + Vite）

```bash
# 安装依赖（已锁定 Node ≥ 20 + pnpm ≥ 11）
cd web && pnpm install

# 类型检查 + 单测
pnpm test            # vitest run（15 个用例）

# Dev server（默认 :5173，已配 /api 代理到 :8000）
pnpm dev

# 生产构建 + 预览
pnpm build
pnpm preview         # :4173
```

## 4. Mock 模式与对齐 banner

- **URL 开关**：`http://localhost:5173/?mock=1` 直接读 `web/public/samples/solve_orion.json`，跳过真实后端。
- **M1 常驻 banner**：UI 顶部常驻红色 banner「样图模式, 星点对齐官方样图; 换任意照片将在后续版本接入真引擎。」——防止 overlay 漂移被误判为画布 bug。
- **800ms 模拟延迟**：后端 mock 与前端 mock sleep 都做 800ms，可观察到 uploading 状态的旋转 loading。

## 5. 两份 fixture 的 hash 约束

`server/data/fixtures/solve_orion.json` 与 `web/public/samples/solve_orion.json` 必须保持**字节级一致**：

```text
SHA256  EE21DF79BC5A2A1986D9EFD06547BF386288AF5A02A0D49FCACD3FEE6AE08E3D
```

CI 比 hash 失败时应同步两份。修改其中一份务必同时修改另一份（典型场景是调整 fixture 的 8 颗星坐标或 10 条 overlay_lines）。

## 6. 样图来源

`web/public/samples/orion.jpg` 是占位图，由 `scripts/make_orion_sample.py` 生成：

- 尺寸：6016×4016（3:2），与 fixture 的 `image_width/image_height` 完全一致。
- 内容：暗蓝底 + 240 颗随机背景星 + 8 颗 fixture 命中星（白圆点 + 软发光），坐标精确落在 `pixel_x/y` 上。
- 真实样图替换：将新图保存为 `web/public/samples/orion.jpg` 即可；fixture 像素坐标不变。

## 7. 关键技术约束（design spec binding）

| 约束 | 当前实现 |
|---|---|
| 错误统一格式 `{ ok, code?, message?, advice? }` | ✓ 成功体含 `ok:true`，失败体含 `code` |
| Bayer 字符串冻结 `Latin + 空格 + IAU` | ✓ 严格 `Alpha Ori` 风格，大小写敏感 |
| 后端超时 60s / 前端 65s / M1 mock 800ms | ✓ 三档独立配置 |
| 单源：`server/data/constellations.json` → `web/src/data/` | ✓ Vite plugin 在 dev + build 都同步 |
| M1 全程 mock + 常驻 banner | ✓ 不只在 `?mock=1` |
| 客户端拦截 JPG/PNG + 20MB | ✓ 拦截不发请求 + toast |
| 404 用 HTTP 404（不是 200 + ok:false） | ✓ `JSONResponse(status_code=404)` |
| overlay 连线 `lineTo`（非 `moveTo`） | ✓ StarCanvas 已用 `lineTo`，测试断言 |

## 8. M2 路线图

- **真实求解接入**：实现 `services/astrometry.py` 策略层（analyse → scale hint → race/crop → 失败映射）。
- **WCS 像素坐标**：用 astropy 的 `world2pix`（含 SIP 校正）从 WCS 头推出 stars_overlay 的 pixel_x/y。
- **完整超时/并发**：服务端 60s timeout + 全局信号量 ≤3 + 超额 HTTP 429。
- **真实样图**：替换占位 `orion.jpg` 为真实拍摄；坐标按真实解算结果回归（误差 < 2px）。
- **观星指数**（Open-Meteo + Bortle + 月相）+ **AI 故事**（OpenAI 兼容 provider）+ **星座图鉴**完整页。
- **HEIC 支持 / EXIF 方向**：尽早接入。

## 9. 评分对照

| 评分项 | 体现 |
|---|---|
| 创新易用 | 「识别 + 动效 + AI 叙事」三合一差异化闭环 |
| 商业前景 | 轻量低成本、单机可运营、可插件化科普内容 |
| 技术架构 | OPC 轻量化：Vue3 + FastAPI + Conda 一人维护；M1 mock 完整闭环 |
| 功能完备 | 主链路 mock 全通；统一错误格式 + 6 态 + 客户端拦截 |
| 码道深度应用 | 全程 AI 辅助开发，提交 IDE 日志与使用痕迹 |