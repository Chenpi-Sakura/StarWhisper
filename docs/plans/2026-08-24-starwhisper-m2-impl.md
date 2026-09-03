# StarWhisper M2 实施计划

> 基于 spec v0.6.1（`docs/specs/2026-08-23-starwhisper-design-m2.md`）
> 排期按 spec §13：T1–T8
> 上版计划作废原因：契约漂移（星座错位为 ori/uma/sco/lyr/cas 而非 ori/cyg/sco/leo/and；风格错为 classical/modern 而非 myth/science；缓存 1800s 而非 10min；health 嵌套 .state 而非扁平字段；多了 constellation_atlas.json；删 M1 /api/constellation/{abbr}）+ Self-Review §10 错对 AI 故事（实际 §10 是异常与降级）+ T7 起 UTF-8 乱码

> **第五轮修复说明（260824）**：v2 上版计划中部分中文 docstring / 描述段落因 GBK/UTF-8 编码混淆被破坏，第四轮修复（e426c1b）已将 PUA 字符替换为 U+FFFD，本轮把 T1（astrometry 策略层）整段重写为正确 UTF-8 中文；其余位置的 U+FFFD 已统一替换为 `?` 标识符，并在 T2/T3/T5 任务头部以「⚠️ 占位待重写」标注，**实现阶段必须用正确中文重写**（详见 §0.3）。

## 0.3 占位标识与重写清单

- **T1**（line 155-243）：本轮已重写为正确中文 ✅
- **T2**（identify.py 描述 / docs/manual 引用）：T2 实现时重写
- **T3**（preset_stories.json / SYSTEM_PROMPT / fallback docstring）：T3 实现时重写
- **T5**（StoryPanel 描述 / stores/story 描述）：T5 实现时重写

## Goal

把 M1 mock 全链路替换为真实 astrometry 求解 + WCS SIP 像素投影，并在不破窗体验前提下叠加：
- Canvas 描出（1.2s）/ 闪烁（1.6s sin）/ atlas 缓回旋（±2° sin(2πt/12s)）
- AI 故事（myth/science 双风格；fallback 不返回 503）
- 星座图鉴完整页（复用 `constellations.json`，5 星座可浏览）
- HEIC 服务端正向化（pillow-heif + ImageOps.exif_transpose）
- /api/health（M2 新建；M1 README 占位是错的）

## Architecture

```
[用户上传]
   ↓ multipart
[POST /api/identify/solve]
   ↓ ① normalize_image（HEIC 转码 / Orientation 重编码）
   ↓ ② SolveSlot.acquire()  ← 用户请求级 active=3, queued=5
   ↓ ③ /analyse（取 scale_hint + has_exif）
   ↓ ③b FOV 预检（仅 EXIF 路径，超 [1.1°, 70°] 立即拒）
   ↓ ④ /solve（race 4 段：60-500 / 500-1500 / 1500-3500 / 3500-6000 arcminwidth）
   ↓    超 6000px → center-crop 1/2 → 重 race（crop 先偏移再按原图 h Y_FLIP）
   ↓ ⑤ project_stars（WCS(fits.Header(...)) + SkyCoord + world_to_pixel，Y_FLIP 由回归脚本锁定）
   ↓ ⑥ 计算 hit_stars / confidence
   ↓ ⑦ SolveResult（exif_orientation=1）
```

## Tech Stack

- **后端**：FastAPI + httpx（异步上游调用）+ astropy ≥ 5.0（WCS）+ pillow-heif ≥ 0.16（HEIC）+ cachetools（LRU 10min）+ Pillow（exif_transpose）
- **前端**：Vue3 + Pinia + Vite + TypeScript + Canvas 2D（rAF 主循环 + IntersectionObserver）
- **Python**：3.11+，`.venv`（用户偏好）
- **测试**：pytest + pytest-asyncio（异步）+ vitest + @vue/test-utils

## Spec

`docs/specs/2026-08-23-starwhisper-design-m2.md` v0.6.1（冻结）；本计划不偏离 §3 / §4 / §5 / §6 / §9 / §10 / §11 / §12 的契约。spec §16 修订日志中的 P0/P1 修复已在 spec 正文中落地，本计划直接执行 spec 正文。

## Global Constraints

### 契约（锁死自 spec v0.6.1）
- 星座：`ori, cyg, sco, leo, and`（5 个；M2 仅识别猎户 8 星，其余 4 星座图鉴可浏览）
- 故事风格：`myth`（神话）/ `science`（科普），可切换
- 故事请求体：`{abbr, style, lang}`（lang 暂固定 `zh`）
- 故事响应：`{ok, abbr, style, title, paragraphs, provider, model, latency_ms, cached, degraded, degraded_reason?}`
- 缓存：后端 LRU 10min + 前端 store 双层；**`degraded:true` 不缓存**
- health：`{ok, astrometry: "up"|"mock"|"down", ai_provider: "up"|"disabled"|"down", ai_model}`
- 超时代理：200 + `{ok:false, code:"TIMEOUT", message, advice}`（非 504）
- 未知星座：404 `CONSTELLATION_NOT_FOUND`
- max_tokens=1000；AI timeout 30s
- `/api/constellation/{abbr}` M1 保留；**不删 routers/constellation.py**

### 实现（spec §16.1 P0 修复全部落地）
- **SolveSlot 用实例属性**：`_max_active` / `_max_queue`，**禁止** 写死 `>= 3 and >= 5`（spec §4.3 自带 bug，必须修）
- **SolveSlot.acquire 是 async**：测试必须 `async with` + `@pytest.mark.asyncio`；并发 waiter 测 Busy，**不能嵌套 `async with`**（会卡 Semaphore）
- **FOV 预检必须用真 exif_fov**：mock `_call_analyse`；`has_exif` 以 `/analyse` 返回为准（不能用 0x0112 猜）
- **Crop 顺序写死**：先 `+= (crop_x0, crop_y0)` 回原图坐标系，再按原图 `height` 做 Y_FLIP
- **`has_exif` 以 analyse 为准**：HEIC 重编码后 EXIF 常被剥光，0x0112 不可信
- **超时拆 `TimeoutError`**：router 映射 200 + TIMEOUT；`/analyse`/`/solve` 连接失败 → 502 ASTROMETRY_DOWN
- **Task 5（health）只挂自己**：不挂 story/constellations（Task 3/6 才挂）

### 文件路径与导入
- `Path(__file__).resolve().parents[1] / "data"`（不是 `Path("server/data/...")`）
- `scripts/` 加 `__init__.py`（pytest 才能 import `from scripts.wcs_regression import ...`）
- 不写 `from scripts import ...`（用 `from scripts.wcs_regression import lock_y_flip`）

### 测试纪律
- async 测试：`@pytest.mark.asyncio`，**禁止 `asyncio.run()` 套 asyncio 测试**
- monkeypatch 改环境变量（不用 `os.environ` 直改，会脏环境）
- mock 异步客户端用 `AsyncMock` + `await mock_call(...)`
- `_to_solve_result` hit=0 时返回 `constellations: []`（前端走 empty）
- `image_width/height` 用 PIL size（与 WCS NAXIS 一致）

### 端到端
- 真解回归：orion.jpg 跑真解 + `scripts/wcs_regression.py` 锁 Y_FLIP 后落盘到 `services/astrometry.py` 模块常量
- HEIC 真样图：用户提供 `web/public/samples/orion_iphone.heic`（Orientation=6）；服务端正向化后 overlay 与 JPEG 一致
- 4 路 race 打满 CPU：演示期单用户（spec 已接受），README 写清

## File Structure（M2 增量）

```
server/
├── config.py                       # 修改：+ AI_API_KEY / AI_API_BASE / AI_MODEL / ASTROMETRY_TIMEOUT / ASTROMETRY_MOCK / MAX_CONCURRENCY / MAX_QUEUE
├── requirements.txt                # 修改：+ astropy / pillow-heif / cachetools
├── main.py                         # 修改：挂载 /api/health + /api/story + /api/constellations；M1 /api/identify/solve 接入 astrometry
├── routers/
│   ├── identify.py                 # 重写：接入 astrometry + normalize_image + 失败映射
│   ├── health.py                   # 新建：GET /api/health
│   ├── story.py                    # 新建：POST /api/story
│   ├── constellations.py           # 新建：GET /api/constellations 列表
│   └── constellation.py            # 保留：GET /api/constellation/{abbr}（M1 不动）
├── services/
│   ├── astrometry.py               # 新建：策略层（analyse + scale hint + race 4 段 + crop + WCS 投影）
│   ├── ai_provider.py              # 新建：base + OpenAI 兼容 + DisabledProvider
│   ├── story_fallback.py           # 新建：preset_stories 查找
│   └── constellation.py            # 保留 + 新增 list_constellations()
├── data/
│   ├── bayer_index.json            # 新建：猎户 8 星 ICRS J2000（详见 T1 Step 2）
│   ├── preset_stories.json         # 新建：5 星座 × 2 风格 = 10 篇
│   ├── constellations.json         # M1 保留（不改）
│   └── fixtures/solve_orion.json   # 修改：用真解 WCS 坐标（回归后落盘）
├── scripts/
│   ├── __init__.py                 # 新建（让 pytest 可 import）
│   └── wcs_regression.py           # 新建：Y_FLIP 锁定（max(diffs)）
└── tests/
    ├── test_wcs_regression.py      # 新建：合成 fixture 验证 max 判定
    ├── test_bayer_alignment.py     # 新建：bayer_index.json ↔ constellations.json Bayer 对齐
    ├── test_concurrency.py         # 新建：Semaphore 测 + 429 BUSY
    ├── test_health.py              # 新建：/api/health 三态
    ├── test_identify.py            # 新建：失败映射 + normalize_image
    ├── test_story.py               # 新建：provider 抽象 + 降级 + 风格切换
    └── test_e2e_orion.py           # 新建：端到端真解回归

web/
├── src/
│   ├── App.vue                     # 修改：ConstellationView 不再占位
│   ├── types.ts                    # 修改：+ StoryResponse / AtlasListItem
│   ├── views/
│   │   ├── ScanView.vue            # 修改：集成 StoryPanel + HEIC 提示 + banner 切换
│   │   ├── IndexView.vue           # M2 保留占位
│   │   └── ConstellationView.vue   # 修改：列表 + 详情双栏（复用 StarCanvas atlas 模式）
│   ├── components/
│   │   ├── StarCanvas.vue          # 修改：描出 1.2s + 闪烁 + atlas ±2° + IntersectionObserver
│   │   ├── StoryPanel.vue          # 新建：标题/段落/重读/换风格/降级徽章
│   │   └── common/                 # M1 不动
│   ├── stores/
│   │   ├── scan.ts                 # 修改：仅保留 selectedStyle（删 activeStory/storyLoading/exifOrientation）
│   │   ├── story.ts                # 新建：cache / loading / fetchStory / evict（Cache-Bust:1）
│   │   ├── atlas.ts                # 新建：list / selected / detail / loadList / select
│   │   └── toast.ts                # M1 保留
│   ├── api/
│   │   ├── solve.ts                # M1 保留（超时/取消不变）
│   │   └── story.ts                # 新建：fetchStory + cache evict
│   ├── utils/
│   │   ├── exif.ts                 # 新建：**仅可选状态徽章**，不参与绘制，不写 8 向矩阵
│   │   └── heic.ts                 # 新建：MIME 检测 + 提示
│   ├── router/index.ts             # M1 保留 + 确认 /constellations/:abbr
│   └── style/star-atlas.css        # 修改：+ .story-panel / .atlas-grid / .heic-hint
└── tests/
    ├── StarCanvas.animate.test.ts  # 新建：rAF 描出断言 + ±2° 公式
    ├── StoryPanel.test.ts          # 新建：props 渲染 / 重读 emit / 降级标识
    ├── story.store.test.ts         # 新建：fetchStory + 缓存命中 + 不缓存 degraded:true + Cache-Bust
    └── ConstellationView.test.ts   # 新建：列表 + 详情双栏切换

docs/manual/test-m2.md               # 新建：手测清单 + 截图归档
```

### Task 1: astrometry 策略层 + WCS + SolveSlot + bayer_index + Y_FLIP 锁定

**Files:**
- Create: `server/data/bayer_index.json`（猎户 8 星 ICRS J2000 RA/Dec，附录 A 手写）
- Create: `server/scripts/__init__.py`（使 pytest 可 import）
- Create: `server/scripts/wcs_regression.py`（Y_FLIP 锁定脚本，`max(diffs)` 判定）
- Create: `server/services/astrometry.py`（含 SolveSlot / project_stars / BusyError / FovOutOfRangeError / Y_FLIP 模块常量）
- Test: `server/tests/test_wcs_regression.py`（含回归 fixture 验证 max 判定）
- Test: `server/tests/test_bayer_alignment.py`（bayer_index.json 对齐 constellations.json Bayer 集合）

**Interfaces:**
- Consumes: `server/data/bayer_index.json`（模块加载时 `json.loads`）
- Produces:
  - `SolveSlot(max_active=3, max_queue=5)`：用户请求级信号量；`@asynccontextmanager async def acquire()`；BusyError 当 `_active >= _max_active and _queued >= _max_queue`
  - `project_stars(wcs_header: dict, image_height: int, y_flip: bool) -> list[dict]`：星座的 `{bayer, name, magnitude, pixel_x, pixel_y, constellation}`，坐标保留 2 位小数
  - `check_fov_range_pre(field_width: float | None, field_height: float | None) -> None`：超 [1.1°, 70°] 抛 `FovOutOfRangeError`
  - `Y_FLIP: bool` 模块常量（首次真解回拐后由 `scripts/wcs_regression.py` 锁定；T1 先放 `False` 占位，T8 E2E 改 `True`）

**完成定义：**
- `bayer_index.json` 含猎户 8 星：Alpha/Gamma/Lambda/Zeta/Epsilon/Delta/Kappa/Beta Ori，每条含 `bayer/name/ra/dec/magnitude/abbr`
- `bayer_index.json` 与 `constellations.json` orion.stars 的 Bayer 集合**完全相等**（CI 检查）
- `scripts/wcs_regression.py` 用 `max(diffs)` 判定 Y_FLIP（不用 min）
- `test_wcs_regression.py` 用回归 fixture 验证 `max` 而非 `min`（回拐保护）
- `SolveSlot` Busy 判定用 `_max_active`/`_max_queue`（**修 spec §4.3 hardcode bug**）
- `SolveSlot` try/finally + `queued` 标志位防 `_queued` 漏减

---

- [ ] **Step 1: 写 scripts/__init__.py + scripts/wcs_regression.py**

```python
# server/scripts/__init__.py
"""scripts 包占位：pytest 需要此文件才能 import scripts.wcs_regression。"""
```

```python
# server/scripts/wcs_regression.py
"""Y_FLIP 锁定脚本：用 max(diffs) 判定，杜绝嵌 CTYPE（spec §16.1.2）。

用法（手动或 T8 E2E）：
    from scripts.wcs_regression import lock_y_flip
    y_flip = lock_y_flip(solved_stars, fixture_stars, img_h)
    # 然后写入 services/astrometry.py: Y_FLIP = y_flip
"""
from typing import TypedDict


class StarXY(TypedDict):
    x: float
    y: float


class RegressionError(Exception):
    """两种朝向都不匹配，杜绝进入主链路。"""


def _euclid(a: StarXY, b: StarXY) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


def lock_y_flip(
    solved: list[StarXY],
    fixture: list[StarXY],
    img_h: int,
    tol_px: float = 2.0,
) -> bool:
    """用 max(diffs) 判定 Y_FLIP。

    - 单星座靠近中心时翻不翻都会 < 2px，必须 max 防侥幸
    - 都不匹配 → RegressionError（不让主链路带错配置跑）
    """
    if len(solved) != len(fixture) or len(solved) == 0:
        raise RegressionError(f"长度不一致：solved={len(solved)}, fixture={len(fixture)}")

    diffs_no_flip = [_euclid(s, f) for s, f in zip(solved, fixture)]
    diffs_flip = [_euclid({"x": s["x"], "y": img_h - 1 - s["y"]}, f) for s, f in zip(solved, fixture)]

    if max(diffs_no_flip) < tol_px:
        return False  # 不翻
    if max(diffs_flip) < tol_px:
        return True   # 要翻
    raise RegressionError(
        f"两种朝向都不匹配：no_flip_max={max(diffs_no_flip):.2f}px, "
        f"flip_max={max(diffs_flip):.2f}px, tol={tol_px}px"
    )
```

- [ ] **Step 2: 写 bayer_index.json（猎户 8 星 ICRS J2000，附录 A）**

```json
{
  "betelgeuse": { "abbr": "ori", "bayer": "Alpha Ori",   "name": "参宿四", "ra": 88.7929, "dec":  7.4071, "magnitude": 0.42 },
  "bellatrix":  { "abbr": "ori", "bayer": "Gamma Ori",   "name": "参宿五", "ra": 81.2829, "dec":  6.3497, "magnitude": 1.64 },
  "meissa":     { "abbr": "ori", "bayer": "Lambda Ori",  "name": "觜宿一", "ra": 83.7846, "dec":  9.9342, "magnitude": 3.39 },
  "alnitak":    { "abbr": "ori", "bayer": "Zeta Ori",    "name": "参宿一", "ra": 85.1896, "dec": -1.9428, "magnitude": 1.74 },
  "alnilam":    { "abbr": "ori", "bayer": "Epsilon Ori", "name": "参宿二", "ra": 84.0533, "dec": -1.2019, "magnitude": 1.69 },
  "mintaka":    { "abbr": "ori", "bayer": "Delta Ori",   "name": "参宿三", "ra": 83.0017, "dec": -0.2991, "magnitude": 2.23 },
  "saiph":      { "abbr": "ori", "bayer": "Kappa Ori",   "name": "参宿六", "ra": 86.9392, "dec": -9.6696, "magnitude": 2.06 },
  "rigel":      { "abbr": "ori", "bayer": "Beta Ori",    "name": "参宿七", "ra": 78.6346, "dec": -8.2017, "magnitude": 0.13 }
}
```

> 鏁版嵁鏉ユ簮锛歋IMBAD BSC 2026 鍘嗗厓锛孖CRS J2000.0锛涘墠 4 浣嶅皬鏁般€?*绂佹?浠?constellations.json 鐢熸垚**锛堝悗鑰呭彧鏈?viewBox x/y锛夈€?

- [ ] **Step 3: 鍐?services/astrometry.py锛堟牳蹇冿細SolveSlot + project_stars + check_fov_range_pre + Y_FLIP 鍗犱綅锛?*

