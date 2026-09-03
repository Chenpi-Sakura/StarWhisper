# 星语天象 StarWhisper - 设计规格

> 版本：v0.5 | 日期：2026-08-22 | 合并 v0.4.1 补丁：统一超时 60/65s、scanStore 6 态对齐、成功体加 ok、429 入表、脚坐标修正、overlay_lines 同源、fixture 路径定死、章节重排

---

## 1. 设计决策汇总

| 决策项 | 结论 |
|--------|------|
| 识别模式 | 同步 POST /api/identify/solve; 后端 60s / 前端 65s; M1 mock 800ms |
| Astrometry 接入 | M2 自行实现策略层(analyse→scale hint→solve 调参), 非裸调上游 API |
| M1 策略 | 后端 skeleton + 前端 skeleton + mock 全链路（绑定官方样图）。真实 solver/WCS/astropy 归 M2 |
| 星座动画 | 原生 Canvas 双模式: overlay（像素对齐）/ scan-atlas（识别结果页内, 不旋转）|
| 路由 | 无 vue-router; M1 仅「星空识别」可用, 其余 tab 显示占位 |
| Overlay 连线 | 前端内置 constellations.json, Bayer join stars_overlay 与图鉴 lines（同源 10 条）|
| 错误格式 | 统一 { ok, ... }; 成功 ok:true+solved:true; 业务失败 HTTP 200 ok:false; 协议错误 4xx/5xx ok:false |
| 样图 | M1 绑定 web/public/samples/orion.jpg + 配套 mock fixture（前后端共用一份）|

---

## 2. Monorepo 项目结构

server/                         # FastAPI 后端 (Python 3.11, conda)
├── main.py                     # 入口：挂载 routers，配置 CORS
├── config.py                   # ASTROMETRY_SERVICE_URL, AI_API_KEY, CORS origins
├── routers/
│   ├── __init__.py
│   ├── identify.py             # POST /api/identify/solve (M2 对接真实 solver; M1 mock)
│   ├── index.py                # 观星指数 (M2)
│   └── story.py                # AI 故事 (M2)
├── services/
│   ├── __init__.py
│   ├── astrometry.py           # M2 策略层（analyse + 调参 + race/crop + 失败映射）
│   ├── weather.py              # Open-Meteo (M2)
│   ├── constellation.py        # 内置星表查询 (M1)
│   └── ai_provider.py          # OpenAI-compatible (M2)
└── data/
    ├── constellations.json     # 内置星座连线数据（源文件）, M1: 5 星座
    ├── bortle_cities.json      # 国内主要城市经纬度 -> Bortle 光污染等级映射
    └── fixtures/
        └── solve_orion.json    # M1 mock fixture（前后端共用, ?mock=1 同源引用, 不复制）

web/                            # 前端 (Vue 3 + Vite + TypeScript + pnpm)
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── tsconfig.json
├── index.html
├── public/
│   └── samples/
│       └── orion.jpg           # M1 官方样图（猎户座, 与 mock fixture 对齐）
├── src/
│   ├── App.vue                 # 报头 + tab 切换 + toast
│   ├── main.ts                 # createApp + Pinia
│   ├── views/
│   │   ├── IndexView.vue       # 观星指数 (M2, M1 占位「即将揭晓」)
│   │   ├── ScanView.vue        # 星空识别 (M1 核心, 含 overlay + scan-atlas)
│   │   └── ConstellationView.vue  # 星座图鉴 (M2, M1 占位)
│   ├── components/
│   │   ├── StarCanvas.vue      # Canvas 动画 (overlay / scan-atlas)
│   │   ├── StoryPanel.vue      # AI 故事 (M2)
│   │   └── common/
│   │       ├── PlateBox.vue, StarChip.vue, StarBtn.vue, StarToast.vue
│   ├── stores/
│   │   ├── scan.ts             # 识别状态机
│   │   ├── stargaze.ts         # 观星数据 (M2)
│   │   └── toast.ts
│   ├── api/
│   │   └── solve.ts            # fetch 封装 (AbortController 65s timeout)
│   ├── data/
│   │   └── constellations.json # 构建时从 server/data 拷贝（单源约定, 见 §10）
│   └── style/
│       └── star-atlas.css


---

## 3. API 契约

### 3.0 外部依赖

