# M2 测试手册

本手册覆盖 StarWhisper M2（星语天象）端到端人工验收，对应 spec §12 验收标准。
执行环境：Windows + Python 3.14 + Node 20+。

## 1. 启动后端

```bash
cd server
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

- 默认 `ASTROMETRY_MOCK=0`：走真实 astrometry 上游（需网络可达 `ASTROMETRY_SERVICE_URL`）。
- 离线验收：`$env:ASTROMETRY_MOCK="1"; .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000`。
- 健康检查：`curl http://localhost:8000/api/health` 应返 `{ok:true,...}`。

## 2. 启动前端

```bash
cd web
npm run dev
```

- 默认端口 5173，自动打开 http://localhost:5173/。
- 后端代理已配置在 `vite.config.ts`，`/api/*` 转发到 `localhost:8000`。

## 3. 验收路径

### 路径 A：扫描 → 解出 → 看故事

1. 打开 http://localhost:5173/，默认进入「星空识别」tab。
2. 点「观星指数」tab → 页面显示「试一张 orion」按钮 + 「前往星座图鉴」按钮。
3. 点「试一张 orion」按钮 → 自动切回「星空识别」tab，预填 `orion.jpg`，进入 ready 状态。
4. 点「开始识别」→ 等 ~3 秒（mock 模式）或 ~30 秒（真实上游），应看到：
   - StarCanvas 上 8 条连线错峰描出 + 8 颗主星闪烁。
   - 下方「猎户座 (100%)」chip 高亮。
   - StoryPanel 显示「猎户神话」标题 + ≥ 1 段正文。
5. 点「科普」切换 → 段落刷新（若前端 store 已缓存则直接显示，否则请求后端）。
6. 点「换一篇」→ 跳过后端 LRU 重生成（`cached=false`，`latency_ms > 100`）。

### 路径 B：星座图鉴

1. 顶部导航点「星座图鉴」tab。
2. 左侧 5 张卡片（ori / cyg / sco / leo / and），每张含星名 + 拜耳名。
3. 点「猎户座」→ 右侧 StarCanvas 缓回旋 ±2° sin(12s)，8 颗主星 + 连线样式。
4. 点「用这个去扫描 →」→ 切到「星空识别」tab 并预填 ori（待 M2.5 接入真解后生效）。

### 路径 C：HEIC 自动转码

1. 「星空识别」tab 上传 iPhone HEIC 文件（可用 `web/public/samples/orion.heic`）。
2. 立即看到 info 提示「HEIC 将由服务器自动转换为 JPG」。
3. 点「开始识别」→ 服务端通过 pillow-heif 转码后正常解出星座（无需用户操作）。
4. 响应 `exif_orientation=1`（已转正）。

### 路径 D：异常降级

1. 关掉后端（`Ctrl+C` 停止 uvicorn）。
2. 「星空识别」tab 上传任意图片 → 看到友好错误提示「网络异常」+ 重试按钮。
3. 重新启动后端 → 点「重试」按钮 → 恢复正常识别流程。

### 路径 E：Orientation=3 转正

1. 「星空识别」tab 上传 `web/public/samples/orion_orientation_3.jpg`（EXIF Orientation=3）。
2. 点「开始识别」→ 服务端 `normalize_image` 旋转 180° + 重编码 q95。
3. 响应 `exif_orientation=1`，StarCanvas overlay 与照片方向一致（不偏 180°）。

## 4. 截图存档

以下截图为人工验收产物，路径占位（验收时实际拍摄后放入）：

- `docs/manual/screenshots/m2-canvas-overlay.png` — 路径 A 第 4 步：StarCanvas 8 星 + 8 连线 overlay。
- `docs/manual/screenshots/m2-scan-view.png` — 路径 A 第 3 步：ScanView ready 状态预览。
- `docs/manual/screenshots/m2-atlas-view.png` — 路径 B 第 3 步：ConstellationView 猎户座回旋。
- `docs/manual/screenshots/m2-story-ready.png` — 路径 A 第 4 步：StoryPanel 神话正文。

## 5. 自动化测试

### 5.1 后端 e2e（spec §12 验收）

```bash
cd server
.\.venv\Scripts\python.exe -m pytest tests/test_e2e_orion.py -v
```

期望：6 passed（E2E#1-#6 全覆盖）。

### 5.2 后端全量

```bash
cd server
.\.venv\Scripts\python.exe -m pytest -v
```

期望：全绿（含 bayer 对齐 / 并发 / 星座 / 健康 / 识别 / 故事 / WCS 回归 / e2e orion）。

### 5.3 前端全量

```bash
cd web
npm test -- --run
```

期望：全绿（含 ScanView / StarCanvas / StoryPanel / ConstellationView / stores）。

## 6. 已知限制

- **M2 仅覆盖猎户座真解**：其余 4 星座（cyg / sco / leo / and）的 RA/Dec 待 M2.5 补全，图鉴可显示但扫描不命中。
- **AI 故事默认降级**：未配置 `AI_API_KEY` 时走 traditions 内嵌 brief 降级（`degraded:true`），需配置 DeepSeek / 字节 API Key 才能验证真实 LLM 生成。T7 已将 stories 内嵌到各 constellation JSON，不存在独立 `preset_stories.json`。
- **HEIC 转码质量**：pillow-heif 重编码 q95，极少数极端 HEIC 文件可能解码失败返 422 `HEIC_DECODE_FAILED`。