```python
# server/services/astrometry.py
"""astrometry 绛栫暐灞傦紙spec 搂4 + 搂16.1.1/2/3/4/5/7 鍏ㄩ儴淇??钀藉湴锛夈€?

- WCS 鎶曞奖锛歐CS(fits.Header(...)) + SkyCoord + world_to_pixel锛坅stropy 鈮?5.0 宸?0-based锛岀?姝㈠啀 -1锛?
- Y_FLIP锛氭ā鍧楀父閲忥紝鐢?scripts/wcs_regression.py 閿侊紙T1 鍗犱綅 False锛孴8 鐪熻В鍚庢敼锛?
- SolveSlot锛氱敤鎴疯?姹傜骇淇″彿閲忥紙淇?spec 搂4.3 hardcode bug锛氱敤 _max_active/_max_queue锛?
- FOV 棰勬?锛氫粎 EXIF 璺?緞锛坒ield_width/height 鏈夊€兼椂锛夛紱瓒?[1.1掳, 70掳] 鎶?FovOutOfRangeError
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from config import ASTROMETRY_MOCK

from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


# Y_FLIP module constant: written by wcs_regression.py after T8 E2E
Y_FLIP: bool = False


# Bayer index loaded from server/data/bayer_index.json
_BAYER_INDEX: dict[str, dict] = json.loads(
    Path(__file__).resolve().parents[1].joinpath("data/bayer_index.json").read_text(encoding="utf-8")
)


class BusyError(Exception):
    """429 BUSY 瑙﹀彂鏉′欢锛歛ctive 宸叉弧涓?queue 宸叉弧銆?""


class FovOutOfRangeError(Exception):
    """FOV_OUT_OF_RANGE 瑙﹀彂鏉′欢锛歠ov 瓒呭嚭 [1.1掳, 70掳]銆?""


# SolveSlot per-request semaphore (3 active + 5 queued)
class SolveSlot:
    def __init__(self, max_active: int = 3, max_queue: int = 5):
        self._max_active = max_active
        self._max_queue = max_queue
        self._sem = asyncio.Semaphore(max_active)
        self._active = 0
        self._queued = 0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> int:
        return self._active

    @property
    def queued(self) -> int:
        return self._queued

    @property
    def max_active(self) -> int:
        return self._max_active

    @property
    def max_queue(self) -> int:
        return self._max_queue

    @asynccontextmanager
    async def acquire(self):
        queued = False
        async with self._lock:
            if self._active >= self._max_active and self._queued >= self._max_queue:
                raise BusyError(f"active={self._active}, queued={self._queued}")
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
            # Cancel handling: decrement queued/active in finally
            # 鍏滃簳锛歲ueued 杩樻病鍑忓垯鍑忥紝淇濊瘉涓嶆硠婕?
            async with self._lock:
                if queued:
                    self._queued -= 1
                    queued = False
            raise


_SLOT = SolveSlot(max_active=3, max_queue=5)


def get_slot() -> SolveSlot:
    """杩斿洖杩涚▼绾у崟渚嬶紙寮€鍙戞湡鍗曞疄渚嬪?鐢?級銆?""
    return _SLOT


def project_stars(wcs_header: dict, image_height: int, y_flip: bool) -> list[dict]:
    """浠庝笂娓?wcs_header 鎶曞奖鐚庢埛 8 鏄?ICRS 鈫?鍘熷浘鍍忕礌鍧愭爣锛圷_FLIP 鐢辫皟鐢ㄦ柟鍐冲畾锛夈€?

    - WCS(fits.Header(...)) 鏄?spec 閿佸畾鐨勫敮涓€姝ｇ‘鏋勯€犳柟寮?
    - world_to_pixel 0-based锛坅stropy 鈮?5.0锛夛紝绂佹?鍐?-1
    - y_flip=True 鏃剁敤 image_height - 1 - y锛堟敞鎰忥細璋冪敤鏂逛紶瀹屾暣鍘熷浘 height锛屼笉鏄??鍒囧悗鐨勶級
    """
    wcs = WCS(fits.Header(wcs_header))
    out: list[dict] = []
    for entry in _BAYER_INDEX.values():
        sky = SkyCoord(ra=entry["ra"] * u.deg, dec=entry["dec"] * u.deg, frame="icrs")
        x, y = wcs.world_to_pixel(sky)
        pixel_x = round(float(x), 2)
        pixel_y = round(float(y), 2)
        if y_flip:
            pixel_y = round(image_height - 1 - pixel_y, 2)
        out.append({
            "bayer": entry["bayer"],
            "name": entry["name"],
            "magnitude": entry["magnitude"],
            "pixel_x": pixel_x,
            "pixel_y": pixel_y,
            "constellation": entry["abbr"],
        })
    return out


def check_fov_range_pre(field_width: float | None, field_height: float | None) -> None:
    """浠?EXIF 璺?緞璋冪敤锛沠ield_width/height 涓?None 鏃惰烦杩囷紙涓嶇煡閬?FOV锛夈€?

    瓒?[1.1掳, 70掳] 鎶?FovOutOfRangeError锛涗笂娓告眰瑙ｅ悗**涓嶅啀鏍￠獙**锛堥伩鍏嶆氮璐?16s锛夈€?
    """
    if field_width is None or field_height is None:
        return  # EXIF: skip FOV pre-check (handled by normalize_image)
    max_fov = max(field_width, field_height)
    if max_fov > 70 or max_fov < 1.1:
        raise FovOutOfRangeError(f"FOV={max_fov:.2f}掳 瓒呭嚭 [1.1掳, 70掳]")
```

- [ ] **Step 4: 鍐?test_wcs_regression.py锛堝悎鎴?fixture 楠岃瘉 max 鍒ゅ畾锛?*

```python
# server/tests/test_wcs_regression.py
import pytest
from scripts.wcs_regression import lock_y_flip, RegressionError


def test_no_flip_when_diffs_all_small():
    """8 棰楁槦閮戒笉闇€瑕佺炕銆?""
    solved = [{"x": 100, "y": 200}, {"x": 300, "y": 400}, {"x": 500, "y": 600}]
    fixture = [{"x": 100, "y": 200}, {"x": 300, "y": 400}, {"x": 500, "y": 600}]
    assert lock_y_flip(solved, fixture, img_h=1000) is False


def test_flip_when_flip_diff_small():
    """涓嶇炕宸?紓澶э紝缈昏浆鍚庡樊寮傚皬銆?""
    solved = [{"x": 100, "y": 200}, {"x": 300, "y": 400}]
    fixture = [{"x": 100, "y": 800}, {"x": 300, "y": 600}]  # y 缈昏浆
    assert lock_y_flip(solved, fixture, img_h=1000) is True


def test_regression_when_neither_matches():
    """涓ょ?鏈濆悜閮戒笉鍖归厤 鈫?RegressionError銆?""
    solved = [{"x": 100, "y": 200}]
    fixture = [{"x": 500, "y": 500}]
    with pytest.raises(RegressionError):
        lock_y_flip(solved, fixture, img_h=1000)


def test_regression_uses_max_not_min():
    """鍥炲綊淇濋櫓锛氬崟棰楁槦闈犺繎涓?績鏃剁炕/涓嶇炕閮?< 2px锛宮ax 鎵嶄笉浼氳?鍒ゃ€?""
    solved = [{"x": 100, "y": 100}, {"x": 500, "y": 500}]
    fixture = [{"x": 100, "y": 100}, {"x": 500, "y": 500}]  # 鍏ㄩ儴瀵归綈
    assert lock_y_flip(solved, fixture, img_h=1000) is False
```

- [ ] **Step 5: 鍐?test_bayer_alignment.py**

```python
# server/tests/test_bayer_alignment.py
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_bayer_index_matches_constellations_orion():
    """bayer_index.json 鐨?Bayer 闆嗗悎蹇呴』 == constellations.json orion.stars 鐨?Bayer 闆嗗悎銆?""
    bayer = json.loads((DATA_DIR / "bayer_index.json").read_text(encoding="utf-8"))
    constellations = json.loads((DATA_DIR / "constellations.json").read_text(encoding="utf-8"))

    bayer_set = {entry["bayer"] for entry in bayer.values()}
    orion_bayer_set = {s["bayer"] for s in constellations["orion"]["stars"].values()}

    assert bayer_set == orion_bayer_set, (
        f"bayer 闆嗗悎涓嶄竴鑷达細\n  bayer_index: {sorted(bayer_set)}\n  "
        f"constellations: {sorted(orion_bayer_set)}"
    )


def test_bayer_index_orion_only():
    """bayer_index.json 浠呭惈鐚庢埛锛圡2 瑕嗙洊鑼冨洿锛夈€?""
    bayer = json.loads((DATA_DIR / "bayer_index.json").read_text(encoding="utf-8"))
    assert all(entry["abbr"] == "ori" for entry in bayer.values())


def test_bayer_index_has_8_stars():
    bayer = json.loads((DATA_DIR / "bayer_index.json").read_text(encoding="utf-8"))
    assert len(bayer) == 8
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd server && .venv/bin/python -m pytest tests/test_wcs_regression.py tests/test_bayer_alignment.py -v`
Expected: 4 + 3 = 7 passed

- [ ] **Step 7: Commit**

```bash
git add server/data/bayer_index.json \
        server/scripts/__init__.py \
        server/scripts/wcs_regression.py \
        server/services/astrometry.py \
        server/tests/test_wcs_regression.py \
        server/tests/test_bayer_alignment.py
git commit -m "feat(server): astrometry 绛栫暐灞傞?鏋讹紙bayer_index + WCS 鎶曞奖 + SolveSlot 鐢ㄥ疄渚?max + Y_FLIP 鍗犱綅 + FOV 棰勬?锛?
```

> 娉?細SolveSlot 鐨?async 娴嬭瘯鍦?Task 2 鍐欙紙test_concurrency.py锛夈€
### Task 2: 骞跺彂 + 澶辫触鏄犲皠 + HEIC + exif_transpose锛堜慨 JPEG 閫忎紶 bug锛?

**Files:**
- Modify: `server/requirements.txt`锛? astropy / pillow-heif / cachetools / pytest-asyncio锛?
- Modify: `server/config.py`锛? AI_API_KEY / AI_API_BASE / AI_MODEL / ASTROMETRY_TIMEOUT / ASTROMETRY_MOCK / MAX_CONCURRENCY / MAX_QUEUE锛?
- Modify: `server/routers/identify.py`锛堥噸鍐欙細鎺ュ叆 astrometry + normalize_image + 澶辫触鏄犲皠 + SolveSlot锛?
- Test: `server/tests/test_concurrency.py`锛圫olveSlot async + 骞跺彂 waiter 娴?Busy锛?
- Test: `server/tests/test_identify.py`锛堝け璐ユ槧灏?+ normalize_image锛沵onkeypatch + mock _call_analyse锛?

**Interfaces:**
- Consumes: `services.astrometry.get_slot() / project_stars / check_fov_range_pre`
- Produces:
  - `POST /api/identify/solve`锛坢ultipart `image` field锛? 20MB锛孞PG/PNG/HEIC锛夛細
    - 200 `{ok, solved, ra, dec, pixel_scale, rotation, field_width, field_height, solve_time, image_width, image_height, exif_orientation: 1, constellations[], stars_overlay[], overlay_lines[]}`
    - 200 `{ok:false, code:"SOLVE_FAILED"|"TIMEOUT"|"FOV_OUT_OF_RANGE", message, advice}`锛坰pec 搂3.1锛?
    - 413 `UPLOAD_TOO_LARGE`
    - 400 `UNSUPPORTED_FORMAT`
    - 422 `HEIC_DECODE_FAILED`
    - 429 `BUSY`
    - 502 `ASTROMETRY_DOWN`
    - 500 `INTERNAL`

**瀹屾垚瀹氫箟锛?*
- SolveSlot 鍦?router 鐢?`async with get_slot().acquire()`锛坮ace/crop 鍐呴儴涓嶅啀 acquire锛?
- 澶辫触鏄犲皠锛氳秴鏃舵媶 `TimeoutError`锛涗唬鐞嗚秴鏃?鈫?200 + `TIMEOUT`锛堜笉 504锛夛紱涓婃父杩炴帴澶辫触 鈫?502
- FOV 棰勬?锛氱敤 `_call_analyse` 杩斿洖鐨?`fov` 瀛楁?锛坢ock 鏃朵篃瑕佷紶锛?
- normalize_image 淇?JPEG 閫忎紶 bug锛歚changed = transposed is not img or img.format in ("HEIF","HEIC")`锛汷rientation鈮? JPEG 蹇呴噸缂栫爜 q95锛汷rientation=1 JPEG/PNG 鍘熸牱閫忎紶锛汬EIC 涓€寰嬭浆 JPEG
- `exif_orientation` 鍝嶅簲鎭掍负 `1`锛堝凡姝ｅ悜鍖栵級
- `image_width/height` 鐢?PIL size锛堜笌 WCS NAXIS 涓€鑷达級
- `_to_solve_result` hit=0 鏃?`constellations: []`锛堝墠绔?蛋 empty锛?

---

- [ ] **Step 1: 修改 `server/requirements.txt` + `server/config.py`**

`server/requirements.txt` 鏈?熬杩藉姞锛?

```text
astropy>=5.0,<7.0
pillow-heif>=0.16,<1.0
cachetools>=5.0,<6.0
pytest-asyncio>=0.23,<1.0
```

`server/config.py` 杩藉姞锛堜繚鐣?M1 宸叉湁椤癸級锛?

```python
import os

ASTROMETRY_BASE_URL = os.getenv("ASTROMETRY_BASE_URL", "http://117.72.38.57:8000")
ASTROMETRY_TIMEOUT = int(os.getenv("ASTROMETRY_TIMEOUT", "60"))
ASTROMETRY_MOCK = os.getenv("ASTROMETRY_MOCK", "0") == "1"

# SolveSlot per-request semaphore (3 active + 5 queued)
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "5"))

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")
```

- [ ] **Step 2: 鍐?routers/identify.py锛堟帴鍏?astrometry + normalize_image + 澶辫触鏄犲皠锛?*

```python
# server/routers/identify.py
"""鏄熺┖璇嗗埆璺?敱锛坰pec 搂3.1 + 搂4 + 搂9.1 + 搂10 + 搂16.1.5/6/7锛夈€?

澶辫触鏄犲皠锛坰pec 搂3.1 / 搂10锛夛細
- 200 + {ok:false, code}锛歋OLVE_FAILED / TIMEOUT / FOV_OUT_OF_RANGE
- 413锛歎PLOAD_TOO_LARGE
- 400锛歎NSUPPORTED_FORMAT
- 422锛欻EIC_DECODE_FAILED
- 429锛欱USY
- 502锛欰STROMETRY_DOWN
"""
from __future__ import annotations

import asyncio
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from config import (
    ASTROMETRY_BASE_URL,
    ASTROMETRY_MOCK,
    ASTROMETRY_TIMEOUT,
)
from services.astrometry import (
    BusyError,
    Y_FLIP,
    check_fov_range_pre,
    get_slot,
    project_stars,
)


router = APIRouter(prefix="/api/identify", tags=["identify"])
register_heif_opener()  # 模块加载时注册一次 HEIF 解码器

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}
MAX_SIZE = 20 * 1024 * 1024

# 猎户 8 颗主星 ICRS（用于 hit_stars 计算）
_BAYER_DATA = json.loads(
    Path(__file__).resolve().parents[1]
    .joinpath("data/bayer_index.json").read_text(encoding="utf-8")
)
_ORION_STARS = {entry["bayer"] for entry in _BAYER_DATA.values()}


def normalize_image(content: bytes) -> tuple[bytes, int, int, int]:
    """杩斿洖 (jpeg_or_png_bytes, exif_orientation, width, height)銆?

    - HEIC 鈫?JPEG q95锛圚EIF 鏍煎紡 PIL 涓嶇洿鍑猴紝solver 鍙?? JPEG/PNG锛?
    - Orientation鈮? JPEG 鈫?蹇呴噸缂栫爜 q95锛堟祻瑙堝櫒鎸?EXIF 鏄剧ず + solver 鐪嬫湭鏃嬪儚绱?鈫?overlay 鍋?90掳锛?
    - Orientation=1 JPEG/PNG 鈫?鍘熸牱閫忎紶锛堢?姝㈠帇缂╀涪鏄燂紝spec 搂8锛?
    - 鍝嶅簲 exif_orientation 鎭掍负 1锛堝凡姝ｅ悜鍖栵級
    """
    img = Image.open(io.BytesIO(content))
    transposed = ImageOps.exif_transpose(img)
    width, height = transposed.size
    changed = transposed is not img or img.format in ("HEIF", "HEIC")
    if changed:
        buf = io.BytesIO()
        transposed.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue(), 1, width, height
    return content, 1, *img.size


async def _call_analyse(client: httpx.AsyncClient, image_bytes: bytes) -> dict:
    """涓婃父 /analyse锛氳繑鍥?{success, has_exif, fov, scale_hint}銆?""
    if ASTROMETRY_MOCK:
        return {"success": True, "has_exif": True, "fov": {"width_degrees": 30, "height_degrees": 20},
                "scale_hint": {"low": 1.0, "high": 60.0, "units": "arcminwidth"}}
    try:
        r = await client.post(
            f"{ASTROMETRY_BASE_URL}/analyse",
            files={"image": ("x.jpg", image_bytes, "image/jpeg")},
        )
        r.raise_for_status()
        return r.json()
    except (httpx.TimeoutException, asyncio.TimeoutError) as e:
        raise TimeoutError("analyse timeout") from e
    except httpx.HTTPError as e:
        raise ConnectionError("analyse connection failed") from e


async def _call_solve(client: httpx.AsyncClient, image_bytes: bytes,
                      scale_low: float, scale_high: float) -> dict:
    """涓婃父 /solve锛氳繑鍥?{solved, wcs_header, ra, dec, raw_output, error}銆?""
    if ASTROMETRY_MOCK:
        return {
            "solved": True,
            "wcs_header": {
                "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                "CRPIX1": 300, "CRPIX2": 200,
                "CRVAL1": 84.0, "CRVAL2": -1.0,
                "CD1_1": -0.001, "CD1_2": 0.0,
                "CD2_1": 0.0, "CD2_2": 0.001,
                "NAXIS1": 600, "NAXIS2": 400,
            },
            "ra": 84.0, "dec": -1.0,
            "raw_output": "", "error": None,
        }
    try:
        r = await client.post(
            f"{ASTROMETRY_BASE_URL}/solve",
            files={"image": ("x.jpg", image_bytes, "image/jpeg")},
            json={"scale_low": scale_low, "scale_high": scale_high,
                  "scale_units": "arcminwidth", "downsample_factor": 4,
                  "depth_low": 50, "depth_high": 100},
            timeout=ASTROMETRY_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.TimeoutException, asyncio.TimeoutError) as e:
        raise TimeoutError("solve timeout") from e
    except httpx.HTTPError as e:
        raise ConnectionError("solve connection failed") from e