Astrometry 私有化服务 (diarmuidkelly/astrometry-api-server)：
- 地址: 环境变量 `ASTROMETRY_SERVICE_URL`（默认 http://117.72.38.57:8010，**非 .38**）
- POST /solve: 同步解算, multipart image
- POST /analyse: 读 EXIF 返回 FOV/scale hint; 无 EXIF 时返回 `{success:false}`（正常,非错误）
- 服务端超时 60s | 索引覆盖 FOV 1.1°–70°（4100 系列）

**关键：HTTP `/solve` 不智能**——智能决策(EXIF→scale hint→downsample/depth 调参→race/crop)在 bash 客户端，不在 REST。**裸 `POST /solve` 走上游弱默认参数(downsample=2, depth=10-20, 无 scale hint)**，求解更慢更易超时。

**M2 适配器(astrometry.py) 必须自行实现策略层:**
1. POST /analyse 取 scale_low/high + scale_units
2. 有 EXIF → POST /solve {image, scale_low, scale_high, scale_units=arcminwidth, downsample_factor=4, depth_low=50, depth_high=100}
3. 无 EXIF → race(3 段不同 scale 并发); 宽边≥6000px 追加 crop
4. 超时 60s(对齐上游); 结果映射为 StarWhisper SolveResult
5. 并发: 同用户禁止重入; 全局信号量 ≤3; 超额 HTTP 429

**上游失败映射:**
| 上游响应 | → 我们的 code |
|----------|-------------|
| `{solved:false, raw_output:"..."}` | SOLVE_FAILED（raw_output 仅打日志,不返回用户）|
| `{solved:false, error:"solve operation timed out"}` | TIMEOUT |
| HTTP 连接失败/非 JSON | 先 GET /health 确认, 仍失败 → ASTROMETRY_DOWN |

**WCS 细节(M2):**
- CRPIX 是参考点(非图像中心, 此样图偏 166×152px)。用原图尺寸,不用 CRPIX 反推
- CTYPE=RA---TAN-SIP: 含 SIP 畸变校正。必须用完整 `wcs_header` 做 `world2pix`, 不能只用 center+pixel_scale+rotation 简化仿射(40°边缘会偏)
- astropy 默认 FITS 1-based / 原点左下; Canvas 0-based / 左上。Y 翻转 + origin 校准
- `rotation` 字段: 像素坐标已在照片坐标系, 前端不再旋转
- annotate=true 返回标注图仅调试用, 不做产品 overlay

**能力边界:**
- FOV 超出 1.1°–70° 不解或靠 crop 碰运气; advice 提示「请使用普通镜头星空照片, 避开全天鱼眼」

### 3.1 POST /api/identify/solve

上传星空照片，代理到 Astrometry 私有服务 plate-solving, 返回识别结果 + WCS 像素坐标 + overlay 连线。

**HTTP:** POST | Content-Type: multipart/form-data | Field: image (JPG/PNG, 原图不压缩, 最大 20MB)
**超时:** 后端代理 60s(对齐上游), 前端 AbortController 65s, M1 mock 800ms delay

**成功 HTTP 200:**
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
    {
      "abbr": "ori", "name": "猎户座", "latin": "Orion",
      "confidence": 0.875, "hit_stars": 7, "total_bright_stars": 8
    }
  ],
  "stars_overlay": [
    {
      "bayer": "Beta Ori", "name": "参宿七", "magnitude": 0.13,
      "pixel_x": 3421, "pixel_y": 2018, "constellation": "ori"
    }
  ],
  "overlay_lines": [
    ["Alpha Ori", "Gamma Ori"], ["Alpha Ori", "Lambda Ori"], ["Lambda Ori", "Gamma Ori"],
    ["Alpha Ori", "Zeta Ori"], ["Gamma Ori", "Delta Ori"], ["Delta Ori", "Epsilon Ori"],
    ["Epsilon Ori", "Zeta Ori"], ["Delta Ori", "Beta Ori"], ["Zeta Ori", "Kappa Ori"], ["Beta Ori", "Kappa Ori"]
  ]
}

