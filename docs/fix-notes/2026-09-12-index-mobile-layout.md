# 观星指数页移动端适配问题定位与修复

> 定位时间：2026-09-12 ｜ 范围：`web/src/style/star-atlas.css`、`web/src/views/IndexView.vue`、
> `web/src/components/index/{CitySearch,TrendBars,MoonCard}.vue`
> 复现方式：真机截图 + headless Chrome（CDP `Emulation.setDeviceMetricsOverride`）逐元素量盒模型
> 触发场景：窄屏（≤430px）下**整块图版右侧内容被切掉**、报头三个 tab 竖排成「一字一行」

---

## 1. 现象（用户真机截图）

| # | 现象 | 现场 |
|---|---|---|
| 1 | 图版右侧内容被切：城市搜索的「查阅」、云量值的「98%」、等级印章都只露一半 | 手机窄屏 |
| 2 | 报头 `观星指数 / 星空识别 / 星座图鉴` 变成三列**竖排单字**，报头高 ~203px | 同上 |
| 3 | `FIG.` 与 `2` 被拆成两行；起止时间被拆成「起 日期 时」/「日期 时」错位 | 同上 |
| 4 | 等级描述（如「云深雨重，不宜观星」）一字一行竖排 | 同上 |

---

## 2. 根因（实测数据，非推测）

`main.frame` 上写着 `overflow-x: clip`（为了不让装饰罗盘产生横向滚动条）。
**它的副作用是：任何被撑宽的内容不会出现滚动条，而是直接被裁掉** —— 所以"溢出"在这套
CSS 里一律表现为"右侧内容凭空消失"。

用 CDP 在 390px 视口量到的关键盒模型（修复前）：

| 元素 | 实测 | 说明 |
|---|---|---|
| `.plate` | w=366（视口内容区仅 358） | **根因**：`@media (max-width:1000px)` 里 `.index-grid { grid-template-columns: 1fr }`，单列下 `1fr` 的最小尺寸是 `auto`，被 plate 内 **仪表盘 `.gauge-box`（宽 280px 固定）** 顶到 366px，整块图版横向溢出后被裁 |
| `.gauge-wrap` | `grid-template-columns: 280px 0px`，`.gauge-meta` w=0 | 桌面 `auto 1fr` 两列；窄屏 1fr 列被压到 0 宽 → 印章 `.seal`（111×111）溢出行外（实测 x=343.8→469.2）、等级描述一字一行 |
| `.brand` / `.mast-side.right` | 318 / **104.4** | 品牌 `min-content` 大（`STARWHISPER · ATLAS COELESTIS` + 30px「星✶语」），右侧栏被挤到 104px；`.nav-tab` 每格 33×88 → 单字竖排 |
| `.city-search` | `min-width: 260px` | 窄屏硬下限参与 plate 的最小宽度 |
| `.moon-sun` | `minmax(230px, 1fr)` | 同类硬下限 |

---

## 3. 修复清单

### 3.1 根因与容器（`IndexView.vue`）

- `.index-grid` 单列改 `minmax(0, 1fr)`：**消灭 plate 的 366px 最小宽度**（这是"整块被切"的唯一原因）。
- ≤620px 新增媒体查询：
  - `.gauge-wrap` → `minmax(0, 1fr)` 单列 + `justify-items: center`；印章 111→96px、字号 36→30px；等级描述 23→17px 居中；评级图例居中。
  - 起/止区间选择器：模板改为「起组 / 止组」两个 `.range-group`（整组换行，不再拆出「起 日期」与小时错位），提示文案 `flex: 1 1 100%` 独占一行。
  - 行动按钮竖排铺满（扩大点按目标）；`.city-title` 不再两端对齐（tag 曾跑到屏幕外）。
- `TrendBars.vue`：窄屏图体 190→150px、隐藏竖排纵轴说明、刻度字号收小（小时视图 24 槽标签曾经叠字）。

### 3.2 报头（`star-atlas.css`，≤620px）

- `.mast-top` 改纵向堆叠：品牌居中 + 导航独占一行；`.nav-tab { flex: 1 1 0; white-space: nowrap }`（**`nowrap` 是竖排单字的正解**）；隐藏 `.mast-meta` 与 `.page-mark` 压低 sticky 高度（203 → ~115px）。
- `.brand .zh` / `.f-title h1` / `.f-title .latin` 的**负右边距归零**：它是桌面用来抵消 `letter-spacing` 尾隙的，负边距会让盒宽超出容器；**报头在 `main.frame` 之外，不受 `overflow-x: clip` 保护**，窄屏会造成 body 级横向溢出。
- `.plate-cap` 内衬 16px、`.plate-body` 内衬 26→18/16px，把宽度还给内容。

### 3.3 其他组件

- `CitySearch.vue`：≤620px 去掉 `min-width: 260px`，输入框独占一行、两个按钮平分第二行。
- `MoonCard.vue`：≤620px `.moon-sun` 改显式 `minmax(0, 1fr)` 单列。

### 3.4 附带需求

- 小聆寄语改为**一句一行**（`<span>` 三行，`line-height: 1.9`），不再平铺折行到奇怪位置。

---

## 4. 验证

headless Chrome + CDP 在 **320 / 360 / 390 / 430 / 620 / 700 / 768 / 1000 / 1280 / 1600** 逐一量盒模型：

| 视口 | 修复前 | 修复后 |
|---|---|---|
| 320 | 图版 w=366、印章/描述/搜索框越界，`docSW=366` | **0 项越界**，`docSW=320` |
| 360 / 390 / 430 / 620 | 同上（图版 366 + 印章溢出） | **0 项越界**，`docSW==vw` |
| 700 ~ 1600 | 仅 `.brand` / `.f-title` 的负边距盒（桌面设计原意，不产生滚动条） | 与修复前一致（未回归） |

- 三个 tab（识别 / 指数 / 图鉴）在 390px 均无越界。
- `web/tests/mobileLayout.test.ts`（新增 7 例）：把断点契约写进测试（jsdom 无布局引擎，测的是"规则必须落在对应 `@media` 块内"，防以后被删/挪出断点）。
- `IndexView.test.ts` 新增 2 例：起/止成组结构、小聆寄语三行。
- 全量前端测试 `pnpm test` 265 例通过；`pnpm build`（vue-tsc + vite）通过。

---

## 5. 遗留与注意

- 真机截图里 `FIG. 2` 标题在 ≤320px 仍会折成两行（信息本身占满一行），属可接受折行。
- 本仓库 CSS 里"固定宽度 + `overflow-x: clip`"是隐患组合：**新加固定 `min-width` / `minmax(Apx, …)` 前，先用 320px 视口验证**，或直接跑 `web/tests/mobileLayout.test.ts` 的同类断言。