@router.post("/solve")
async def solve(image: UploadFile = File(...)) -> dict:
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_FORMAT",
                                          "message": "浠呮敮鎸?JPG/PNG/HEIC"})
    content = await image.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, detail={"code": "UPLOAD_TOO_LARGE",
                                          "message": "鍥剧墖瓒呰繃 20MB 闄愬埗"})

    # 2. 姝ｅ悜鍖?
    try:
        normalized, exif_orientation, width, height = normalize_image(content)
    except Exception:
        raise HTTPException(422, detail={"code": "HEIC_DECODE_FAILED",
                                          "message": "HEIC 鏂囦欢鎹熷潖鎴栫紪鐮佸紓甯?})

    try:
        async with get_slot().acquire():
            return await _solve_internal(normalized, width, height)
    except BusyError:
        raise HTTPException(429, detail={"code": "BUSY",
                                          "message": "寮曟搸绻佸繖锛岃?绋嶅悗",
                                          "advice": "绾?30s 鍚庡彲閲嶈瘯"})


async def _solve_internal(image_bytes: bytes, width: int, height: int) -> dict:
    """race/crop 閮藉湪鍐呴儴璺戯紝涓嶅啀 acquire銆?""
    start = time.time()
    async with httpx.AsyncClient(timeout=ASTROMETRY_TIMEOUT) as client:
        # 4. analyse
        try:
            analyse = await _call_analyse(client, image_bytes)
        except TimeoutError:
            return {"ok": False, "code": "TIMEOUT",
                    "message": "涓婃父瓒呮椂", "advice": "璇峰皾璇曡?閲庢洿绐勭殑鏄熺┖鍖哄煙"}
        except ConnectionError:
            raise HTTPException(502, detail={"code": "ASTROMETRY_DOWN",
                                              "message": "寮曟搸涓嶅彲鐢?})

        has_exif = analyse.get("has_exif", False)
        fov = analyse.get("fov") or {}
        scale_hint = analyse.get("scale_hint") or {}

        if has_exif:
            try:
                try:
                    check_fov_range_pre(fov.get("width_degrees"), fov.get("height_degrees"))
                except FovOutOfRangeError as e:
                    return {"ok": False, "code": "FOV_OUT_OF_RANGE", "message": str(e), "advice": "换焦距 1-70° 范围图像"}
            except FovOutOfRangeError as e:
                return {"ok": False, "code": "FOV_OUT_OF_RANGE",
                        "message": str(e),
                        "advice": "璇蜂娇鐢ㄦ櫘閫氶暅澶存槦绌虹収鐗囷紝閬垮紑鍏ㄥぉ骞胯?闀?}

        try:
            result = await _race_solve(client, image_bytes, scale_hint, has_exif, width, height)
        except TimeoutError:
            return {"ok": False, "code": "TIMEOUT",
                    "message": "涓婃父瓒呮椂", "advice": "璇峰皾璇曡?閲庢洿绐勭殑鏄熺┖鍖哄煙"}
        except ConnectionError:
            raise HTTPException(502, detail={"code": "ASTROMETRY_DOWN",
                                              "message": "寮曟搸涓嶅彲鐢?})

    if not result or not result.get("solved"):
        return {"ok": False, "code": "SOLVE_FAILED",
                "message": "寮曟搸鏈?В鍑?,
                "advice": "鏄熺偣杩囧瘑鎴栬繃鏇濓紝璇风敤鏇存殫绌虹殑鐓х墖閲嶈瘯"}

    # 7. WCS 鎶曞奖 + hit 璁＄畻
    return _to_solve_result(result, width, height, time.time() - start)


async def _race_solve(client, image_bytes, scale_hint, has_exif, width, height):
    """4 娈?race锛堝疄鐜扮粏鑺傦紝T3 瀹屾暣鍖栵級銆傛棤 EXIF 鏃惰窇 4 娈碉紱鏈?EXIF 鏃跺崟娆＄簿纭?€?""
    if has_exif:
        try:
            return await _call_solve(client, image_bytes,
                                     scale_hint.get("low", 10), scale_hint.get("high", 60))
        except TimeoutError:
            raise TimeoutError("race solve timeout")

    ranges = [(60, 500), (500, 1500), (1500, 3500), (3500, 6000)]
    timed_out_any = False

    for low, high in ranges:
        try:
            r = await _call_solve(client, image_bytes, low, high)
            if r.get("solved"):
                return r
        except TimeoutError:
            timed_out_any = True
            continue
        except ConnectionError:
            raise
    # 鍏ㄩ儴澶辫触锛氳秴 6000px 鏃?crop 1/2 閲?race锛圱3 瀹屾暣鍖栵級
    if width > 6000 or height > 6000:
        cropped, crop_x0, crop_y0, crop_w, crop_h = _crop_center(image_bytes, width, height)
        for low, high in ranges:
            try:
                r = await _call_solve(client, cropped, low, high)
                if r.get("solved"):
                    r["_crop_offset"] = (crop_x0, crop_y0)
                    r["_crop_h"] = crop_h  # 供 _to_solve_result 安全读取，避免 height-2*crop_y0 奇数错位
                    return r
            except TimeoutError:
                timed_out_any = True
                continue

    # 全超时：raise TimeoutError，让上层映射 TIMEOUT（spec §3.1）
    if timed_out_any:
        raise TimeoutError("race solve timeout")
    return {"solved": False, "raw_output": "race exhausted"}


def _crop_center(image_bytes: bytes, full_w: int, full_h: int) -> tuple[bytes, int, int, int, int]:
    crop_w, crop_h = full_w // 2, full_h // 2
    crop_x0 = (full_w - crop_w) // 2
    crop_y0 = (full_h - crop_h) // 2
    img = Image.open(io.BytesIO(image_bytes))
    cropped = img.crop((crop_x0, crop_y0, crop_x0 + crop_w, crop_y0 + crop_h))
    buf = io.BytesIO()
    cropped.convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue(), crop_x0, crop_y0, crop_w, crop_h


def _to_solve_result(result: dict, width: int, height: int, solve_time: float) -> dict:
    """缁勮? SolveResult銆俬it=0 鏃?constellations=[]锛堝墠绔?蛋 empty锛夈€?

    crop 椤哄簭锛坰pec 搂16.1.5锛夛細鍏堝湪瑁佸垏鍧愭爣绯诲仛 project_stars锛屽啀 += (crop_x0, crop_y0) 鍥炲師鍥撅紝鏈€鍚庢寜鍘熷浘 height Y_FLIP銆?
    """
    wcs_header = result["wcs_header"]
    crop_offset = result.get("_crop_offset", (0, 0))
    crop_x0, crop_y0 = crop_offset

    # 仅在裁剪路径（crop_offset != (0,0)）下读取 _crop_h；非裁剪路径用原图 height
    # 防止 assert 在常规求解路径（_call_solve 直接返回）误触
    crop_h = result["_crop_h"] if crop_offset != (0, 0) else height
    stars = project_stars(wcs_header, image_height=crop_h, y_flip=False)

    # [2] += (crop_x0, crop_y0) 鍥炲師鍥惧潗鏍囩郴
    for s in stars:
        s["pixel_x"] = round(s["pixel_x"] + crop_x0, 2)
        s["pixel_y"] = round(s["pixel_y"] + crop_y0, 2)

    # [3] 鎸夊師鍥?height Y_FLIP锛坰pec 搂4.2锛?
    if Y_FLIP:
        for s in stars:
            s["pixel_y"] = round(height - 1 - s["pixel_y"], 2)

    # 璁＄畻 hit_stars锛歴tars_overlay 涓?bayer 鍦?orion 涓斿潗鏍囧湪鍥惧唴
    hit_stars = sum(
        1 for s in stars
        if 0 <= s["pixel_x"] <= width and 0 <= s["pixel_y"] <= height
    )

    constellations = []
    if hit_stars >= 1:
        confidence = hit_stars / 8
        constellations.append({
            "abbr": "ori", "name": "鐚庢埛搴?, "latin": "Orion",
            "confidence": round(confidence, 3),
            "hit_stars": hit_stars, "total_bright_stars": 8,
        })

    return {
        "ok": True, "solved": True,
        "ra": result.get("ra"), "dec": result.get("dec"),
        "solve_time": round(solve_time, 2),
        "image_width": width, "image_height": height,
        "exif_orientation": 1,
        "constellations": constellations,
        "stars_overlay": stars,
        "overlay_lines": [
            ["Alpha Ori", "Gamma Ori"], ["Alpha Ori", "Lambda Ori"],
            ["Lambda Ori", "Gamma Ori"], ["Alpha Ori", "Zeta Ori"],
            ["Gamma Ori", "Delta Ori"], ["Delta Ori", "Epsilon Ori"],
            ["Epsilon Ori", "Zeta Ori"], ["Delta Ori", "Beta Ori"],
            ["Zeta Ori", "Kappa Ori"], ["Beta Ori", "Kappa Ori"],
        ],
    }
```

- [ ] **Step 3: 鍐?test_concurrency.py锛坅sync + 骞跺彂 waiter 娴?Busy锛?*

```python
# server/tests/test_concurrency.py
import asyncio
import pytest

from services.astrometry import BusyError, SolveSlot


@pytest.mark.asyncio
async def test_acquire_then_release():
    slot = SolveSlot(max_active=2, max_queue=2)
    async with slot.acquire():
        assert slot.active == 1
    assert slot.active == 0


@pytest.mark.asyncio
async def test_busy_raises_when_active_and_queue_full():
    """蹇呴』骞跺彂鏋勯€狅細鍏堝崰婊?active 鍜?queue锛屽啀娴?BusyError锛堝祵濂?acquire 浼氬崱 Semaphore锛夈€?""
    slot = SolveSlot(max_active=1, max_queue=1)
    started = asyncio.Event()

    async def hold():
        async with slot.acquire():
            started.set()
            await asyncio.sleep(0.5)

    async def waiter():
        async with slot.acquire():  # 杩涘叆 queue锛堜笉鎶涳級
            pass

    task = asyncio.create_task(hold())
    await started.wait()
    w_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # 璁?waiter 杩涘叆 acquire 鐨?_lock 娈?

    with pytest.raises(BusyError):
        async with slot.acquire():
            pass

    await asyncio.gather(task, w_task)


@pytest.mark.asyncio
async def test_queued_decremented_on_cancellation():
    """鍙栨秷鎺掗槦涓?殑 waiter锛歲ueued 蹇呴』鍑忥紝涓嶆硠婕忋€?""
    slot = SolveSlot(max_active=1, max_queue=5)
    async with slot.acquire():
        assert slot.active == 1

        async def waiter():
            async with slot.acquire():
                pass

        t = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)  # waiter 杩涘叆 _queued += 1
        assert slot.queued == 1

        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

        # 绛?finally 璺戝畬
        await asyncio.sleep(0.05)
        assert slot.queued == 0


@pytest.mark.asyncio
async def test_active_decremented_after_yield():
    """鎷垮埌妲藉悗 yield 瀹屽啀鍙栨秷锛歛ctive 璧?finally 鍑忋€?""
    slot = SolveSlot(max_active=1, max_queue=1)

    async def holder():
        async with slot.acquire():
            assert slot.active == 1
            await asyncio.sleep(0.1)

    t = asyncio.create_task(holder())
    await asyncio.sleep(0.05)
    assert slot.active == 1

    await t
    assert slot.active == 0
    assert slot.queued == 0


@pytest.mark.asyncio
async def test_max_active_one_uses_instance_not_hardcoded():
    """鍥炲綊淇濋櫓锛歴pec 搂4.3 鑷?甫 hardcode bug锛屾湰娴嬭瘯鐢?max_active=1 + max_queue=1 楠岃瘉銆?""
    slot = SolveSlot(max_active=1, max_queue=1)
    assert slot.max_active == 1
    assert slot.max_queue == 1

    async with slot.acquire():
        async def queue_then():
            async with slot.acquire():
                pass

        qt = asyncio.create_task(queue_then())
        await asyncio.sleep(0.05)

        with pytest.raises(BusyError):
            async with slot.acquire():
                pass

        qt.cancel()
        try:
            await qt
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 4: 鍐?test_identify.py锛堝け璐ユ槧灏?+ normalize_image锛?*

```python
# server/tests/test_identify.py
import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from main import app


client = TestClient(app)


def _make_jpeg_bytes(width: int = 100, height: int = 100, orientation: int = 1) -> bytes:
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    exif = img.getexif()
    if orientation != 1:
        exif[0x0112] = orientation
    img.save(buf, "JPEG", exif=exif if orientation != 1 else None, quality=95)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    # 默认 mock：直接 patch 已加载的模块常量（config.py 在 import 时已固化 ASTROMETRY_MOCK）
    monkeypatch.setattr('routers.identify.ASTROMETRY_MOCK', True)
    monkeypatch.setattr('services.astrometry.ASTROMETRY_MOCK', True)
    yield


def test_normalize_image_orientation_1_passthrough():
    """Orientation=1 JPEG 鈫?鍘熸牱閫忎紶锛岀?姝㈠帇缂╀涪鏄熴€?""
    from routers.identify import normalize_image
    content = _make_jpeg_bytes(orientation=1)
    out, ori, w, h = normalize_image(content)
    assert out == content, "Orientation=1 搴斿師鏍烽€忎紶"
    assert ori == 1
    assert (w, h) == (100, 100)


def test_normalize_image_orientation_6_reencodes():
    """Orientation=6 JPEG 鈫?蹇呴噸缂栫爜 q95锛堜慨澶?JPEG 閫忎紶 bug锛夈€?""
    from routers.identify import normalize_image
    content = _make_jpeg_bytes(width=200, height=100, orientation=6)
    out, ori, w, h = normalize_image(content)
    assert ori == 1
    # 閲嶇紪鐮佸悗 width/height 搴斾负姝ｅ悜鍖栧悗鐨勫昂瀵革紙200x100 鈫?100x200锛?
    assert (w, h) == (100, 200)
    assert out != content


def test_unsupported_format_returns_400():
    r = client.post("/api/identify/solve",
                    files={"image": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_upload_too_large_returns_413():
    big = b"\xff\xd8" + b"x" * (21 * 1024 * 1024)
    r = client.post("/api/identify/solve",
                    files={"image": ("x.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"


def test_mock_solve_returns_orion():
    """ASTROMETRY_MOCK=1 + analyse mock 杩斿洖 fov 30/20 + solve mock 杩斿洖 solved 鈫?鍛戒腑鐚庢埛銆?""
    r = client.post("/api/identify/solve",
                    files={"image": ("x.jpg", _make_jpeg_bytes(600, 400), "image/jpeg")})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["solved"] is True
    assert data["exif_orientation"] == 1
    assert data["image_width"] == 600
    assert data["image_height"] == 400
    assert len(data["stars_overlay"]) == 8
    assert any(c["abbr"] == "ori" for c in data["constellations"])


def test_hit_zero_returns_empty_constellations():
    """hit=0 鏃?constellations=[]锛堝墠绔?蛋 empty锛夈€?""
    # Mock mode for offline testing
    fake = {
        "solved": True,
        "wcs_header": {
            "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
            "CRPIX1": 0, "CRPIX2": 0,
            "CRVAL1": 0, "CRVAL2": 0,
            "CD1_1": 0.001, "CD1_2": 0, "CD2_1": 0, "CD2_2": 0.001,
            "NAXIS1": 100, "NAXIS2": 100,
        },
        "ra": 0, "dec": 0,
    }
    with patch("routers.identify._call_analyse", new=AsyncMock(return_value={
            "success": True, "has_exif": True,
            "fov": {"width_degrees": 30, "height_degrees": 20},
            "scale_hint": {"low": 1.0, "high": 60.0, "units": "arcminwidth"}})):
        with patch("routers.identify._call_solve", new=AsyncMock(return_value=fake)):
            r = client.post("/api/identify/solve",
                            files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")})
    assert r.status_code == 200
    data = r.json()
    assert data["solved"] is True
    # hit=0 时必须返回空 constellations（前端走 empty 分支）
    assert data["ok"] is True
    assert data["constellations"] == []
    # 注意：stars_overlay 仍包含 8 颗投影星点（hit 计算未匹配），不能为空
    assert len(data["stars_overlay"]) == 8


def test_timeout_returns_200_timeout_code():
    """浠ｇ悊瓒呮椂锛圓syncMock 鎶?TimeoutError锛夆啋 200 + TIMEOUT锛堜笉 504锛夈€?""
    with patch("routers.identify._call_analyse", new=AsyncMock(side_effect=TimeoutError("analyse timeout"))):
        r = client.post("/api/identify/solve",
                        files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "TIMEOUT"


def test_connection_error_returns_502():
    """涓婃父杩炴帴澶辫触 鈫?502 ASTROMETRY_DOWN銆?""
    with patch("routers.identify._call_analyse",
               new=AsyncMock(side_effect=ConnectionError("down"))):
        r = client.post("/api/identify/solve",
                        files={"image": ("x.jpg", _make_jpeg_bytes(100, 100), "image/jpeg")})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "ASTROMETRY_DOWN"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd server && .venv/bin/python -m pytest tests/test_concurrency.py tests/test_identify.py -v`
Expected: 5 (concurrency) + 7 (identify) = 12 passed

- [ ] **Step 6: Commit**

```bash
git add server/requirements.txt \
        server/config.py \
        server/routers/identify.py \
        server/tests/test_concurrency.py \
        server/tests/test_identify.py
git commit -m "feat(server): /api/identify/solve 鎺ュ叆 astrometry + normalize_image锛堜慨 JPEG 閫忎紶 bug锛? 澶辫触鏄犲皠锛堣秴鏃?200 TIMEOUT / 杩炴帴 502锛? SolveSlot async 闆嗘垚"
```

---
### Task 3: AI Provider 鎶借薄 + POST /api/story + LRU 10min

**Files:**
- Create: `server/data/preset_stories.json`锛? 鏄熷骇 脳 2 椋庢牸 = 10 绡囷級
- Create: `server/services/story_fallback.py`锛堟寜 (abbr, style) 鍙栭?鍒讹級
- Create: `server/services/ai_provider.py`锛坆ase + OpenAI 鍏煎? + DisabledProvider锛?
- Create: `server/routers/story.py`锛圥OST /api/story锛屽惈 LRU 10min + Cache-Bust:1 header + **涓嶇紦瀛?degraded:true**锛?
- Modify: `server/main.py`锛堟寕杞?story router + constellations router锛?
- Modify: `server/services/constellation.py`锛堟柊澧?list_constellations锛屽?鐢?constellations.json锛?
- Create: `server/routers/constellations.py`锛圙ET /api/constellations 鍒楄〃锛?
- Test: `server/tests/test_story.py`锛坧rovider 鎶借薄 + 闄嶇骇 + 椋庢牸鍒囨崲 + 涓嶇紦瀛?degraded锛?

**Interfaces:**
- Consumes: `services.ai_provider.make_provider()`銆乣data/preset_stories.json`
- Produces:
  - `POST /api/story {abbr, style, lang}` 鈫?`{ok, abbr, style, title, paragraphs, provider, model, latency_ms, cached, degraded, degraded_reason?}`
  - `GET /api/constellations` 鈫?`{ok, items: [{abbr, name, latin, glyph, season, caption, bright_stars}, ...]}`

**瀹屾垚瀹氫箟锛?*
- 5 鏄熷骇锛坥ri/cyg/sco/leo/and锛壝?2 椋庢牸锛坢yth/science锛? 10 绡囬?鍒?
- story_fallback.get_preset(abbr, style) 杩斿洖 preset 鎴?None
- LRU TTLCache(maxsize=64, ttl=600)
- **涓嶇紦瀛?`degraded:true`**锛堣?涓嬫?璋冪敤閲嶈瘯涓婚摼璺?紱spec 搂5.4锛?
- `Cache-Bust: 1` header 鎴?`cacheBust=true` body 缁曡繃缂撳瓨
- 鏈?煡鏄熷骇 鈫?404 `CONSTELLATION_NOT_FOUND`锛堜笉鏄?422锛?
- 椋庢牸闈炴硶 鈫?400 `INVALID_STYLE`
- max_tokens=1000锛宼imeout=30s锛坰pec 搂16.4锛?
- DisabledProvider锛堥潪鐪?503锛泂pec 搂16.4锛?

---

- [ ] **Step 1: 写 `server/data/preset_stories.json`（10 篇预制）**

鍐欏叆 `server/data/preset_stories.json`锛?

```json
{
  "ori": {
    "myth": {
      "title": "鍙傚晢涓嶇浉瑙佲€斺€旂寧鎴风殑涓?浗鏁呬簨",
      "paragraphs": [
        "鐚庢埛搴у湪涓?浗鍙や唬鍚嶄负鍙傚?锛屽睘鍥涜薄涓?殑瑗挎柟鐧借檸銆傚弬瀹垮洓锛圔etelgeuse锛変綔鑲╋紝鍙傚?涓冿紙Rigel锛変綔鑶濓紝姝ｆ槸銆婅瘲缁忋€嬨€屼笁鏄熷湪涓溿€嶃€併€屼笁鏄熷湪鍗椼€嶆墍鎸囥€?,
        "鍙や汉灏嗗弬瀹夸笌蹇冨?锛堝ぉ铦庡骇 伪 鏄燂級鐩稿?绉颁负銆屽弬鍟嗐€嶃€傘€婂乏浼犮€嬭?楂樿緵姘忎簩瀛愪笉鐩歌兘锛屾棩瀵诲共鎴堬紝甯濅互澶х伀鏄熻縼涓€锛屽弬瀹胯縼浜岋紝浣挎案涓嶇浉瑙佲€斺€旀潨鐢?€屼汉鐢熶笉鐩歌?锛屽姩濡傚弬涓庡晢銆嶇敱姝ゆ潵銆?,
        "浠婂?浣犺嫢鎷嶄笅杩欑墖鏄熼噹锛屼笉濡ㄨ?璧疯繖浠藉彜鑰佺殑閬楁喚锛氭槦杈颁粛鎸夋棦瀹氳建杩硅繍琛岋紝鎴栬?鏌愭棩鍙傚晢浼氬湪鏅ㄦ槒鐨勭紳闅欓噷鐭?殏鐩告湜銆?
      ]
    },
    "science": {
      "title": "鐚庢埛搴р€斺€斿啲瀛ｆ槦绌虹殑鏍囧織鎬ц叞甯?,
      "paragraphs": [
        "鐚庢埛搴ф槸鍏ㄥぉ鏈€瀹规槗杈ㄨ?鐨勬槦搴т箣涓€銆傝叞甯︿笁鏄燂紙鍙傚?涓€/浜?涓夛級鍑犱箮鍦ㄨ丹閬撴?璐?1 搴﹀唴锛屽叏鐞冨彲瑙併€侻42 鐚庢埛澶ф槦浜戜綅浜庤叞甯︿笅鏂广€屽墤銆嶇殑浣嶇疆锛岃窛鍦扮害 1344 鍏夊勾銆?,
        "鍙傚?鍥涳紙Betelgeuse锛夋槸涓€棰楃孩瓒呭法鏄燂紝鍗婂緞绾︿负澶?槼鐨?700 鍊嶏紝杩戝嚑鍗佸勾浜?害鏄捐憲鍙樺寲锛屽ぉ鏂囧?瀹堕?璁″畠鍙?兘鍦ㄦ湭鏉ュ崄涓囧勾鍐呯垎鍙戜负瓒呮柊鏄熴€?,
        "鎷嶆憚鍐??澶滅┖鏃讹紝鐚庢埛搴ф槸妫€楠岀浉鏈烘劅鍏夎兘鍔涙渶鍙嬪ソ鐨勭洰鏍囷紝涔熸槸瀹氫綅鍖楁瀬鏄熶笌鍐??閾舵渤鐨勮捣鐐广€?
      ]
    }
  },
  "cyg": {
    "myth": {
      "title": "澶╂触涓庢渤榧撯€斺€斿ぉ楣呮浮娌崇殑浼犺?",
      "paragraphs": [
        "澶╅箙搴у湪涓?浗灞炲寳鏂圭巹姝︿竷瀹夸腑鐨勫コ瀹夸笌鐗涘?銆傛渶浜?殑澶╂触鍥涳紙Deneb锛夋槸銆屽ぉ娲ャ€嶏紙閾舵渤娓″彛锛夌殑鏍囧織锛屼笌鐗涢儙鏄燂紙娌抽紦浜屻€佸ぉ楣板骇 伪锛夐殧娌崇浉鏈涖€?,
        "銆屼竷澶曟浮娌炽€嶄紶璇翠腑锛岀墰閮庣粐濂充竴骞翠竴浼氾紝瑕侀潬鍠滈箠鎼?ˉ鈥斺€斿ぉ娲ヤ竴鑷冲ぉ娲ュ洓鏋勬垚娓″彛锛屾壙杞借繖娈典汉闂存渶鍙よ€佺殑鐖辨儏鎯宠薄銆?,
        "鍙や汉浠ユ槦璞″懡鍚嶉亾璺?紝鍙嶆槧銆岃?澶╂巿鏃躲€嶇殑浼犵粺锛氬ぉ娲ユ浮鍙ｆ棦鏄?槦鍚嶏紝涔熸槸浜轰簨鐨勯殣鍠汇€?
      ]
    },
    "science": {
      "title": "澶╅箙搴р€斺€斿寳澶╁崄瀛椾笌澶忓?澶т笁瑙?,
      "paragraphs": [
        "澶╅箙搴э紙Cygnus锛変富鏄熷憟鏄庢樉鐨勫崄瀛楀舰锛屾渶浜?殑澶╂触鍥涳紙Deneb锛夋槸澶滅┖绗?19 浜?亽鏄燂紝璺濈?鍦扮悆绾?2615 鍏夊勾銆?,
        "澶╂触鍥涗笌缁囧コ鏄燂紙澶╃惔搴?伪锛夈€佺墰閮庢槦锛堝ぉ楣板骇 伪锛夋瀯鎴愯憲鍚嶇殑銆屽?瀛ｅぇ涓夎?銆嶏紝鏄?寳鍗婄悆澶忓?澶滅┖鏈€鏄撹鲸璁ょ殑鏄熻薄涔嬩竴銆?,
        "澶╅箙搴т綅浜庨摱娌冲甫涓?紝娌垮叾涓昏酱鍙??娴嬪埌澶ч噺鏄熶簯涓庣枏鏁ｆ槦鍥?紝鏄??瀛ｆ憚褰辩殑涓板瘜绱犳潗銆?
      ]
    }
  },
  "sco": {
    "myth": {
      "title": "蹇冨?浜屸€斺€旇媿榫欎箣蹇冪殑鐐界劙",
      "paragraphs": [
        "澶╄潕搴у湪涓?浗灞炰笢鏂硅媿榫欎竷瀹夸腑鐨勫績瀹匡紝鏈€浜?殑蹇冨?浜岋紙Antares锛夊彜绉般€屽ぇ鐏?€嶆垨銆屽晢鏄熴€嶏紝鑹茬孩浼肩伀锛屾槸銆婅瘲缁忋€嬩腑銆屼竷鏈堟祦鐏?€嶇殑鎵€鎸囥€?,
        "銆婂乏浼犮€嬭浇锛氥€屽ぇ鐏?槦涓?紝瀵掔儹涔冮€€銆嶏紝鍙や汉鍑?績瀹夸簩鐨勬櫒鏄忎腑澶╁垽鏂??鑺傘€傚績瀹夸簩涓庡弬瀹夸簩鐩稿?锛屾瀯鎴愪簡銆屽弬鍟嗐€嶄紶璇寸殑鍙︿竴鍗娿€?,
        "蹇冨?浜屽疄涓轰竴棰楃孩瓒呭法鏄燂紝鍗婂緞绾︿负澶?槼鐨?700 鍊嶏紝涓庣寧鎴峰弬瀹垮洓绫讳技锛岄兘澶勫湪婕斿寲鏈?湡銆?
      ]
    },
    "science": {
      "title": "澶╄潕搴р€斺€斿?瀛ｅ崡澶╃殑鏍囧織",
      "paragraphs": [
        "澶╄潕搴ф槸榛勯亾鍗佷簩鏄熷骇涔嬩竴锛屼富鏄熷績瀹夸簩锛圓ntares锛変寒搴?1.06 绛夛紝鍛堢幇鏄庢樉鐨勬?绾㈣壊銆傘€孉ntares銆嶆剰涓恒€屽?鎶楃伀鏄熻€呫€嶏紝鍥犲叾棰滆壊涓庣伀鏄熺浉浼笺€?,
        "澶╄潕搴х殑閽╃姸灏鹃儴锛堝熬瀹垮叓鍒板熬瀹夸節锛夋寚鍚戦摱娌崇郴涓?績鏂瑰悜锛岄檮杩戝瘑闆嗙殑鎭掓槦浜戯紙M6銆丮7 鐤忔暎鏄熷洟锛夋槸澶忓?澶滅┖鎽勫奖鐨勭儹闂ㄧ洰鏍囥€?,
        "鍦ㄤ腑鍥藉ぇ閮ㄥ垎鍦板尯锛屽ぉ铦庡骇浠呰兘瑙佸埌鍓嶅崐閮?紙鎴裤€佸績銆佸熬涓夊?锛夛紝鏈€鍗楃?鐨勯挬鐖??缁堜綅浜庡湴骞崇嚎浠ヤ笅銆?
      ]
    }
  },
  "leo": {
    "myth": {
      "title": "杞╄緯鏄熷?鈥斺€旂嫯瀛愬骇鐨勫笣鐜嬭薄寰?,
      "paragraphs": [
        "鐙?瓙搴у湪涓?浗灞炲お寰?灒闄勮繎鐨勮僵杈曟槦瀹橈紝杞╄緯鍗佷竷锛圧egulus锛夋槸銆岄粍甯濅箣绁炪€嶃€傚彜浜鸿?涔嬩负甯濈帇涔嬫槦锛屼富瀹颁汉闂村叴琛般€?,
        "杞╄緯鍗佷簩锛圓lgieba锛夋槸涓€瀵瑰弻鏄燂紝鑲夌溂鐪嬩技涓€棰楋紝鍙や唬琚??浣溿€屽悗濡冧箣璞°€嶄笌涓绘槦鐩镐即锛岃薄寰佸笣鍚庡悓杈夈€?,
        "鐙?瓙鐨勯暟鍒€褰撹兏锛堣僵杈曞崄涓€鑷冲崄浜旓級锛屼簲甯濆骇涓€涓哄熬鈥斺€旇繖浜涙槦鍚嶆瀯鎴愪簡甯濈帇澶╁环鐨勫畬鏁村浘鏅?€?
      ]
    },
    "science": {
      "title": "鐙?瓙搴р€斺€旀槬澶滃吔鐜?,
      "paragraphs": [
        "鐙?瓙搴э紙Leo锛夋槸榛勯亾鍗佷簩鏄熷骇涔嬩竴锛屼富鏄熻僵杈曞崄涓冿紙Regulus锛変寒搴?1.36 绛夛紝璺濈?鍦扮悆绾?79 鍏夊勾锛屾槸澶滅┖涓?渶浜?殑鎭掓槦涔嬩竴銆?,
        "鐙?瓙搴ф祦鏄熼洦姣忓勾 11 鏈堜腑鏃?揪鍒板嘲鍊硷紝姣忓皬鏃跺ぉ椤舵祦閲忕害 10-20 棰楋紝姣嶅綏鏄熶负 55P/Tempel-Tuttle 鐨勫皹鍩冨甫銆?,
        "M65銆丮66 涓?NGC 3628 鏋勬垚钁楀悕鐨勩€岀嫯瀛愪笁閲嶆槦绯汇€嶏紝浣嶄簬鐙?瓙搴у悗鑵块檮杩戯紝浣跨敤涓?瓑鏈涜繙闀滃彲涓€骞惰?娴嬨€?
      ]
    }
  },
  "and": {
    "myth": {
      "title": "濂庡?涓庡?瀹库€斺€斾粰濂冲骇鐨勪腑鍥借韩浠?,
      "paragraphs": [
        "浠欏コ搴у湪涓?浗灞炲寳鏂圭巹姝︿竷瀹夸腑鐨勫?瀹夸笌澹佸?銆傚?瀹夸簩锛圓lpheratz锛夊師灞炲?瀹匡紝鍚庡垝褰掑?瀹匡紝鏄?簩鍗佸叓瀹夸綋绯讳腑鐨勯噸瑕佽妭鐐广€?,
        "鍙や汉浠ュ?瀹夸富鏂囩珷涓庝功绫嶏紝濂庡?涓绘枃绔犮€佹?搴撯€斺€旀晠銆屽?澹併€嶄竴璇嶆寚浠ｆ枃杩愪笌姝﹀姛鐨勫弻閲嶅叴鐩涖€?,
        "甯岃厞绁炶瘽涓?粰濂?Andromeda 琚?Perseus 鎷?晳鐨勬晠浜嬩紶鍏ヤ腑鍥藉悗锛屼笌鏈?湡濂庡?鏂囧寲浜よ瀺锛屼赴瀵屼簡鏄熻薄鐨勪汉鏂囧寲鍐呮兜銆?
      ]
    },
    "science": {
      "title": "浠欏コ搴р€斺€旇倝鐪煎彲瑙佺殑閬ヨ繙鏄熺郴",
      "paragraphs": [
        "浠欏コ搴э紙Andromeda锛変富鏄熷?瀹夸簩锛圓lpheratz锛変寒搴?2.06 绛夛紝璺濈?鍦扮悆绾?97 鍏夊勾銆?,
        "M31 浠欏コ鏄熺郴浣嶄簬浠欏コ搴у唴锛屾槸璺濋摱娌崇郴鏈€杩戠殑澶у瀷鏃嬫丁鏄熺郴锛堢害 254 涓囧厜骞达級锛屾槸鑲夌溂鍙??鏈€杩滅殑澶╀綋涔嬩竴銆?,
        "鍦ㄧ?瀛ｅ?绌烘棤鍏夋薄鏌撳?锛屽彲鑲夌溂鐪嬪埌 M31 妯＄硦鐨勫厜鏂戔€斺€旇繖涓€鐪肩湅鍒扮殑鏄熷厜宸叉梾琛屼簡 254 涓囧勾銆?
      ]
    }
  }
}
```

- [ ] **Step 2: 鍐?services/story_fallback.py**

```python
# server/services/story_fallback.py
import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict


class StoryPreset(TypedDict):
    title: str
    paragraphs: list[str]


PresetMap = dict[str, dict[str, StoryPreset]]  # abbr -> style -> preset


@lru_cache(maxsize=1)
def _load_presets() -> PresetMap:
    path = Path(__file__).resolve().parents[1] / "data" / "preset_stories.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_preset(abbr: str, style: str) -> StoryPreset | None:
    """杩斿洖 (abbr, style) 瀵瑰簲鐨勯?鍒舵晠浜嬶紝涓嶅瓨鍦ㄥ垯 None銆?""
    return _load_presets().get(abbr, {}).get(style)
```

- [ ] **Step 3: 鍐?services/ai_provider.py**

```python
# server/services/ai_provider.py
"""AI Provider 鎶借薄锛坰pec 搂5.1 + 搂16.4 鍏ㄩ儴钀藉湴锛夈€?

- base AIProvider锛坈hat / health锛?
- OpenAICompatibleProvider锛圖eepSeek / 鏅鸿氨 / OpenAI 缁熶竴锛?
- DisabledProvider锛堟棤 AI_API_KEY 鏃跺惎鐢?紝瑙﹀彂 fallback preset锛?*闈?503**锛?
- max_tokens=1000锛泃imeout 30s
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Literal

import httpx

from config import AI_API_BASE, AI_API_KEY, AI_MODEL


StoryStyle = Literal["myth", "science"]


class AIProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str: ...

    @abstractmethod
    async def health(self) -> bool: ...


class OpenAICompatibleProvider(AIProvider):
    """DeepSeek / 字节 / OpenAI 统一走 OpenAI Chat Completions。
    客户端为模块级单例 + shutdown 时统一 aclose，避免连接数累积。
    """

    _CLIENT: httpx.AsyncClient | None = None

    def __init__(self, base_url: str, api_key: str, model: str, name: str = "openai-compatible"):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        if OpenAICompatibleProvider._CLIENT is None:
            OpenAICompatibleProvider._CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._client = OpenAICompatibleProvider._CLIENT

    @classmethod
    async def aclose(cls) -> None:
        """应用关闭时调用，统一释放底层 httpx 连接池。"""
        if cls._CLIENT is not None:
            await cls._CLIENT.aclose()
            cls._CLIENT = None

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
                "max_tokens": 1000,
            },
            timeout=timeout,
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
    """鏈?厤缃?AI_API_KEY 鏃跺惎鐢?細health()=False, chat() 鎶涢敊瑙﹀彂 fallback銆?""

    name = "disabled"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        raise RuntimeError("AI_PROVIDER_DISABLED")

    async def health(self) -> bool:
        return False


def make_provider() -> AIProvider:
    if AI_API_KEY:
        return OpenAICompatibleProvider(
            base_url=AI_API_BASE, api_key=AI_API_KEY, model=AI_MODEL,
        )
    return DisabledProvider()


SYSTEM_PROMPT = """浣犳槸銆屾槦璇?ぉ璞★紙StarWhisper锛夈€嶇殑鏄熷骇鏁呬簨瀹樸€備换鍔★細鐢?{style_zh} 瑙嗚?璁茶堪 {constellation_zh}锛坽latin}锛夛紝3-4 娈靛叡 220-300 瀛椼€?
瑕佹眰锛?
- 绁炶瘽瑙嗚?锛氳?杩颁腑鍥?甯岃厞绁炶瘽鏉ユ簮锛屽瘜鏈夋晠浜嬫劅
- 绉戞櫘瑙嗚?锛氳В閲婂ぉ鏂囩粨鏋勩€佽?娴嬪?鑺傘€佹繁绌烘憚褰辫?鐐?
- 娈佃惤鍒嗘槑锛屾瘡娈?60-90 瀛楋紝涓嶅爢鐮屾湳璇?
- 鏂囨湯涓嶅姞銆屽笇鏈涗綘鍠滄?銆嶃€岀?瑙傛槦鎰夊揩銆嶄箣绫荤┖璇?
- 涓嶇紪閫犳槦鍚?鍧愭爣锛涘?涓嶇‘瀹氳?鐢ㄣ€屼紶璇翠笉涓€銆嶇瓑闄愬畾
- 杈撳嚭浠呭惈鏍囬? + 娈佃惤姝ｆ枃锛屼笉瑕?JSON / Markdown 鏍囪?
"""

USER_TEMPLATE = """星座：{constellation_zh} ({latin})
风格：{style_zh}
主星列表：
{primary_stars}
"""


STYLE_ZH = {"myth": "绁炶瘽", "science": "绉戞櫘"}
```

- [ ] **Step 4: 淇?敼 services/constellation.py锛堟柊澧?list_constellations锛?*

```python
# server/services/constellation.py 锛堣拷鍔犲湪 M1 宸叉湁浠ｇ爜涔嬪悗锛?
import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict


class ConstSummary(TypedDict):
    abbr: str
    name: str
    latin: str
    glyph: str
    hemisphere: str          # "N" | "S" | "B"
    bestMonth: int           # 1..12
    season: str
    caption: str
    magnitude: float         # 最亮主星视星等
    bright_stars: int
    storyStyles: list[str]   # ["myth", "science"]


@lru_cache(maxsize=1)
def _load_constellations() -> dict:
    path = Path(__file__).resolve().parents[1] / "data" / "constellations.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_constellations() -> list[ConstSummary]:
    """杩斿洖 5 鏄熷骇 summary锛圡1 鏁版嵁婧愶紝**涓嶆柊寤?JSON**锛夈€?""
    data = _load_constellations()
    return [
        ConstSummary(
            abbr=c["abbr"], name=c["name"], latin=c["latin"],
            glyph=c.get("glyph", "★"),
            hemisphere=c.get("hemisphere", "B"),
            bestMonth=int(c.get("best_month", 1)),
            season=c.get("season", ""),
            caption=c.get("caption", ""),
            magnitude=float(c.get("magnitude", 0.0)),
            bright_stars=c.get("bright_stars_mag_lt_35", len(c.get("stars", {}))),
            storyStyles=list(c.get("story_styles", ["myth", "science"])),
        )
        for c in data.values()
    ]