**字段说明:**
- `ok`: 全局统一字段。成功 true, 失败 false。前端统一 `if (!data.ok)` 判失败
- image_width/height: 原图解码后像素尺寸(非 WCS CRPIX, 用 PIL/解码器取得)
- exif_orientation: 原始 EXIF Orientation 值(1-8)。M1 fixture 固定写 1
- constellations: abbr 小写, confidence = 画面内命中亮星数 / 该星座总亮星数（如 7/8 = 0.875）
- stars_overlay: Bayer 编号做 join key。视场内亮星(mag < 3.5) + Bayer join 匹配的星座恒星。**须包含为画线而留的视场外端点**（pixel_x/y 可超出 [0,image_width]×[0,image_height]）, 否则「保留端点、canvas clip」无数据。示例仅示参宿七一颗, **fixture `solve_orion.json` 必须含完整 8 星 + 10 线**, pixel_x/y 对 orion.jpg 手工点过
- overlay_lines: Bayer 对数组, 与 atlas lines 同源（10 条, 见 §3.2）。视场外端点: 保留坐标, Canvas 裁切绘制
- overlay_lines 归属: 通过 stars_overlay 的 constellation 字段推断, 两端同属一个 abbr 即为该星座连线。选中某星座时其连线 opacity=1, 其余 opacity=0.3
- pixel_x/y: 须从 orion.jpg 真实解算或手工标注取得（M1 可手工标注占位, M2 用真 solve 回归校准, 误差 < 2px）
- pixel_scale: arcsec/pixel
- Y 轴已翻转(FITS 左下原点 -> Canvas 左上原点)

**Bayer 字符串冻结格式:** 一律 `Latin + 空格 + IAU 三字母`（如 `"Alpha Ori"`）, 大小写敏感。禁止 `"α Ori"` / `"Alp Ori"`

**失败 HTTP 200:**
{
  "ok": false, "solved": false, "solve_time": 8.99,
  "code": "SOLVE_FAILED",
  "message": "星图解析未成",
  "advice": "星点模糊或光害过强, 请用更澄澈的夜空照片重试。"
}

**超时 HTTP 200:**
{
  "ok": false, "solved": false, "solve_time": 50.0,
  "code": "TIMEOUT",
  "message": "解析超时",
  "advice": "请尝试视野稍窄的星空区域照片。"
}

**错误 HTTP 4xx/5xx:**
{ "ok": false, "code": "...", "message": "...", "advice": null }

| HTTP | code | message |
|------|------|---------|
| 413 | UPLOAD_TOO_LARGE | 图片超过 20MB 限制 |
| 400 | UNSUPPORTED_FORMAT | 仅支持 JPG、PNG 格式 |
| 429 | BUSY | 引擎繁忙，请稍后 |
| 502 | ASTROMETRY_DOWN | 星图解析引擎暂不可用 |
| 500 | INTERNAL | 服务端异常 |

### 3.2 GET /api/constellation/{abbr}

根据星座缩写(小写)返回图鉴连线数据。用于 atlas 模式。**M1 内置 orion/cygnus/scorpius/leo/andromeda**

**查找规则:** 按 `entry.abbr` 匹配, 大小写不敏感（`ORI` / `ori` 均可）。json key（`orion`）与路径（`ori`）不同, 以 abbr 为准, 不要因 `orion` 路径 404。

**HTTP 200:**
{
  "ok": true,
  "abbr": "ori", "name": "猎户座", "latin": "Orion",
  "glyph": "✶", "season": "冬季",
  "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
  "stars": {
    "betelgeuse": {"x":144,"y":62, "bayer":"Alpha Ori","name":"参宿四","magnitude":0.42},
    "bellatrix":  {"x":330,"y":78, "bayer":"Gamma Ori","name":"参宿五","magnitude":1.64},
    "meissa":     {"x":282,"y":28, "bayer":"Lambda Ori","name":"觜宿一","magnitude":3.39},
    "alnitak":    {"x":260,"y":148,"bayer":"Zeta Ori","name":"参宿一","magnitude":1.74},
    "alnilam":    {"x":280,"y":158,"bayer":"Epsilon Ori","name":"参宿二","magnitude":1.69},
    "mintaka":    {"x":300,"y":168,"bayer":"Delta Ori","name":"参宿三","magnitude":2.23},
    "saiph":      {"x":228,"y":246,"bayer":"Kappa Ori","name":"参宿六","magnitude":2.06},
    "rigel":      {"x":334,"y":238,"bayer":"Beta Ori","name":"参宿七","magnitude":0.13}
  },
  "lines": [
    ["betelgeuse","bellatrix"],["meissa","betelgeuse"],["meissa","bellatrix"],
    ["betelgeuse","alnitak"],["bellatrix","mintaka"],
    ["mintaka","alnilam"],["alnilam","alnitak"],
    ["mintaka","rigel"],["alnitak","saiph"],["rigel","saiph"]
  ],
  "bright_stars_mag_lt_35": 8
}