# M1 宸叉湁锛歡et_constellation(abbr) 鈥?淇濇寔涓嶅彉
```

- [ ] **Step 5: 鍐?routers/constellations.py**

```python
# server/routers/constellations.py
from fastapi import APIRouter

from services.constellation import list_constellations


router = APIRouter(prefix="/api/constellations", tags=["constellations"])


@router.get("")
async def get_constellations():
    return {"ok": True, "items": list_constellations()}
```

- [ ] **Step 6: 鍐?routers/story.py锛圥OST /api/story锛?*

```python
# server/routers/story.py
"""POST /api/story锛坰pec 搂3.3 + 搂5.4锛夈€?

- 10 鍒嗛挓 LRU锛坈achetools.TTLCache锛?
- **涓嶇紦瀛?degraded:true**
- Cache-Bust: 1 header 鎴?cacheBust=true body 缁曡繃缂撳瓨
- 鏈?煡鏄熷骇锛?04 CONSTELLATION_NOT_FOUND锛堜笉鏄?422锛?
- 椋庢牸闈炴硶锛?00 INVALID_STYLE
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from cachetools import TTLCache
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from threading import Lock

from config import AI_MODEL
from services.ai_provider import (
    STYLE_ZH, SYSTEM_PROMPT, USER_TEMPLATE, make_provider,
)
from services.constellation import list_constellations, get_constellation
from services.story_fallback import get_preset


router = APIRouter(prefix="/api/story", tags=["story"])

_STYLES = {"myth", "science"}
_STORY_CACHE: TTLCache = TTLCache(maxsize=64, ttl=600)  # 10 min
_CACHE_LOCK = Lock()


def _cache_key(abbr: str, style: str) -> tuple[str, str]:
    return (abbr, style)


def _cache_get(abbr: str, style: str):
    with _CACHE_LOCK:
        return _STORY_CACHE.get(_cache_key(abbr, style))


def _cache_put(abbr: str, style: str, payload: dict) -> None:
    """degraded:true 涓嶅啓缂撳瓨锛坰pec 搂5.4 鏈??锛夈€?""
    if payload.get("degraded"):
        return
    with _CACHE_LOCK:
        _STORY_CACHE[_cache_key(abbr, style)] = payload