**说明:**
- abbr 统一小写 | X 轴: 左侧 RA 更大(标准星图方向, 面对南天) | 字段名统一 `magnitude`
- stars key 用英文常用名, 含 bayer 字符串做 join key
- 星等范围: -1.46(天狼) ~ 3.5
- 脚坐标已修正: Saiph(东足)左下 x=228, Rigel(西足)右下 x=334, 与肩/腰带方向一致

**HTTP 404:**
{ "ok": false, "code": "CONSTELLATION_NOT_FOUND", "message": "未收录此星座", "advice": "目前内置 5 星座, 更多将在后续版本加入" }


## 4. 主链路数据流

### 4.1 识别链路
1. 用户选图(相册/样图) — scanStore → ready, previewUrl 显示
2. 点击「开始识别」— POST /api/identify/solve (multipart 原图)
3. 显示 loading(astrolabe + 步骤文案); 进行中禁止重复点击
4. solved/done — overlay StarCanvas 渲染(像素映射 contain+letterbox)
5. empty — 结果卡 + 「未识别到已收录星座」banner
6. 用户选星座 — 高亮对应 overlay_lines
7. 「查看连线样式」— 切换到 scan-atlas 模式预览(不旋转)

### 4.2 前后端状态映射
| 前端 status | 条件 | 展示 |
|------------|------|------|
| idle | 初始 | 引导文案 |
| ready | 已选图, previewUrl | 缩略图 + 「开始识别」按钮 |
| uploading | fetch 中 | loading 动画 + 文案, 禁止操作 |
| done | solved && constellations.length>0 | overlay Canvas + 星座列表 |
| empty | solved && constellations.length===0 | 结果卡 + empty banner（星点淡显示 opacity 0.2, 不画线）|
| error | !solved 或 HTTP 错误或超时 | errorCard + advice/message |

### 4.3 错误处理
| 场景 | 触发 | 用户看到 |
|------|------|---------|
| 求解失败 | solved=false | errorCard + advice 文案 |
| 超时 | 65s 无响应 | errorCard + 超时引导 |
| 求解成功但无星座 | constellations=[] | 结果卡片 + 未识别引导 |
| 服务不可达 | 502 | toast + 重试按钮 |

---

## 5. 前端状态管理

### scanStore (Pinia)
status: idle / ready / uploading / done / empty / error
imageFile: File | null
previewUrl: string | null
result: SolveResult | null              // POST /api/identify/solve 完整响应
activeAbbr: string | null               // 当前选中星座（Canvas 与 store 统一用 activeAbbr）
errorCode: string | null
errorMessage: string | null
abortController: AbortController | null  // 可控取消

actions:
- selectImage(file: File) — revoke 旧 previewUrl → 设 imageFile/previewUrl → status=ready
- solve() — POST multipart, AbortController 可控, 65s timeout
- cancel() — abort fetch, 回 ready（保留预览, 不清 imageFile/previewUrl）
- selectConstellation(abbr) — 设置 activeAbbr
- reset() — revoke previewUrl, 清空全部字段, 回 idle

### toastStore
- show(message, type: info|success|error) — 3s 自动消失

### stargazeStore (M2)
- cityName, weatherData, scoreIndex, hourlyForecast

---

## 6. Canvas 动画规格

### 6.1 双模式

**overlay 模式（识别成功, done/empty 状态）:**
- Props: mode="overlay", stars_overlay[], overlay_lines[], imageWidth, imageHeight, activeAbbr
- 像素映射(关键):
  ```
  scale  = min(contentW/imageWidth, contentH/imageHeight)  // contain
  offsetX = (contentW - imageWidth*scale) / 2               // letterbox
  offsetY = (contentH - imageHeight*scale) / 2
  sx = pixel_x * scale + offsetX                            // CSS 像素
  sy = pixel_y * scale + offsetY
  canvas.width  = contentW * devicePixelRatio
  canvas.height = contentH * devicePixelRatio
  ctx.scale(dpr, dpr)  // 绘图全用 CSS 像素
  ```
- object-fit: contain(禁止 cover, 会裁切星点)
- Canvas 绝对定位覆盖 img, 尺寸 = 图片 display rect
- **CSS 强制:** `canvas { width: 100%; height: 100%; }` 避免高清屏物理拉伸形变
- **ResizeObserver:** StarCanvas.vue 挂载 ResizeObserver 监听父容器尺寸, 窗口 resize / 移动端横竖屏切换时重算 scale/offset 并重绘
- 动画: 连线描出(1.2s) + 闪烁; **关闭旋转**
- 高亮: activeAbbr 对应的星和连线 opacity=1 / 金色; 其他星座 opacity=0.3
- 连线归属: 通过 stars_overlay 的 constellation 字段推断, 两端同属 activeAbbr 即高亮
- 视场外端点: 保留坐标, clipping 自然裁切
- rotation 字段忽略(WCS 已投影对齐)
- empty 状态: 星点淡显示 opacity 0.2, 不画 overlay_lines, 只出 banner

**scan-atlas 模式（识别成功后切换, 查看图鉴样式）:**
- Props: mode="scan-atlas", constellationData(来自 3.2), activeAbbr
- viewBox 640×460, 背景网格 + 双同心圆
- 动画: fadeIn → drawLines → twinkle; **不旋转**
- 星点半径: r = clamp(4 - 0.4 * magnitude, 1.2, 8); 天狼 -1.46 → 4.58
- 高亮态: shadowBlur 发光|6px 5px gold|

### 6.2 性能

- Canvas shadowBlur(非 CSS filter, 避免整 canvas 重绘)
- requestAnimationFrame 60fps; overlay ≤ 30 星; atlas ≤ 200 星(背景散布)
- prefers-reduced-motion: 跳过动画, 直接终态, 停旋转

---

## 7. M1 交付清单 (8.20 - 8.23)

**原则:** 后端 skeleton + 前端 skeleton + mock 全链路（绑定样图对齐）。

### 后端
- [ ] FastAPI 骨架: main.py + config.py(仅 ASTROMETRY_SERVICE_URL/CORS) + requirements.txt
- [ ] Mock POST /api/identify/solve（返回猎户座 fixture, 800ms delay）
- [ ] Mock GET /api/constellation/{abbr}（返回 5 星座 JSON, abbr 小写, 大小写不敏感）
- [ ] 统一错误格式 {ok, code, message, advice?}; 成功体含 ok:true

### 前端
- [ ] Vue3 + Vite + TS + pnpm; 仿古 CSS 变量
- [ ] 通用组件: PlateBox, StarChip, StarBtn, StarToast
- [ ] App.vue: 报头 + 三 tab（M2 tab 占位）
- [ ] ScanView: 图片选择/预览 + idle→ready→uploading→done|empty|error 全状态
- [ ] StarCanvas overlay: 像素映射 + contain/letterbox + 连线描出 + 闪烁 + ResizeObserver
- [ ] StarCanvas scan-atlas: 识别成功后切换查看(不旋转)
- [ ] api/solve.ts: fetch 封装 65s timeout + AbortController
- [ ] 前端内置 constellations.json（构建时从 server/data 拷贝, Bayer join + atlas 渲染）

### Mock 模式
- [ ] ?mock=1 开关。**离线方案:** 前端存 `web/public/samples/solve_orion.json`（与 `server/data/fixtures/solve_orion.json` 内容相同, CI 比 hash 保证一致）, 纯前端可跑; 后端 mock endpoint 读 server 源 fixture
- [ ] 样图: web/public/samples/orion.jpg
- [ ] 样图对齐的 mock fixture（8 颗猎户亮星 + 10 条 overlay_lines, exif_orientation=1, pixel_x/y 对 orion.jpg 手工点过）
- [ ] 800ms 模拟延迟（展示 loading 状态）
- [ ] UI 文案：「样图模式 —— 点击"开始识别"查看猎户座识别效果」
- [ ] **对齐 banner（全程悬挂）:**「样图模式, 星点对齐官方样图; 换任意照片将在后续版本接入真引擎。」— 防止用户选任意照片后 overlay 漂移误认为画布 bug

### 不入 M1
- astrometry.py 策略层(analyse+参数+race/crop+失败映射)
- astropy SIP world2pix 坐标转换
- 真实 solve 代理; 并发信号量
- 观星指数 / 星座图鉴完整页 / AI 故事 / 分享卡
- HEIC 支持、EXIF 方向处理