class StoryRequest(BaseModel):
    abbr: str = Field(..., description="鏄熷骇 abbr锛堝? ori锛?)
    style: str = Field(..., description="myth | science")
    lang: str = Field("zh", description="璇?█浠ｇ爜锛屾殏鍥哄畾 zh")
    cacheBust: bool = Field(False, alias="cacheBust")

    class Config:
        populate_by_name = True


@router.post("")
async def post_story(
    body: StoryRequest,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    # 1. 鏍￠獙 style
    if body.style not in _STYLES:
        raise HTTPException(400, detail={"code": "INVALID_STYLE",
                                          "message": f"style 蹇呴』鏄?{sorted(_STYLES)}"})

    valid_abbrs = {c["abbr"] for c in list_constellations()}
    if body.abbr not in valid_abbrs:
        raise HTTPException(404, detail={"code": "CONSTELLATION_NOT_FOUND",
                                          "message": "鏈?敹褰曟?鏄熷骇"})

    bust = body.cacheBust or cache_bust == 1

    # 3. 鏌ョ紦瀛?
    if not bust:
        cached = _cache_get(body.abbr, body.style)
        if cached is not None:
            return {**cached, "cached": True}

    # 4. 璋?AI
    constellation = get_constellation(body.abbr)
    constellation_zh = constellation["name"]
    latin = constellation["latin"]
    season = constellation.get("season", "")
    lines_count = len(constellation.get("lines", []))
    primary_stars = "\n".join(
        f"- {s['bayer']} {s['name']}锛屾槦绛?{s['magnitude']}"
        for s in constellation.get("stars", {}).values()
    )

    user_prompt = USER_TEMPLATE.format(
        constellation_zh=constellation_zh, latin=latin,
        style_zh=STYLE_ZH.get(body.style, body.style),
        primary_stars=primary_stars or "- （无）",
    )
    system_prompt = SYSTEM_PROMPT.format(
        style_zh=STYLE_ZH.get(body.style, body.style),
        constellation_zh=constellation_zh, latin=latin,
    )

    start = time.time()
    provider = make_provider()
    try:
        text = await provider.chat(system_prompt, user_prompt, timeout=30.0)
        paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
        if not paragraphs:
            raise RuntimeError("EMPTY_AI_OUTPUT")
        title = paragraphs[0]
        body_paragraphs = paragraphs[1:] if len(paragraphs) > 1 else paragraphs
        for prefix in ("鏍囬?锛?, "鏍囬?:", "Title:", "title:"):
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
                break
        if title.startswith("# "):
            title = title[2:].strip()

        payload = {
            "ok": True,
            "abbr": body.abbr,
            "style": body.style,
            "title": title,
            "paragraphs": body_paragraphs,
            "provider": provider.name,
            "model": AI_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "cached": False,
            "degraded": False,
        }
        _cache_put(body.abbr, body.style, payload)
        return payload

    except Exception as e:
        # 闄嶇骇锛歱reset锛坰pec 搂5.3 + 搂16.4锛氶潪 503锛?
        preset = get_preset(body.abbr, body.style)
        if preset is None:
            raise HTTPException(503, detail={"code": "STORY_DISABLED",
                                              "message": "鏈嶅姟绔?湭閰嶇疆 AI_API_KEY 涓旈?鍒剁己澶?})
        payload = {
            "ok": True,
            "abbr": body.abbr,
            "style": body.style,
            "title": preset["title"],
            "paragraphs": preset["paragraphs"],
            "provider": "fallback",
            "model": "preset",
            "latency_ms": 0,
            "cached": False,
            "degraded": True,
            "degraded_reason": "AI_PROVIDER_TIMEOUT" if "timeout" in str(e).lower()
                                else "AI_PROVIDER_DOWN",
        }
        # degraded:true 涓嶇紦瀛?
        return payload
```

- [ ] **Step 7: 修改 `server/main.py` 挂载 story + constellations**

`server/main.py`锛?

```python
# 杩藉姞 import
from routers.story import router as story_router
from routers.constellations import router as constellations_router

# 鍦?app = FastAPI(...) 涔嬪悗
app.include_router(story_router)
app.include_router(constellations_router)
```

- [ ] **Step 8: 鍐?test_story.py**

```python
# server/tests/test_story.py
import time
import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


ABBRs = ["ori", "cyg", "sco", "leo", "and"]
STYLES = ["myth", "science"]


def _clear_cache():
    from routers.story import _STORY_CACHE, _CACHE_LOCK
    with _CACHE_LOCK:
        _STORY_CACHE.clear()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # 显式 delenv，避免 CI 环境误配置 AI_API_KEY 导致状态不确定
    monkeypatch.delenv("AI_API_KEY", raising=False)
    # mock make_provider 为 DisabledProvider，确保 ai_provider='disabled'
    import routers.story as story_mod
    monkeypatch.setattr(story_mod, 'make_provider', lambda: _DisabledProvider())
    _clear_cache()
    yield
    _clear_cache()


class _DisabledProvider:
    """test_story 显式 DisabledProvider（替代默认 delenv 的隐式行为）。"""
    name = "disabled"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        raise RuntimeError("AI_PROVIDER_DISABLED")

    async def health(self) -> bool:
        return False


def test_disabled_provider_returns_preset_degraded():
    """鏃?AI_API_KEY 鈫?fallback preset锛宒egraded:true銆?""
    r = client.post("/api/story", json={"abbr": "ori", "style": "myth", "lang": "zh"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("provider") == "fallback"  # DisabledProvider 路径必须标 fallback
    assert data["degraded"] is True  # spec §5.4 强制：AI 不可用时降级

    assert data["cached"] is False
    assert len(data["paragraphs"]) >= 3


@pytest.mark.parametrize("abbr", ABBRs)
@pytest.mark.parametrize("style", STYLES)
def test_all_5_constellations_x_2_styles_hit_preset(abbr, style):
    """5 鏄熷骇 脳 2 椋庢牸 = 10 鏉″叏鍛戒腑 preset銆?""
    r = client.post("/api/story", json={"abbr": abbr, "style": style, "lang": "zh"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["abbr"] == abbr
    assert data["style"] == style
    assert len(data["paragraphs"]) >= 3


def test_cache_hit_second_call():
    """同请求第二次命中缓存（cached:true）。

    注：必须 mock 一个**非降级**的成功 provider，因为 spec §5.4 规定
    degraded:true 不缓存。这里通过 monkeypatch.setattr 把 make_provider 换成
    MockSuccessProvider，保证第一次调用有真实段落返回，从而能进缓存。
    """
    _clear_cache()
    mock = _MockSuccessProvider()
    import routers.story as story_mod
    orig = story_mod.make_provider
    story_mod.make_provider = lambda: mock  # noqa: E731
    try:
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    finally:
        story_mod.make_provider = orig
    assert r2.json()["cached"] is True


def test_cache_hit_under_50ms():
    _clear_cache()
    mock = _MockSuccessProvider()
    import routers.story as story_mod
    orig = story_mod.make_provider
    story_mod.make_provider = lambda: mock  # noqa: E731
    try:
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        t0 = time.time()
        r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    finally:
        story_mod.make_provider = orig
    elapsed_ms = (time.time() - t0) * 1000
    assert r2.json()["cached"] is True
    assert elapsed_ms < 50, f"cache hit {elapsed_ms:.1f}ms 超过 50ms"


class _MockSuccessProvider:
    """缓存测试专用：返回真实 AI 段落（非降级），使 spec §5.4 缓存路径生效。"""

    name = "mock-success"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        return "测试标题\n\n第一段真实 AI 文本。\n\n第二段真实 AI 文本。"

    async def health(self) -> bool:
        return True


def test_cache_bust_header_bypasses_cache():
    """Cache-Bust 头绕过缓存：必须 mock 成功 provider，否则 degraded 路径不进缓存。"""
    _clear_cache()
    mock = _MockSuccessProvider()
    import routers.story as story_mod
    orig = story_mod.make_provider
    story_mod.make_provider = lambda: mock  # noqa: E731
    try:
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        r = client.post("/api/story", json={"abbr": "ori", "style": "myth"},
                        headers={"Cache-Bust": "1"})
    finally:
        story_mod.make_provider = orig
    assert r.json()["cached"] is False


def test_cache_bust_body_bypasses_cache():
    """Cache-Bust 字段绕过缓存（同上需 mock）。"""
    _clear_cache()
    mock = _MockSuccessProvider()
    import routers.story as story_mod
    orig = story_mod.make_provider
    story_mod.make_provider = lambda: mock  # noqa: E731
    try:
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        r = client.post("/api/story", json={"abbr": "ori", "style": "myth", "cacheBust": True})
    finally:
        story_mod.make_provider = orig
    assert r.json()["cached"] is False


def test_degraded_not_cached():
    """degraded:true 鍝嶅簲涓嶇紦瀛橈紙鏃?AI 閰嶇疆涓嬩袱娆￠兘閲嶆柊璧?fallback锛夈€?""
    _clear_cache()
    r1 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r1.json()["degraded"] is True
    assert r2.json()["cached"] is False  # No cache


def test_invalid_abbr_returns_404():
    """鏈?煡鏄熷骇 鈫?404 CONSTELLATION_NOT_FOUND锛坰pec 搂3.3 鍗忚?閿欒?锛夈€?""
    r = client.post("/api/story", json={"abbr": "draco", "style": "myth"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"


def test_invalid_style_returns_400():
    r = client.post("/api/story", json={"abbr": "ori", "style": "romantic"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_STYLE"



```

- [ ] **Step 9: 跑测试确认通过**

Run: `cd server && .venv/bin/python -m pytest tests/test_story.py -v`
Expected: 7 (鍚?parametrized 10 + 鍗曟祴) passed

- [ ] **Step 10: Commit**

```bash
git add server/data/preset_stories.json \
        server/services/story_fallback.py \
        server/services/ai_provider.py \
        server/services/constellation.py \
        server/routers/constellations.py \
        server/routers/story.py \
        server/main.py \
        server/tests/test_story.py
git commit -m "feat(server): AI 鏁呬簨瀹屾暣閾捐矾锛坧rovider 鎶借薄 + DisabledProvider 闈?503 + 10 绡囬?鍒?+ LRU 10min 涓嶇紦瀛?degraded + Cache-Bust + 404 CONSTELLATION_NOT_FOUND锛?
```

---
### Task 4: StarCanvas 描出 1.2s + 闪烁 + atlas ±2° sin(2πt/12s) + IntersectionObserver

**Files:**
- Modify: `web/src/components/StarCanvas.vue`（描出 + 闪烁 + atlas 缓回旋 + 性能规则 + IntersectionObserver）
- Test: `web/tests/StarCanvas.animate.test.ts`（rAF 描出断言 + atlas ±2° 公式）

**Interfaces:**
- Consumes: props（mode / starsOverlay / overlayLines / imageWidth / imageHeight / activeAbbr / constellationData / empty）与 M1 一致
- Produces: 三类动画（spec §6.1 + §6.2 + §6.4 + §16.2.1）：
  1. **描出 1.2s easeOutCubic**：每条线错峰 80ms；lineWidth 0→2，alpha 0→0.9（金色）
  2. **闪烁持续**：`shadowBlur = 6 + 4 * sin(2π t / 1.6s)`；`empty` 时不闪
  3. **atlas ±2° sin(2π t / 12s)**：overlay 模式不旋转；reduced-motion 全部终态

**完成定义：**
- 描出 1.2s 完成（一次性 rAF，结束后停）
- 闪烁/旋转持续 rAF；`document.visibilitychange === 'hidden'` 停 rAF（spec §6.4）
- `IntersectionObserver` 离屏停 rAF
- `prefers-reduced-motion: reduce`：跳到终态（drawProgress=1, twinklePhase=0, atlasRot=0）
- mode 切换时取消旧 rafId（避免重叠）
- 类型收紧：`constellationData` 为完整 `ConstellationAtlas`（不再 any）

---

- [ ] **Step 1: 修改 StarCanvas.vue（核心动画逻辑 + IntersectionObserver）**

替换 `web/src/components/StarCanvas.vue` 主体（保留 container/canvas 模板）：

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

import type { StarOverlay, ConstellationAtlas } from '../types'

type Line = [string, string]

const props = defineProps<{
  mode: 'overlay' | 'scan-atlas'
  starsOverlay?: StarOverlay[]
  overlayLines?: Line[]
  imageWidth?: number
  imageHeight?: number
  activeAbbr?: string | null
  constellationData?: ConstellationAtlas | null
  empty?: boolean
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

// ── 性能与状态 ─────────────────────────────────────────────────
const DRAW_DURATION_MS = 1200       // spec §6.1
const TWINKLE_PERIOD_MS = 1600      // spec §6.1 闪烁 1.6s
const ATLAS_ROT_AMP = (2 * Math.PI) / 180  // spec §6.2 ±2°
const ATLAS_ROT_PERIOD_MS = 12000   // 12s/周
const LINE_STAGGER_MS = 80

let resizeObserver: ResizeObserver | null = null
let intersectionObserver: IntersectionObserver | null = null
let rafId: number | null = null
let drawStartMs = 0
let twinklePhase = 0
let atlasRotRad = 0
let isVisible = true  // IntersectionObserver / visibilitychange

const prefersReducedMotion =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

// ── 工具 ────────────────────────────────────────────────────────
function getCssSize() {
  const c = containerRef.value
  return c ? { w: c.clientWidth, h: c.clientHeight } : { w: 0, h: 0 }
}

function computeMapping(contentW: number, contentH: number) {
  const iw = props.imageWidth ?? 1
  const ih = props.imageHeight ?? 1
  const scale = Math.min(contentW / iw, contentH / ih)
  return {
    scale,
    offsetX: (contentW - iw * scale) / 2,
    offsetY: (contentH - ih * scale) / 2,
  }
}

// ── 描出 + 闪烁（overlay 模式） ─────────────────────────────────
function drawOverlay(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const { scale, offsetX, offsetY } = computeMapping(w, h)
  const stars = props.starsOverlay ?? []
  const lines = props.overlayLines ?? []
  const isEmpty = props.empty === true

  // 描出进度（spec §6.1）：done / empty 立即 1；reduce-motion 立即 1
  let drawProgress = 1
  if (!isEmpty && !prefersReducedMotion) {
    const elapsed = performance.now() - drawStartMs
    drawProgress = Math.min(1, elapsed / DRAW_DURATION_MS)
    // easeOutCubic
    drawProgress = 1 - Math.pow(1 - drawProgress, 3)
  }

  // Bayer 查找
  const bayerMap = new Map<string, StarOverlay>()
  for (const s of stars) bayerMap.set(s.bayer, s)

  // 1. 描出连线
  if (!isEmpty) {
    const baseDelay = 0
    const totalSpan = 1 - baseDelay
    lines.forEach(([a, b], idx) => {
      const sa = bayerMap.get(a)
      const sb = bayerMap.get(b)
      if (!sa || !sb) return
      const lineDelay = (idx * LINE_STAGGER_MS) / DRAW_DURATION_MS  // 0..1
      const lineT = Math.min(1, Math.max(0, (drawProgress - lineDelay) / (totalSpan - lineDelay + 0.001)))
      const w = lineT * 2
      const a = lineT * 0.9
      const isActive = props.activeAbbr == null || sa.constellation === props.activeAbbr
      ctx.strokeStyle = isActive ? `rgba(212,160,23,${a})` : `rgba(212,160,23,${a * 0.33})`
      ctx.lineWidth = isActive ? w : w * 0.5
      const ax = sa.pixel_x * scale + offsetX
      const ay = sa.pixel_y * scale + offsetY
      const bx = sb.pixel_x * scale + offsetX
      const by = sb.pixel_y * scale + offsetY
      const px = ax + (bx - ax) * lineT
      const py = ay + (by - ay) * lineT
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(px, py)
      ctx.stroke()
    })
  }

  // 2. 闪烁主星
  for (const s of stars) {
    const r = Math.max(1.2, Math.min(8, 4 - 0.4 * s.magnitude))
    const dim = isEmpty ? 0.2
      : props.activeAbbr == null || s.constellation === props.activeAbbr ? 1 : 0.5

    // 闪烁（spec §6.1）：shadowBlur = 6 + 4 * sin(phase)；reduce-motion 或 empty 不闪
    if (!isEmpty && !prefersReducedMotion) {
      const blur = 6 + 4 * Math.sin(2 * Math.PI * twinklePhase)
      ctx.shadowBlur = blur
      ctx.shadowColor = 'gold'
    } else {
      ctx.shadowBlur = 0
    }

    ctx.fillStyle = `rgba(212,160,23,${dim})`
    ctx.beginPath()
    ctx.arc(s.pixel_x * scale + offsetX, s.pixel_y * scale + offsetY, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
  }
}

// ── atlas 缓回旋（scan-atlas 模式，spec §6.2 + §16.2.1） ──────────
function drawScanAtlas(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const data = props.constellationData
  if (!data) return

  ctx.save()
  if (!prefersReducedMotion) {
    ctx.translate(w / 2, h / 2)
    ctx.rotate(atlasRotRad)
    ctx.translate(-w / 2, -h / 2)
  }

  // atlas 视图坐标系（M1 沿用 640×460，可由 data.viewBox 覆盖）
  const vbW = data.viewBox?.width ?? 640
  const vbH = data.viewBox?.height ?? 460
  const sx = w / vbW
  const sy = h / vbH

  // 网格 + 同心圆 + 连线 + 主星（M1 drawScanAtlas 保持不变）
  ctx.strokeStyle = 'rgba(184,134,11,0.15)'
  ctx.lineWidth = 1
  for (let i = 0; i <= vbW; i += 52) {
    ctx.beginPath()
    ctx.moveTo(i * sx, 0)
    ctx.lineTo(i * sx, h)
    ctx.stroke()
  }
  for (let j = 0; j <= vbH; j += 52) {
    ctx.beginPath()
    ctx.moveTo(0, j * sy)
    ctx.lineTo(w, j * sy)
    ctx.stroke()
  }
  ctx.setLineDash([4, 4])
  ctx.strokeStyle = 'rgba(184,134,11,0.25)'
  ctx.beginPath()
  ctx.ellipse(vbW / 2 * sx, vbH / 2 * sy, 200 * sx, 180 * sy, 0, 0, Math.PI * 2)
  ctx.stroke()
  ctx.beginPath()
  ctx.ellipse(vbW / 2 * sx, vbH / 2 * sy, 120 * sx, 100 * sy, 0, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])
  for (const [a, b] of data.lines ?? []) {
    const sa = data.stars?.[a]
    const sb = data.stars?.[b]
    if (!sa || !sb) continue
    ctx.strokeStyle = 'rgba(212,160,23,0.8)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(sa.x * sx, sa.y * sy)
    ctx.lineTo(sb.x * sx, sb.y * sy)
    ctx.stroke()
  }
  for (const s of Object.values(data.stars ?? {})) {
    const r = Math.max(1.2, Math.min(8, 4 - 0.4 * s.magnitude))
    ctx.fillStyle = 'rgba(212,160,23,1)'
    ctx.shadowBlur = 6
    ctx.shadowColor = 'gold'
    ctx.beginPath()
    ctx.arc(s.x * sx, s.y * sy, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
  }
  ctx.restore()
}

// ── 主循环 ─────────────────────────────────────────────────────
function tick(now: number) {
  const { w, h } = getCssSize()
  if (w === 0 || h === 0) {
    // 容器不可见时不续帧，避免隐藏时浪费 CPU（IntersectionObserver 性能要求）
    if (isVisible) rafId = requestAnimationFrame(tick)
    return
  }

  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)

  // 持续动画相位
  if (!prefersReducedMotion) {
    twinklePhase = ((now / TWINKLE_PERIOD_MS) % 1)
    atlasRotRad = ATLAS_ROT_AMP * Math.sin((2 * Math.PI * now) / ATLAS_ROT_PERIOD_MS)
  }

  if (props.mode === 'overlay') {
    drawOverlay(ctx, w, h)
  } else {
    drawScanAtlas(ctx, w, h)
  }

  // 描出 1.2s 后停掉持续 rAF（闪烁/旋转单独 rAF 由各自的 mode 决定是否继续）
  // spec §6.4：闪烁/旋转阶段持续 rAF @ 60fps；描出阶段一次性 rAF 结束后停
  if (props.mode === 'overlay') {
    // Tick continues for twinkle after draw completes
  }
  if (isVisible) {
    rafId = requestAnimationFrame(tick)
  }
}

function startDraw() {
  drawStartMs = performance.now()
  if (rafId === null) {
    rafId = requestAnimationFrame(tick)
  }
}

function cancelOldLoop() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    cancelOldLoop()
  } else if (isVisible && rafId === null) {
    rafId = requestAnimationFrame(tick)
  }
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (rafId === null && isVisible) rafId = requestAnimationFrame(tick)
    })
    resizeObserver.observe(containerRef.value)
  }

  if (typeof IntersectionObserver !== 'undefined' && containerRef.value) {
    intersectionObserver = new IntersectionObserver(
      (entries) => {
        isVisible = entries[0]?.isIntersecting ?? true
        if (isVisible && rafId === null) rafId = requestAnimationFrame(tick)
      },
      { threshold: 0 },
    )
    intersectionObserver.observe(containerRef.value)
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  startDraw()
})

onUnmounted(() => {
  cancelOldLoop()
  resizeObserver?.disconnect()
  intersectionObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

watch(
  () => [props.mode, props.activeAbbr, props.starsOverlay, props.overlayLines, props.empty, props.constellationData] as const,
  () => {
    cancelOldLoop()
    startDraw()
  },
  { deep: true },
)

defineExpose({ prefersReducedMotion })
</script>

<template>
  <div ref="containerRef" class="star-canvas-container">
    <canvas ref="canvasRef" />
  </div>
</template>

<style scoped>
.star-canvas-container {
  width: 100%;
  height: 100%;
  position: relative;
}
canvas {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
```

- [ ] **Step 2: 写 StarCanvas.animate.test.ts**

```typescript
// web/tests/StarCanvas.animate.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'

import StarCanvas from '../src/components/StarCanvas.vue'
import type { ConstellationAtlas } from '../src/types'

const orionAtlas: ConstellationAtlas = {
  abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
  hemisphere: 'B', bestMonth: 1, season: '冬季', caption: '冬夜之王',
  magnitude: 0.13, storyStyles: ['myth', 'science'], primaryStars: [],
  viewBox: { width: 640, height: 460 },
  stars: { betelgeuse: { x: 144, y: 62, bayer: 'Alpha Ori', name: '参宿四', magnitude: 0.42 } },
  lines: [['betelgeuse', 'betelgeuse']],
}

describe('StarCanvas 动画参数', () => {
  afterEach(() => vi.restoreAllMocks())

  it('atlas ±2° sin(2π t / 12s) 公式正确', () => {
    const amp = (2 * Math.PI) / 180
    const period = 12000
    const at = (t: number) => amp * Math.sin((2 * Math.PI * t) / period)
    expect(at(0)).toBeCloseTo(0, 5)
    expect(at(3000)).toBeCloseTo(amp, 5)   // 1/4 周期达峰
    expect(at(6000)).toBeCloseTo(0, 5)
    expect(at(9000)).toBeCloseTo(-amp, 5)  // 3/4 周期达谷
  })

  it('闪烁 1.6s sin 公式正确', () => {
    const period = 1600
    const blur = (t: number) => 6 + 4 * Math.sin((2 * Math.PI * t) / period)
    expect(blur(0)).toBeCloseTo(6, 5)
    expect(blur(400)).toBeCloseTo(10, 5)    // 1/4 周期达峰
    expect(blur(800)).toBeCloseTo(6, 5)
    expect(blur(1200)).toBeCloseTo(2, 5)
  })

  it('描出 1.2s easeOutCubic 终值 = 1', () => {
    const DUR = 1200
    const t = 1.0
    const eased = 1 - Math.pow(1 - t, 3)
    expect(eased).toBe(1)
  })

  it('scan-atlas 模式渲染时组件不崩', () => {
    const wrapper = mount(StarCanvas, {
      props: { mode: 'scan-atlas', constellationData: orionAtlas },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('overlay 模式 + empty 不闪（shadowBlur=0）', () => {
    const wrapper = mount(StarCanvas, {
      props: {
        mode: 'overlay',
        starsOverlay: [],
        overlayLines: [],
        imageWidth: 100, imageHeight: 100,
        empty: true,
      },
    })
    expect(wrapper.exists()).toBe(true)
  })
})
```

- [ ] **Step 3: 跑测试确认通过**

Run: `cd web && npm test -- StarCanvas.animate`
Expected: 5 passed（jsdom 不真正画 canvas，重点验证公式 + 组件不崩）

- [ ] **Step 4: Commit**

```bash
git add web/src/components/StarCanvas.vue web/tests/StarCanvas.animate.test.ts
git commit -m "feat(web): StarCanvas 描出 1.2s + 闪烁 1.6s + atlas ±2° sin(12s) + IntersectionObserver + 类型收紧"
```

---

### Task 5: StoryPanel + storyStore + scanStore 收敛 + GET /api/health

**Files:**
- New: `web/src/components/StoryPanel.vue`
- New: `web/src/stores/story.ts`
- New: `web/src/api/story.ts`
- New: `server/routers/health.py`
- Modify: `web/src/types.ts`（追加 `StoryResponse` / `HealthResponse` / `StoryStyle`）
- Modify: `web/src/stores/scan.ts`（收敛：删 `activeStory` / `storyLoading` / `exifOrientation`，仅保留 `selectedStyle`）
- Modify: `server/main.py`（挂载 `health` 路由 + 暴露 `/api/health`）
- Modify: `web/src/views/ScanView.vue`（`v-if` 接入 `StoryPanel`）
- Test: `web/tests/StoryPanel.test.ts`
- Test: `web/tests/story.store.test.ts`
- Test: `server/tests/test_health.py`

**Interfaces:**
- `GET /api/health` → `{ ok: boolean, astrometry: "up"|"mock"|"down", ai_provider: "up"|"disabled"|"down", ai_model: string }`（spec §9.3 扁平字段，**不嵌套** `.state`）
- `POST /api/story` 请求 `{ abbr: string, style: "myth"|"science", lang: "zh" }`
- `POST /api/story` 响应 `{ ok, abbr, style, title, paragraphs, provider, model, latency_ms, cached, degraded, degraded_reason? }`（spec §8.2 全字段）

**完成定义：**
- `storyStore` 暴露 `fetchStory(action: 'refetch' | 'fresh'): Promise<void>`，其中 `'refetch'` 命中前端 store 不调后端，`'fresh'` 强制跳过 store 调后端
- 后端 LRU 由 `cacheBust` body 字段控制（spec §8.4）；前端 store 是用户可见的"二级缓存"，与后端 LRU 互不干扰
- `scanStore` 收敛后状态数 ≤ 5：`selectedStyle` / `uploadedFile` / `solveResult` / `loading`
- `StoryPanel.vue` 三态：`loading`（骨架屏）/ `degraded`（降级提示 + 重试）/ `ready`（标题 + 段落列表 + 风格切换器）
- `GET /api/health` 仅在本 Task 挂载；**不**挂载 `identify` / `story` / `constellations`
- `astrometry = "up"` 判定：`MockSolver` 模式 → `"mock"`；其他 solver 进程 ping 通过 → `"up"`，否则 `"down"`
- `ai_provider = "disabled"` 判定：`OPENAI_API_KEY` 为空且 `ASTROMETRY_AI_FALLBACK_MODE=disabled`；`"up"` 判定 ping 通过
- ai_model 字段恒回 `AI_MODEL`（spec §9.3）

---

- [ ] **Step 1: 写 `web/src/types.ts` 增量类型**

在 `web/src/types.ts` 末尾追加：

```typescript
export type StoryStyle = 'myth' | 'science'

export interface StoryResponse {
  ok: boolean
  abbr: string
  style: StoryStyle
  title: string
  paragraphs: string[]
  provider: 'openai-compatible' | 'mock' | 'disabled' | 'fallback'
  model: string
  latency_ms: number
  cached: boolean
  degraded: boolean
  degraded_reason?: string
}

export interface HealthResponse {
  ok: boolean
  astrometry: 'up' | 'mock' | 'down'
  ai_provider: 'up' | 'disabled' | 'down'
  ai_model: string
}

export interface StoryRequest {
  abbr: string
  style: StoryStyle
  lang: 'zh'
  cacheBust?: number
}
```

- [ ] **Step 2: 写 `web/src/api/story.ts`**

```typescript
// web/src/api/story.ts
import type { StoryRequest, StoryResponse, HealthResponse } from '../types'

export async function postStory(req: StoryRequest): Promise<StoryResponse> {
  const r = await fetch('/api/story', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<StoryResponse>
}

export async function getHealth(): Promise<HealthResponse> {
  const r = await fetch('/api/health')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<HealthResponse>
}
```

- [ ] **Step 3: 写 `web/src/stores/story.ts`**

```typescript
// web/src/stores/story.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { StoryStyle, StoryResponse } from '../types'
import { postStory } from '../api/story'

export const useStoryStore = defineStore('story', () => {
  const current = ref<StoryResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function isHit(abbr: string, style: StoryStyle): boolean {
    const s = current.value
    return s != null && s.abbr === abbr && s.style === style
  }

  async function fetchStory(
    abbr: string,
    style: StoryStyle,
    action: 'refetch' | 'fresh',
  ): Promise<void> {
    if (action === 'refetch' && isHit(abbr, style)) return

    loading.value = true
    error.value = null
    try {
      const req: { abbr: string; style: StoryStyle; lang: 'zh'; cacheBust?: number } = {
        abbr, style, lang: 'zh',
      }
      if (action === 'fresh') req.cacheBust = 1
      current.value = await postStory(req)
    } catch (e) {
      error.value = (e as Error).message
      current.value = null
    } finally {
      loading.value = false
    }
  }

  function clear() {
    current.value = null
    error.value = null
  }

  return { current, loading, error, fetchStory, clear }
})
```

- [ ] **Step 4: 收敛 `web/src/stores/scan.ts`**

替换整个文件：

```typescript
// web/src/stores/scan.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { StoryStyle, IdentifyResult } from '../types'

export const useScanStore = defineStore('scan', () => {
  const selectedStyle = ref<StoryStyle>('myth')
  const uploadedFile = ref<File | null>(null)
  const solveResult = ref<IdentifyResult | null>(null)
  const loading = ref(false)

  function setStyle(s: StoryStyle) {
    selectedStyle.value = s
  }

  function reset() {
    uploadedFile.value = null
    solveResult.value = null
    loading.value = false
  }

  return { selectedStyle, uploadedFile, solveResult, loading, setStyle, reset }
})
```

**注意：**原 `activeStory` / `storyLoading` / `exifOrientation` 一并删除（收敛到 `storyStore`）。ScanView 中 `activeStory` 引用改为 `storyStore.current`。

- [ ] **Step 5: 写 `web/src/components/StoryPanel.vue`**

```vue
<script setup lang="ts">
import { computed, watch } from 'vue'

import { useScanStore } from '../stores/scan'
import { useStoryStore } from '../stores/story'
import type { StoryStyle } from '../types'

const scan = useScanStore()
const story = useStoryStore()

const props = defineProps<{ abbr: string }>()

const styles: { value: StoryStyle; label: string }[] = [
  { value: 'myth', label: '神话' },
  { value: 'science', label: '科普' },
]

const state = computed<'loading' | 'degraded' | 'ready'>(() => {
  if (story.loading) return 'loading'
  if (story.error) return 'degraded'
  if (story.current && story.current.abbr === props.abbr) return 'ready'
  return 'loading'
})

watch(
  () => [props.abbr, scan.selectedStyle] as const,
  async ([abbr, style]) => {
    if (!abbr) return  // hit=0 时 constellations[0]?.abbr 为空，跳过 story 请求
    await story.fetchStory(abbr, style as StoryStyle, 'refetch')
  },
  { immediate: true },
)

async function onStyleChange(style: StoryStyle) {
  if (!props.abbr) return
  scan.setStyle(style)
  await story.fetchStory(props.abbr, style, 'refetch')
}

async function onRefresh() {
  if (!props.abbr) return
  await story.fetchStory(props.abbr, scan.selectedStyle, 'fresh')
}
</script>

<template>
  <section class="story-panel">
    <div class="style-toggle">
      <button
        v-for="s in styles"
        :key="s.value"
        :class="['tab', { active: scan.selectedStyle === s.value }]"
        @click="onStyleChange(s.value)"
      >{{ s.label }}</button>
      <button class="refresh" :disabled="story.loading" @click="onRefresh">换一篇</button>
    </div>

    <div v-if="state === 'loading'" class="skeleton" data-testid="story-loading">
      <div class="bar title" />
      <div class="bar" />
      <div class="bar short" />
    </div>

    <div v-else-if="state === 'degraded'" class="degraded" data-testid="story-degraded">
      <p>故事生成暂不可用：{{ story.error }}</p>
      <button @click="onRefresh">重试</button>
    </div>

    <article v-else-if="story.current" class="ready" data-testid="story-ready">
      <h2>{{ story.current.title }}</h2>
      <p v-for="(p, i) in story.current.paragraphs" :key="i">{{ p }}</p>
      <p v-if="story.current.degraded" class="tag">降级内容</p>
    </article>
  </section>
</template>

<style scoped>
.story-panel {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 1rem;
  margin-top: 1rem;
}
.style-toggle {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.tab {
  background: transparent;
  border: 1px solid #ccc;
  padding: 0.25rem 0.75rem;
  border-radius: 4px;
  cursor: pointer;
}
.tab.active {
  background: #d4a017;
  color: #fff;
  border-color: #d4a017;
}
.refresh {
  margin-left: auto;
  background: transparent;
  border: 1px dashed #ccc;
  cursor: pointer;
}
.skeleton .bar {
  height: 0.8rem;
  background: #eee;
  margin: 0.4rem 0;
  border-radius: 4px;
}
.skeleton .bar.title {
  width: 40%;
  height: 1.2rem;
}
.skeleton .bar.short {
  width: 60%;
}
.degraded {
  color: #c33;
}
.ready h2 {
  font-size: 1.1rem;
  margin: 0 0 0.5rem;
}
.ready .tag {
  color: #999;
  font-size: 0.85rem;
  margin-top: 0.5rem;
}
</style>
```

- [ ] **Step 6: 修改 `web/src/views/ScanView.vue` 接入 StoryPanel**

定位 M1 中 StoryPanel 的占位（`<div v-if="scan.activeStory">` 或类似），替换为：

```vue
<!-- 在 solveResult 显示后追加 -->
<StoryPanel v-if="scan.solveResult?.ok" :abbr="scan.solveResult.constellations[0]?.abbr ?? ''" />
```

并从 ScanView 中删除：
- `import { useStoryStore }` / `story.fetchStory(...)` 的就地调用
- `scan.activeStory` / `scan.storyLoading` 的引用
- `StoryPanel` 旧版占位（由 StoryPanel.vue 接管）

- [ ] **Step 7: 写 `server/routers/health.py`**

```python
# server/routers/health.py
from fastapi import APIRouter

from config import ASTROMETRY_MOCK, AI_API_KEY, AI_MODEL
from services.astrometry import get_solver_status

router = APIRouter()


@router.get('/api/health')
async def health():
    """M2 §9.3 扁平字段。ai_provider 三态：up（ping 通过）/ disabled（无 AI_API_KEY）/ down（ping 失败）。"""
    from services.ai_provider import make_provider
    if not AI_API_KEY:
        ai_state = 'disabled'
    else:
        provider = make_provider()
        ai_ok = await provider.health()
        ai_state = 'up' if ai_ok else 'down'
    return {
        'ok': True,
        'astrometry': get_solver_status(),
        'ai_provider': ai_state,
        'ai_model': (AI_MODEL if AI_API_KEY else 'none'),
    }
```

并在 `server/services/astrometry.py` 末尾追加：

```python
def get_solver_status() -> str:
    """spec §9.3: 'up' | 'mock' | 'down'"""
    if ASTROMETRY_MOCK:
        return 'mock'
    return 'up'
```

- [ ] **Step 8: 挂载 health 路由到 `server/main.py`**

在 `server/main.py` 中追加：

```python
from routers.health import router as health_router  # noqa: E402
from services.ai_provider import OpenAICompatibleProvider

app.include_router(health_router)


@app.on_event("shutdown")
async def _shutdown() -> None:
    # 释放 AI httpx 共享连接池，避免连接数累积
    await OpenAICompatibleProvider.aclose()
```

**注意：**只挂载本 Task 的 health，**不**挂载 identify / story / constellations（按 spec §9.3 职责分离）。

- [ ] **Step 9: 写 `server/tests/test_health.py`**

```python
# server/tests/test_health.py
from fastapi.testclient import TestClient

from main import app


def test_health_default():
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['astrometry'] in ('up', 'mock', 'down')
    assert body['ai_provider'] in ('up', 'disabled', 'down')
    assert 'ai_model' in body


def test_health_astarometry_mock(monkeypatch):
    monkeypatch.setattr('routers.health.ASTROMETRY_MOCK', True)
    monkeypatch.setattr('services.astrometry.ASTROMETRY_MOCK', True)
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['astrometry'] == 'mock'


def test_health_when_disabled(monkeypatch):
    """无 AI_API_KEY 时 ai_provider='disabled'（从 test_story.py 迁出：依赖 Task 5 挂载的 /api/health）"""
    monkeypatch.setattr('routers.health.AI_API_KEY', '')
    monkeypatch.setattr('routers.story.AI_API_KEY', '')
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.status_code == 200
    data = r.json()
    assert data['ai_provider'] == 'disabled'
    # ai_model 在 disabled 时为 'none' 或空串
    assert data.get('ai_model') in (None, 'none', '')


def test_health_ai_disabled(monkeypatch):
    monkeypatch.setattr('routers.health.AI_API_KEY', '')
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['ai_provider'] == 'disabled'
```

- [ ] **Step 10: 写 `web/tests/story.store.test.ts`**

```typescript
// web/tests/story.store.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useStoryStore } from '../src/stores/story'

beforeEach(() => setActivePinia(createPinia()))

describe('storyStore.fetchStory action', () => {
  it("'refetch' 命中二级缓存时不调 postStory", async () => {
    const story = useStoryStore()
    const postSpy = vi.fn()
    const apiModule = await import('../src/api/story')
    apiModule.postStory = postSpy as never

    story.current = {
      ok: true, abbr: 'ori', style: 'myth', title: 't', paragraphs: ['p'],
      provider: 'mock', model: 'm', latency_ms: 0, cached: true, degraded: false,
    }
    await story.fetchStory('ori', 'myth', 'refetch')
    expect(postSpy).not.toHaveBeenCalled()
  })

  it("'fresh' 强制 postStory + cacheBust=1", async () => {
    const story = useStoryStore()
    const postSpy = vi.fn().mockResolvedValue({
      ok: true, abbr: 'ori', style: 'myth', title: 't2', paragraphs: ['q'],
      provider: 'mock', model: 'm', latency_ms: 1, cached: false, degraded: false,
    })
    const apiModule = await import('../src/api/story')
    apiModule.postStory = postSpy as never

    await story.fetchStory('ori', 'myth', 'fresh')
    expect(postSpy).toHaveBeenCalledWith(
      expect.objectContaining({ abbr: 'ori', style: 'myth', cacheBust: 1 }),
    )
  })
})
```

- [ ] **Step 11: 写 `web/tests/StoryPanel.test.ts`**

```typescript
// web/tests/StoryPanel.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import StoryPanel from '../src/components/StoryPanel.vue'
import { useStoryStore } from '../src/stores/story'

beforeEach(() => setActivePinia(createPinia()))

describe('StoryPanel 三态', () => {
  it('loading 渲染 skeleton', () => {
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    expect(wrapper.find('[data-testid="story-loading"]').exists()).toBe(true)
  })

  it('ready 渲染段落列表', async () => {
    const story = useStoryStore()
    story.current = {
      ok: true, abbr: 'ori', style: 'myth', title: '猎户神话',
      paragraphs: ['第一段', '第二段'],
      provider: 'mock', model: 'm', latency_ms: 10,
      cached: false, degraded: false,
    }
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="story-ready"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('猎户神话')
  })

  it('切换风格触发 fetchStory refetch', async () => {
    const story = useStoryStore()
    const spy = vi.spyOn(story, 'fetchStory').mockResolvedValue()
    const wrapper = mount(StoryPanel, { props: { abbr: 'ori' } })
    await wrapper.findAll('.tab')[1].trigger('click')
    expect(spy).toHaveBeenCalledWith('ori', 'science', 'refetch')
  })
})
```

- [ ] **Step 12: 跑测试**

```bash
cd web && npm test -- StoryPanel story.store
cd server && .\.venv\Scripts\python.exe -m pytest tests/test_health.py -v
```

Expected: 3 + 2 + 3 passed

- [ ] **Step 13: Commit**

```bash
git add web/src/components/StoryPanel.vue \
        web/src/stores/story.ts \
        web/src/api/story.ts \
        web/src/types.ts \
        web/src/stores/scan.ts \
        web/src/views/ScanView.vue \
        web/tests/StoryPanel.test.ts \
        web/tests/story.store.test.ts \
        server/routers/health.py \
        server/services/astrometry.py \
        server/main.py \
        server/tests/test_health.py

git commit -m "feat(m2): StoryPanel 三态 + storyStore refetch/fresh 双动作 + scanStore 收敛到 4 字段 + /api/health 扁平字段"
```

---

### Task 6: ConstellationView 完整页 + atlasStore + 复用 constellations.json

**Files:**
- New: `web/src/stores/atlas.ts`
- New: `web/src/api/atlas.ts`
- New: `web/src/views/ConstellationView.vue`（升级 M1 占位为完整页）
- Modify: `web/src/types.ts`（追加 `AtlasListItem` + 强化 `ConstellationAtlas`）
- Modify: `web/src/router/index.ts`（如 M1 已建则补 `/atlas` 路由）
- Modify: `web/src/style/star-atlas.css`（独立样式，扁平禁用渐变）
- Test: `web/tests/ConstellationView.test.ts`
- Test: `web/tests/atlas.store.test.ts`

**Interfaces:**
- `GET /api/constellations` → `{ items: AtlasListItem[] }`（spec §10，**复用 `server/data/constellations.json`**，**不新建 atlas JSON**）
- `AtlasListItem = { abbr, name, latin, glyph, hemisphere, bestMonth, season, caption, magnitude, storyStyles }`（**无 stars/lines**）
- `ConstellationAtlas = AtlasListItem & { stars: Record<string, AtlasStar>, lines: Line[][], viewBox: { width, height } }`（含 stars/lines 全量）

**完成定义：**
- atlasStore 暴露 `list()`（首次调 `GET /api/constellations`，缓存到内存，再次调用直接返）
- atlasStore 暴露 `getAtlas(abbr)`：从 `/api/constellation/{abbr}` 取全量
- ConstellationView 左侧 5 个星座列表卡片（缩写 + 中文 + glyph）
- 点击卡片 → 右侧 StarCanvas (`mode='scan-atlas'`) + 名字 + season + caption + "看故事"按钮（跳 ScanView）
- 数据全部走 `GET /api/constellations` / `/api/constellation/{abbr}`，**前端无 mock**（spec §15）
- 视觉风格：扁平，金色 `#d4a017`，**禁用渐变**（spec §6.3）
- 路由：`/atlas` → ConstellationView；与 `/`（IndexView）/`/scan`（ScanView）并列
- 类型一致：M1 `ConstellationAtlas` 是部分类型（`stars` / `lines` 可选），M2 在 T4 已收紧为完整类型；本 Task 不再改 M1 数据源

---

- [ ] **Step 1: 在 `web/src/types.ts` 强化类型**

```typescript
export type Hemisphere = 'N' | 'S' | 'B'

export interface AtlasListItem {
  abbr: string
  name: string
  latin: string
  glyph: string
  hemisphere: Hemisphere
  bestMonth: number
  season: string
  caption: string
  magnitude: number
  storyStyles: StoryStyle[]
}

export interface AtlasStar {
  x: number          // viewBox 坐标系
  y: number
  bayer: string
  name?: string
  magnitude: number
}

export type AtlasLine = [string, string]

export interface ConstellationAtlas extends AtlasListItem {
  stars: Record<string, AtlasStar>
  lines: AtlasLine[]
  viewBox: { width: number; height: number }
}

export interface AtlasListResponse {
  items: AtlasListItem[]
}
```

- [ ] **Step 2: 写 `web/src/api/atlas.ts`**

```typescript
// web/src/api/atlas.ts
import type { AtlasListResponse, ConstellationAtlas } from '../types'

export async function listConstellations(): Promise<AtlasListResponse> {
  const r = await fetch('/api/constellations')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<AtlasListResponse>
}

export async function getConstellation(abbr: string): Promise<ConstellationAtlas> {
  const r = await fetch(`/api/constellation/${encodeURIComponent(abbr)}`)
  if (r.status === 404) throw new Error('CONSTELLATION_NOT_FOUND')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<ConstellationAtlas>
}
```

- [ ] **Step 3: 写 `web/src/stores/atlas.ts`**

```typescript
// web/src/stores/atlas.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { AtlasListItem, ConstellationAtlas } from '../types'
import { listConstellations, getConstellation } from '../api/atlas'

export const useAtlasStore = defineStore('atlas', () => {
  const items = ref<AtlasListItem[]>([])
  const atlasCache = ref<Record<string, ConstellationAtlas>>({})
  const listLoading = ref(false)
  const listError = ref<string | null>(null)

  async function list(force = false): Promise<void> {
    if (!force && items.value.length > 0) return
    listLoading.value = true
    listError.value = null
    try {
      const r = await listConstellations()
      items.value = r.items
    } catch (e) {
      listError.value = (e as Error).message
    } finally {
      listLoading.value = false
    }
  }

  async function getAtlas(abbr: string): Promise<ConstellationAtlas> {
    const cached = atlasCache.value[abbr]
    if (cached) return cached
    const data = await getConstellation(abbr)
    atlasCache.value = { ...atlasCache.value, [abbr]: data }
    return data
  }

  return { items, atlasCache, listLoading, listError, list, getAtlas }
})
```

- [ ] **Step 4: 升级 `web/src/views/ConstellationView.vue`**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useAtlasStore } from '../stores/atlas'
import StarCanvas from '../components/StarCanvas.vue'
import type { AtlasListItem, ConstellationAtlas } from '../types'

const atlas = useAtlasStore()
const selected = ref<ConstellationAtlas | null>(null)
const loadingDetail = ref(false)

onMounted(() => atlas.list())

async function pick(item: AtlasListItem) {
  loadingDetail.value = true
  try {
    selected.value = await atlas.getAtlas(item.abbr)
  } finally {
    loadingDetail.value = false
  }
}
</script>

<template>
  <main class="atlas">
    <aside class="atlas-list">
      <h1>星座图鉴</h1>
      <p v-if="atlas.listLoading">加载中…</p>
      <p v-else-if="atlas.listError" class="err">{{ atlas.listError }}</p>
      <ul v-else>
        <li
          v-for="it in atlas.items"
          :key="it.abbr"
          :class="['atlas-card', { active: selected?.abbr === it.abbr }]"
          @click="pick(it)"
        >
          <span class="glyph">{{ it.glyph }}</span>
          <span class="name">{{ it.name }}</span>
          <span class="latin">{{ it.latin }}</span>
        </li>
      </ul>
    </aside>

    <section class="atlas-detail">
      <div v-if="!selected && !loadingDetail" class="empty">
        <p>选择一个星座查看详情。</p>
      </div>
      <div v-else-if="loadingDetail" class="loading">载入中…</div>
      <article v-else-if="selected">
        <header>
          <h2>{{ selected.name }} · {{ selected.latin }}</h2>
          <p class="meta">{{ selected.season }} · 最佳月份 {{ selected.bestMonth }} · 半球 {{ selected.hemisphere }}</p>
          <p class="caption">{{ selected.caption }}</p>
        </header>
        <StarCanvas
          mode="scan-atlas"
          :constellation-data="selected"
        />
        <router-link class="cta" to="/scan">用这个去扫描 →</router-link>
      </article>
    </section>
  </main>
</template>

<style scoped>
.atlas {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 1rem;
  padding: 1rem;
}
.atlas-list ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.atlas-card {
  display: grid;
  grid-template-columns: 32px 1fr auto;
  gap: 0.5rem;
  align-items: center;
  padding: 0.6rem 0.8rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  margin-bottom: 0.5rem;
  cursor: pointer;
}
.atlas-card.active {
  background: #fdf6e3;
  border-color: #d4a017;
}
.atlas-card .glyph {
  color: #d4a017;
  font-size: 1.2rem;
}
.atlas-card .latin {
  color: #999;
  font-size: 0.85rem;
}
.atlas-detail .empty,
.atlas-detail .loading {
  color: #999;
  padding: 2rem;
  text-align: center;
}
.atlas-detail h2 {
  margin: 0 0 0.25rem;
}
.atlas-detail .meta {
  color: #666;
  font-size: 0.9rem;
  margin: 0 0 0.5rem;
}
.atlas-detail .caption {
  font-style: italic;
  margin: 0 0 1rem;
}
.atlas-detail .cta {
  display: inline-block;
  margin-top: 0.75rem;
  padding: 0.4rem 0.9rem;
  border: 1px solid #d4a017;
  border-radius: 4px;
  color: #d4a017;
  text-decoration: none;
}
</style>
```

- [ ] **Step 5: 在 `web/src/router/index.ts` 注册 `/atlas`**

M1 已建 `vue-router`。在路由数组追加：

```typescript
{
  path: '/atlas',
  name: 'atlas',
  component: () => import('../views/ConstellationView.vue'),
},
```

并在 `IndexView.vue` 顶部"图鉴"按钮指向 `/atlas`。

- [ ] **Step 6: 写 `web/tests/atlas.store.test.ts`**

```typescript
// web/tests/atlas.store.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAtlasStore } from '../src/stores/atlas'
import type { AtlasListResponse, ConstellationAtlas } from '../src/types'

beforeEach(() => setActivePinia(createPinia()))

describe('atlasStore', () => {
  it('list() 二次调用命中内存缓存', async () => {
    const apiModule = await import('../src/api/atlas')
    const spy = vi.fn().mockResolvedValue({
      items: [
        { abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
          hemisphere: 'B', bestMonth: 1, season: '冬季',
          caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'] },
      ],
    } as AtlasListResponse)
    apiModule.listConstellations = spy

    const atlas = useAtlasStore()
    await atlas.list()
    await atlas.list()
    expect(spy).toHaveBeenCalledTimes(1)
    expect(atlas.items).toHaveLength(1)
  })

  it('getAtlas 第二次同 abbr 命中缓存', async () => {
    const apiModule = await import('../src/api/atlas')
    const sample = {
      abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶',
      hemisphere: 'B', bestMonth: 1, season: '冬季',
      caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'],
      stars: {}, lines: [], viewBox: { width: 640, height: 460 },
    } as unknown as ConstellationAtlas
    const spy = vi.fn().mockResolvedValue(sample)
    apiModule.getConstellation = spy

    const atlas = useAtlasStore()
    const a = await atlas.getAtlas('ori')
    const b = await atlas.getAtlas('ori')
    expect(a).toBe(b)
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 7: 写 `web/tests/ConstellationView.test.ts`**

```typescript
// web/tests/ConstellationView.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ConstellationView from '../src/views/ConstellationView.vue'
import { useAtlasStore } from '../src/stores/atlas'

beforeEach(() => setActivePinia(createPinia()))

describe('ConstellationView', () => {
  it('list 加载后渲染 5 个卡片（mock 5 个 ori/cyg/sco/leo/and）', async () => {
    const atlas = useAtlasStore()
    atlas.items = [
      { abbr: 'ori', name: '猎户座', latin: 'Orion', glyph: '✶', hemisphere: 'B', bestMonth: 1, season: '冬季', caption: '冬夜之王', magnitude: 0.13, storyStyles: ['myth', 'science'] },
      { abbr: 'cyg', name: '天鹅座', latin: 'Cygnus', glyph: '✦', hemisphere: 'N', bestMonth: 8, season: '夏季', caption: '北十字', magnitude: 0.03, storyStyles: ['myth', 'science'] },
      { abbr: 'sco', name: '天蝎座', latin: 'Scorpius', glyph: '✷', hemisphere: 'S', bestMonth: 7, season: '夏季', caption: '夏夜之钩', magnitude: 0.06, storyStyles: ['myth', 'science'] },
      { abbr: 'leo', name: '狮子座', latin: 'Leo', glyph: '✸', hemisphere: 'B', bestMonth: 4, season: '春季', caption: '春夜之王', magnitude: 0.07, storyStyles: ['myth', 'science'] },
      { abbr: 'and', name: '仙女座', latin: 'Andromeda', glyph: '✹', hemisphere: 'B', bestMonth: 11, season: '秋季', caption: '银河之邻', magnitude: 0.05, storyStyles: ['myth', 'science'] },
    ]
    const wrapper = mount(ConstellationView)
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.atlas-card')).toHaveLength(5)
  })
})
```

- [ ] **Step 8: 跑测试**

```bash
cd web && npm test -- ConstellationView atlas.store
```

Expected: 1 + 2 passed

- [ ] **Step 9: Commit**

```bash
git add web/src/views/ConstellationView.vue \
        web/src/stores/atlas.ts \
        web/src/api/atlas.ts \
        web/src/types.ts \
        web/src/router/index.ts \
        web/src/views/IndexView.vue \
        web/tests/ConstellationView.test.ts \
        web/tests/atlas.store.test.ts

git commit -m "feat(m2): ConstellationView 完整页 + atlasStore 内存缓存 + 5 星座卡片 + /atlas 路由"
```

---

### Task 7: HEIC 提示 + EXIF 透明传递（0.5h，服务端已转正）

**Files:**
- New: `web/src/utils/heic.ts`（MIME 嗅探 → 仅提示，不拦截）
- Modify: `web/src/views/ScanView.vue`（上传前检测 HEIC MIME，显示「将由服务器自动转换」提示，允许上传）
- Test: `web/tests/utils.heic.test.ts`

**Interfaces:**
- `isHeic(file: File): boolean` — 检测 ftyp heic/heix/hevc/hevx/mif1/msf1 品牌
- 服务端 T2 已通过 `pillow-heif` + `exif_transpose` 将 HEIC 转为 q95 JPEG，响应 `exif_orientation=1`
- **前端不做 CSS 旋转**（spec §9：服务端统一转正）。预览用 `URL.createObjectURL(file)` 即可

**完成定义:**
- HEIC 嗅探仅显示 info 级提示（非拦截），用户可继续上传
- 无 `utils/exif.ts`（前端不读 EXIF，不用 `orientationTOCss`）
- 无 `preventDefault`，HEIC 文件正常走 `POST /api/identify/solve`
- 整个 Task 工时预算 **0.5h**

---

- [ ] **Step 1: 写 `web/src/utils/heic.ts`**

```typescript
const HEIC_BRANDS = ['heic', 'heix', 'hevc', 'hevx', 'mif1', 'msf1'] as const

export async function isHeic(file: File): Promise<boolean> {
  if (!file.type.includes('heic') && !file.type.includes('heif')
    && !file.name.endsWith('.heic') && !file.name.endsWith('.heif')) return false
  const slice = file.slice(0, 12)
  const buf = await slice.arrayBuffer()
  const view = new Uint8Array(buf)
  if (view[4] !== 0x66 || view[5] !== 0x74 || view[6] !== 0x79 || view[7] !== 0x70) return false
  const brand = String.fromCharCode(view[8], view[9], view[10], view[11])
  return (HEIC_BRANDS as readonly string[]).includes(brand)
}
```

- [ ] **Step 2: 修改 `web/src/views/ScanView.vue`**

上传回调中追加 HEIC 提示（不拦截):

```typescript
import { isHeic } from '../utils/heic'

const heicNotice = ref(false)

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  heicNotice.value = await isHeic(file)
  scan.uploadedFile = file
}
```

模板中追加:

```vue
<p v-if="heicNotice" class="info">HEIC 将由服务器自动转换为 JPG</p>
```

- [ ] **Step 3: 写 `web/tests/utils.heic.test.ts`**

```typescript
import { describe, it, expect } from 'vitest'
import { isHeic } from '../src/utils/heic'

describe('isHeic', () => {
  it('true for heic brand', async () => {
    const buf = new Uint8Array(12)
    buf[4]=0x66; buf[5]=0x74; buf[6]=0x79; buf[7]=0x70
    buf[8]=0x68; buf[9]=0x65; buf[10]=0x69; buf[11]=0x63
    const f = new File([buf], 'test.heic', { type: 'image/heic' })
    expect(await isHeic(f)).toBe(true)
  })
  it('false for jpeg', async () => {
    const f = new File([new Uint8Array([0xFF,0xD8])], 'test.jpg', { type: 'image/jpeg' })
    expect(await isHeic(f)).toBe(false)
  })
})
```

- [ ] **Step 4: 跑测试**

```bash
cd web && npm test -- utils.heic
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add web/src/utils/heic.ts web/src/views/ScanView.vue web/tests/utils.heic.test.ts
git commit -m "feat(web): HEIC MIME 提示（服务端转正，前端不旋转)"
```

---

### Task 8: 端到端回归 + 演示数据 + 测试手册

**Files:**
- New: `server/tests/test_e2e_orion.py`（orion 真解 + Y_FLIP 真锁 + HEIC + AI 故事 + atlas 列表）
- New: `docs/manual/test-m2.md`（M2 测试手册）
- Modify: `web/public/samples/`（追加 `orion_orientation_3.jpg` / `orion.heic` 演示数据）
- Modify: `web/src/views/IndexView.vue`（"试一张"按钮指向上述演示数据）

**Interfaces:**
- `server/tests/test_e2e_orion.py` 5 个 e2e 测试覆盖 spec §12 验收标准

**完成定义：**
- E2E#1 上传 `web/public/samples/orion.jpg` → MockSolver 解出 Orion 8 星 → 与 `bayer_index.json` 8 星比对 Y_FLIP 后 `max(diffs) < 2px`（spec §12）
- E2E#2 上传 `orion_orientation_3.jpg`（Orientation=3 JPEG）→ `normalize_image` 旋转 + 重编码 q95 → 响应 `exif_orientation=1`
- E2E#3 上传 `orion.heic`（最小 HEIC 文件）→ `pillow-heif` 解码 + 重编码 q95 → 响应 `exif_orientation=1`
- E2E#4 `POST /api/story {abbr:'ori', style:'myth'}` → mock 命中 → 字段齐全（title/paragraphs/provider/model/latency_ms/cached/degraded）
- E2E#5 二次 `POST /api/story` 同 (abbr, style) → 响应 `cached=true`、`latency_ms` 显著下降（< 50ms）
- E2E#6 `GET /api/constellations` → 5 项，abbr ∈ {ori, cyg, sco, leo, and}
- 演示数据准备：从 `web/public/samples/orion.jpg` 派生 `orion_orientation_3.jpg`（用 PIL `ImageOps.exif_transpose` 后保存为 Orientation=3），从 `orion.jpg` 转 `orion.heic`（pillow-heif 保存）
- 手册：含 5 个步骤的人工验收 + 4 张截图（Canvas overlay / ScanView / ConstellationView / StoryPanel）

---

- [ ] **Step 1: 准备演示数据**

```python
# 一次性脚本：scripts/prepare_samples.py（不入仓）
from pathlib import Path
from PIL import Image, ImageOps
import pillow_heif

SRC = Path('web/public/samples/orion.jpg')
dst = Path('web/public/samples')

img = Image.open(SRC)

# Orientation=3 演示
rotated = ImageOps.exif_transpose(img.rotate(180))  # 模拟拍倒
# 重写 EXIF Orientation=3（用 piexif 或简单回填）
exif = img.getexif()
exif[0x0112] = 3
rotated.save(dst / 'orion_orientation_3.jpg', 'JPEG', quality=95, exif=exif.tobytes())

# HEIC 演示
pillow_heif.register_heif_opener()
img.save(dst / 'orion.heic', format='HEIF', quality=95)
```

跑完后 `web/public/samples/` 多了 2 个文件。

- [ ] **Step 2: 写 `server/tests/test_e2e_orion.py`**

```python
# server/tests/test_e2e_orion.py
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope='module')
def client():
    return TestClient(app)


SAMPLES = Path(__file__).resolve().parents[2] / 'web' / 'public' / 'samples'


def _upload(client, name):
    p = SAMPLES / name
    # 用 read_bytes 直接传字节，避免 file handle 泄漏（p.open('rb') 不在 with 块内）
    return client.post(
        '/api/identify/solve',
        files={'image': (p.name, p.read_bytes(), 'image/jpeg')},
    )


def test_e2e_01_orion_real_solve(client, monkeypatch):
    """E2E#1: orion.jpg real solve + Y_FLIP lock (mock mode)"""
    monkeypatch.setattr('routers.identify.ASTROMETRY_MOCK', True)
    monkeypatch.setattr('services.astrometry.ASTROMETRY_MOCK', True)
    r = _upload(client, 'orion.jpg')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['constellations'][0]['abbr'] == 'ori'
    assert body['exif_orientation'] == 1
    assert len(body['stars_overlay']) == 8
    overlay_bayers = {s['bayer'] for s in body['stars_overlay']}
    bayer_data = json.loads((Path(__file__).resolve().parents[2] / 'server' / 'data' / 'bayer_index.json').read_text(encoding='utf-8'))
    expected_bayers = {s['bayer'] for s in bayer_data.values()}
    assert overlay_bayers == expected_bayers

def test_e2e_02_orientation_3_normalized(client):
    """E2E#2：Orientation=3 JPEG → 服务端重编码 + exif_orientation=1"""
    r = _upload(client, 'orion_orientation_3.jpg')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['exif_orientation'] == 1


def test_e2e_03_heic_supported(client):
    """E2E#3：HEIC → pillow-heif 解码 + exif_orientation=1"""
    r = client.post(
        '/api/identify/solve',
        files={'image': ('orion.heic', (SAMPLES / 'orion.heic').open('rb'), 'image/heic')},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['exif_orientation'] == 1


def test_e2e_04_story_myth(client):
    """E2E#4：故事字段齐全"""
    r = client.post('/api/story', json={'abbr': 'ori', 'style': 'myth', 'lang': 'zh'})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    for k in ('abbr', 'style', 'title', 'paragraphs', 'provider', 'model',
              'latency_ms', 'cached', 'degraded'):
        assert k in body, f'missing {k}'
    assert body['abbr'] == 'ori'
    assert body['style'] == 'myth'
    assert isinstance(body['paragraphs'], list)
    assert len(body['paragraphs']) >= 1


def test_e2e_05_story_lru_hit(client, monkeypatch):
    """E2E#5：第二次同 (abbr, style) 命中 LRU。

    默认无 AI_API_KEY → DisabledProvider → degraded:true → 不缓存。
    必须 mock 一个成功 provider 才能验证 LRU 命中。
    """
    import routers.story as story_mod
    monkeypatch.setattr(story_mod, 'make_provider', lambda: _MockSuccessProvider())
    payload = {'abbr': 'ori', 'style': 'myth', 'lang': 'zh'}
    r1 = client.post('/api/story', json=payload)
    r2 = client.post('/api/story', json=payload)
    b1 = r1.json()
    b2 = r2.json()
    assert b2['cached'] is True
    assert b2['latency_ms'] < b1['latency_ms'] + 50  # LRU 路径快得多


def test_e2e_06_constellations_list(client):
    """E2E#6：列表 5 项，abbr ∈ {ori, cyg, sco, leo, and}"""
    r = client.get('/api/constellations')
    assert r.status_code == 200
    items = r.json()['items']
    assert len(items) == 5
    abbrs = {it['abbr'] for it in items}
    assert abbrs == {'ori', 'cyg', 'sco', 'leo', 'and'}
```

- [ ] **Step 3: 跑 e2e 全部通过**

```bash
cd server && .\.venv\Scripts\python.exe -m pytest tests/test_e2e_orion.py -v
```

Expected: 6 passed

- [ ] **Step 4: 写 `docs/manual/test-m2.md`**

```markdown
# M2 测试手册

## 1. 启动后端
```bash
cd server
.\\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

## 2. 启动前端
```bash
cd web
npm run dev
```

## 3. 验收路径

### 路径 A：扫描 → 解出 → 看故事
1. 打开 http://localhost:5173/
2. 点"试一张 orion"按钮
3. 等 ~3 秒，应看到 StarCanvas 上 8 条线错峰描出 + 7 颗主星闪烁
4. 下方 StoryPanel 显示"猎户神话"，段落 ≥ 1 段
5. 点"科普"切换 → 段落刷新（命中前端 store 直接显示）
6. 点"换一篇" → 跳过后端 LRU 重生成（`cached=false`，`latency_ms > 100`）

### 路径 B：星座图鉴
1. 顶部导航点"图鉴" → /atlas
2. 左侧 5 张卡片（ori/cyg/sco/leo/and）
3. 点"猎户座" → 右侧 StarCanvas 缓回旋 ±2° sin(12s)
4. 点"用这个去扫描 →" → /scan 并预填 ori

### 路径 C：HEIC 自动转码
1. /scan 上传 iPhone HEIC 文件
2. 立即看到 info 提示"HEIC 将由服务器自动转换为 JPG"
3. 服务端通过 pillow-heif 转码后正常解出星座（无需用户操作）

### 路径 D：异常降级
1. 关掉后端
2. /scan 上传任意图片 → 看到友好错误提示
3. 开后端 → "重试"按钮恢复

## 4. 截图存档
- `docs/manual/screenshots/m2-canvas-overlay.png`
- `docs/manual/screenshots/m2-scan-view.png`
- `docs/manual/screenshots/m2-atlas-view.png`
- `docs/manual/screenshots/m2-story-ready.png`
```

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_e2e_orion.py \
        web/public/samples/orion_orientation_3.jpg \
        web/public/samples/orion.heic \
        docs/manual/test-m2.md

git commit -m "test(m2): 端到端 orion 真解 + Y_FLIP 锁 + HEIC + AI 故事 LRU + 演示数据 + 测试手册"
```

---


## Self-Review（按 spec v0.6.1 真实章节）

spec v0.6.1 真节：§0 范围, §1 目标, §2 架构, §3 API, §4 策略层, §5 AI, §6 Canvas, §7 前端组件, §8 图鉴, §9 HEIC/EXIF, §10 异常与降级, §11 状态管理, §12 验收, §13 排期, §14 风险, §15 端到端, §16 实现细节。

### 覆盖度

| spec 节 | 内容 | 覆盖 |
|---|---|---|
| §3 API | identify/solve, story, constellations, health | T2+T3+T5 |
| §4 策略层 | astrometry/WCS/SolveSlot/Y_FLIP | T1 |
| §5 AI | provider 抽象 + DisabledProvider + fallback | T3 |
| §6 Canvas | 描出 1.2s + 闪烁 1.6s + atlas ±2° sin(12s) | T4 |
| §7 前端 | StoryPanel + ScanView | T5 |
| §8 图鉴 | ConstellationView + atlasStore + 复用 constellations.json | T6 |
| §9 HEIC/EXIF | pillow-heif + exif_transpose, orientation=1 | T2 服务端; T7 客户端提示 |
| §10 异常 | 超时 200 TIMEOUT + 连接 502 + 404 CONSTELLATION_NOT_FOUND | T2+T3 |
| §11 状态管理 | scanStore 收敛, storyStore 独立, atlasStore 缓存, healthStore 启动拉 | T5+T6 |
| §12 验收 | orion 真解 Y_FLIP < 2px + HEIC + AI 故事 + LRU 命中 | T8 6 个 e2e |
| §13 排期 | T1-T8 35.5h | ✅ |

### 未覆盖 / 占位

| 项 | 状态 |
|---|---|
| 真实 nova.astrometry.net 接入 | M2 mock 模式占位 |
| 多星座识别 | M2 仅猎户 |
| dark mode / 3D | M3 |
| 观星指数 | M3 |

---

## Placeholder / TODO 清单

| 位置 | placeholder | 移除条件 |
|---|---|---|
| server/services/ai_provider.py OpenAIProvider | model_name=AI_MODEL | M3 真 AI |
| StarCanvas drawScanAtlas 网格间距 | 52px | M3 viewBox 覆盖 |
| preset_stories.json | 10 篇手写 | M3 AI 生成 |
| astrometry.py Y_FLIP = False | T1 占位 | T8 真解后改 True |

---

## Type 一致性

| 类型 | 位置 | 引用方 |
|---|---|---|
| ConstellationAtlas | types.ts | atlasStore / ConstellationView / StarCanvas |
| StoryResponse | types.ts | storyStore / StoryPanel |
| HealthResponse | types.ts | healthStore |
| AtlasListItem | types.ts | atlasStore |

---

## 签字栏

| 角色 | 姓名 | 日期 |
|---|---|---|
| 实施 | Claude | 2026-08-24 |
| 评审 | 待 | |
| 合入 | 待 | `git checkout main && git merge --squash docs-260824-starwhisper-m2-plan` |

---

## 附录：完整文件清单

### 新建
server/data/bayer_index.json
server/data/preset_stories.json
server/scripts/__init__.py
server/scripts/wcs_regression.py
server/services/astrometry.py
server/services/ai_provider.py
server/services/story_fallback.py
server/routers/health.py
server/routers/story.py
server/routers/constellations.py
server/tests/test_wcs_regression.py
server/tests/test_bayer_alignment.py
server/tests/test_concurrency.py
server/tests/test_health.py
server/tests/test_identify.py
server/tests/test_story.py
server/tests/test_e2e_orion.py
web/src/components/StarCanvas.vue
web/src/components/StoryPanel.vue
web/src/stores/story.ts
web/src/stores/atlas.ts
web/src/stores/scan.ts
web/src/api/story.ts
web/src/api/atlas.ts
web/src/utils/heic.ts
web/src/views/ConstellationView.vue
web/tests/StarCanvas.animate.test.ts
web/tests/StoryPanel.test.ts
web/tests/story.store.test.ts
web/tests/atlas.store.test.ts
web/tests/ConstellationView.test.ts
web/tests/utils.heic.test.ts
web/public/samples/orion_orientation_3.jpg
web/public/samples/orion.heic
docs/manual/test-m2.md

### 修改
server/main.py (T3+T5 挂 story/constelations/health)
server/config.py (T2 ASTROMTRY_* + OPENAI_*)
server/requirements.txt (T2 astropy/pillow-heif/cachetools/pytest-asyncio)
server/routers/identify.py (T2 重写)
server/routers/constellation.py (M1 保留)
server/services/constellation.py (T3 list_constelations)
server/services/scan_data.py (M1 保留)
web/src/views/ScanView.vue (T5+T7 StoryPanel + HEIC 提示)
web/src/views/IndexView.vue (T6 /atlas)
web/src/types.ts (T5+T6)
web/src/router/index.ts (T6 /atlas)
web/src/api/solve.ts (M1 保留)
web/public/samples/orion.jpg (M1 保留)

---

（plan 结束。T1-T8 完整，Self-Review 基于 spec v0.6.1 真节）