### M1/M2 边界
| 项 | M1 | M2 |
|----|----|----|
| 样图 + 完整成功 JSON fixture | ✓ | 做回归对照（误差 < 2px）|
| overlay Bayer join + contain 映射 | ✓ | 不变 |
| 后端 mock endpoint | ✓ | 替换为策略层 |
| astrometry.py 策略层 | | ✓ |
| SIP world2pix → stars_overlay | | ✓ |
| race/crop/信号量/429 | | ✓ |
| HEIC / EXIF orientation | | 尽早 |

## 8. 技术约束

- Astrometry 服务地址进环境变量; 不写死 IP
- 图片原图上传不压缩(压缩丢 81% 星点)
- 后端磁盘仅用于 multipart 临时接收, 完成后清理
- 后端 M2 依赖 astropy 计算 WCS 像素坐标
- AI Key 仅服务端环境变量
- 前端: pnpm, Node≥20 | 后端: conda, Python 3.11
- CORS: 可配置 origin 列表, 默认 localhost:5173
- 无数据库, 内存态 + JSON + 外部 API
- 部署: 华为云 AI Shell 一键部署(M4)
- 并发: 前端进行中禁止重入; 后端全局信号量 ≤3(M2); 超额 429 BUSY
- 服务端裁切/压缩: 禁用客户端重采样; 允许不改分辨率的裁切; 缩小仅靠上游 downsample_factor

## 9. 异常与降级

| 场景 | 用户看到 |
|------|---------|
| solve solved=false | errorCard + advice 文案 |
| 超时(前端 65s) | errorCard + 「解析超时」 |
| 429 并发超限(M2) | toast + 「引擎繁忙, 请稍后」; 自动恢复 |
| FOV 超 1.1°–70°(M2) | SOLVE_FAILED + advice「请用普通镜头星空照」 |
| analyse 无 EXIF(M2) | 内部自动 race, 用户无感 |
| 解算成功但无星座(empty) | 结果卡 + 「画面内未识别到已收录星座」 banner |
| Astrometry 不可达(502) | toast + 重试按钮 |
| 上传超限/格式错误 | toast + message |
| 星座不在内置星表(404) | toast + advice |
| 观星一票否决(M2) | 云量>80% 或降水>50% — 指数≤40, 强制「差」 |
| AI 不可用(M2) | 静态预设故事 |

> 注: 超时 advice「视野稍窄」对广角/鱼眼准确; 无 EXIF race 超时场景 M2 再细分 advice。

---

## 10. 星座数据规格

**M1 内置 5 星座:** orion(猎户座), cygnus(天鹅座), scorpius(天蝎座), leo(狮子座), andromeda(仙女座)

**constellations.json 格式:**
{
  "orion": {
    "abbr": "ori", "name": "猎户座", "latin": "Orion",
    "glyph": "✶", "season": "冬季",
    "caption": "冬夜之王。腰带三星之下，悬着一柄孕育恒星的剑。",
    "stars": {
      "betelgeuse": {"x":144,"y":62, "bayer":"Alpha Ori","name":"参宿四","magnitude":0.42},
      ...
    },
    "lines": [["betelgeuse","bellatrix"], ...],
    "bright_stars_mag_lt_35": 8
  }
}

**规范:**
- key 用英文常用名(betelgeuse 非 bet)。join 用 bayer 字符串(如 "Alpha Ori"), 禁止 key
- x/y: 图鉴 viewBox 640×460, 面向南天(左侧 RA 更大)
- 字段名统一 magnitude, 支持负数(天狼 -1.46)
- API 3.2 与本地 json 同源; overlay 用 3.1 的 overlay_lines（与 atlas lines 同一份 Bayer 拓扑, 10 条）, 不调 3.2
- 连线两端星键匹配 stars 下 key; 星点大小公式 r = clamp(4-0.4*mag, 1.2, 8)
- **单源约定:** `server/data/constellations.json` 为源文件; 前端构建时拷贝到 `web/src/data/constellations.json`; 3.2 mock 读 server 源文件。禁止两份各自维护
- **Bayer 冻结:** 一律 `"Latin + 空格 + IAU 三字母"`（如 `"Alpha Ori"`）, 大小写敏感。禁止 `"α Ori"` / `"Alp Ori"`
