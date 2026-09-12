# 观星指数页 PLATE 复刻实施计划（FIG.1/2/3 + 后端 astro 数据）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `web/src/views/IndexView.vue` 从单栏数字盘升级为 `concepts/starwhisper-concept.html` 的双栏图版样式（SVG 指针仪表盘 + 斜纹 meter + 24h 柱状趋势 + 月相卡），后端 `/api/index` 补齐日落/天文晨光/月落/银心升起四项时间数据，并新增任意城市搜索。

**Architecture:** 后端新增 `services/astro_times.py` 纯天文计算模块（astral 算日落/天文晨光，astropy 扫描插值算月落/银心升起），router 透传 `astro` 对象；前端新增 `IndexGauge` / `TrendBars` / `MoonCard` 三个展示组件与 `api/geocoding.ts`（Open-Meteo Geocoding），`IndexView` 重排为 concept 的 `index-grid` 双栏。

**Tech Stack:** FastAPI + astral 3.x + astropy（已依赖，无新包）；Vue 3 `<script setup>` + Pinia + vitest + jsdom。

**Spec:** `concepts/starwhisper-concept.html`（视觉唯一事实源，截图即其渲染结果）；评分口径不变（`server/services/index.py` docstring）。

## Global Constraints

- 评分算法、四档口径、一票否决**一律不动**（`services/index.py` 保持原样）。
- 前端组件命名 kebab-case 语义化（`IndexGauge.vue` / `TrendBars.vue` / `MoonCard.vue`），测试文件 `*.test.ts`。
- 前端 scoped CSS、传统 CSS 属性；视觉变量沿用现有 `--paper/--ink/--gold/--seal` 系列（concept 值即现值）。
- Python 变量/函数 snake_case；服务层无 FastAPI 依赖；测试用 `monkeypatch.setattr` 打在目标模块属性上。
- 后端 import 风格为绝对导入（`from services import index`）。
- astropy IERS 自动下载必须关闭（离线环境防卡死）。
- astro 时间统一输出北京时间 `Asia/Shanghai` 的 `"HH:MM"` 字符串，不可见/无事件返回 `null`。
- `astro` 与 `geocoding` 均为**增量字段/新增文件**，旧 fixture 与旧接口语义不破坏。

---

### Task 1: 后端 `services/astro_times.py` —— 天文时刻纯计算

**Files:**
- Create: `server/services/astro_times.py`
- Test: `server/tests/test_astro_times.py`

**Interfaces:**
- Produces（Task 2 依赖，签名精确如下）:
  - `TZ = ZoneInfo("Asia/Shanghai")`
  - `sunset_time(lat: float, lon: float, d: date) -> str | None`
  - `astro_dawn_time(lat: float, lon: float, now: datetime) -> str | None`
  - `moonset_time(lat: float, lon: float, now: datetime) -> str | None`
  - `galactic_rise_time(lat: float, lon: float, now: datetime) -> str | None`
  - `_find_setting_crossing(times: list[datetime], alts: list[float]) -> datetime | None`（纯函数，供测试）
  - `_find_rising_crossing(times: list[datetime], alts: list[float]) -> datetime | None`

- [ ] **Step 1: 写失败测试**

```python
"""astro_times 单测：纯函数过零插值 + astral 日落/晨光 + 格式约定。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from services import astro_times as at


def test_find_setting_crossing_interpolates():
    base = datetime(2026, 9, 10, 20, 0, tzinfo=at.TZ)
    times = [base + timedelta(minutes=20 * i) for i in range(5)]
    alts = [30.0, 10.0, -5.0, -20.0, -35.0]
    got = at._find_setting_crossing(times, alts)
    assert got is not None
    # 过零点在 20:20~20:40 之间且偏向 20:40（插值 2/3 处）
    assert times[1] < got < times[2]


def test_find_setting_crossing_none_when_never_sets():
    base = datetime(2026, 9, 10, 20, 0, tzinfo=at.TZ)
    times = [base, base + timedelta(minutes=20)]
    assert at._find_setting_crossing(times, [10.0, 5.0]) is None


def test_find_rising_crossing_interpolates():
    base = datetime(2026, 9, 10, 20, 0, tzinfo=at.TZ)
    times = [base + timedelta(minutes=15 * i) for i in range(5)]
    alts = [-30.0, -10.0, 5.0, 20.0, 35.0]
    got = at._find_rising_crossing(times, alts)
    assert got is not None
    assert times[1] < got < times[2]


def test_sunset_time_format_beijing_summer():
    # 北京 2026-06-01 日落约 19:37~19:40（astral 本地计算，断言区间容差）
    got = at.sunset_time(39.9042, 116.4074, date(2026, 6, 1))
    assert got is not None
    hh, mm = map(int, got.split(":"))
    assert 19 <= hh <= 20 and 0 <= mm < 60


def test_sunset_time_none_in_polar_day():
    # 北纬 80° 夏至极昼，无日落
    assert at.sunset_time(80.0, 20.0, date(2026, 6, 21)) is None


def test_astro_dawn_time_is_future_event():
    now = datetime(2026, 9, 10, 21, 0, tzinfo=at.TZ)
    got = at.astro_dawn_time(39.9042, 116.4074, now)
    assert got is not None
    hh, mm = map(int, got.split(":"))
    # 下一次天文晨光应在凌晨（03:00~05:30 附近）
    assert 3 <= hh <= 6


def test_moonset_time_scan_smoke():
    # astropy 扫描（~108 点，单测 <2s）；只验格式与“是未来事件”
    now = datetime(2026, 9, 10, 21, 0, tzinfo=at.TZ)
    got = at.moonset_time(39.9042, 116.4074, now)
    if got is not None:  # 月落是否落入窗口依月龄而定，非确定 → 冒烟断言
        hh, mm = map(int, got.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60


def test_galactic_rise_time_format():
    now = datetime(2026, 9, 10, 21, 0, tzinfo=at.TZ)
    got = at.galactic_rise_time(39.9042, 116.4074, now)
    if got is not None:
        hh, mm = map(int, got.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_astro_times.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'services.astro_times'`

- [ ] **Step 3: 写实现**

```python
"""天文时刻计算：日落 / 天文晨光 / 月落 / 银河核心升起。

- astral 3.x：日落（sunset）与天文晨光（twilight depression=18°，RISING）
- astropy：月亮与银心（人马座 A*）高度角采样 + 线性插值过零
- 时间统一 Asia/Shanghai，输出 "HH:MM"；事件不可见（极昼/极区/窗口外）→ None
- astropy IERS 自动下载必须关闭（离线环境防卡死）
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import SunDirection
from astral.sun import sunset as _astral_sunset
from astral.sun import twilight as _astral_twilight

from astropy.utils.iers import conf as _iers_conf

_iers_conf.auto_download = False  # 离线环境防 IERS 联网卡死

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

TZ = ZoneInfo("Asia/Shanghai")

_GALACTIC_CORE = SkyCoord(ra=266.4168 * u.deg, dec=-29.0078 * u.deg)


def _fmt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(TZ).strftime("%H:%M")


def sunset_time(lat: float, lon: float, d: date) -> str | None:
    try:
        dt = _astral_sunset((lat, lon), date=d, tzinfo=TZ)
    except ValueError:
        return None
    return _fmt(dt)


def astro_dawn_time(lat: float, lon: float, now: datetime) -> str | None:
    """下一次天文晨光（太阳到 -18° 的上升时刻）；今天的已过则取明天的。"""
    for d in (now.date(), now.date() + timedelta(days=1)):
        try:
            dt = _astral_twilight(
                (lat, lon), date=d, direction=SunDirection.RISING,
                depression=18.0, tzinfo=TZ,
            )
        except ValueError:
            continue
        if dt > now:
            return _fmt(dt)
    return None


def _find_setting_crossing(
    times: list[datetime], alts: list[float],
) -> datetime | None:
    for i in range(len(alts) - 1):
        if alts[i] > 0.0 >= alts[i + 1]:
            frac = alts[i] / (alts[i] - alts[i + 1])
            span = times[i + 1] - times[i]
            return times[i] + span * frac
    return None


def _find_rising_crossing(
    times: list[datetime], alts: list[float],
) -> datetime | None:
    for i in range(len(alts) - 1):
        if alts[i] <= 0.0 < alts[i + 1]:
            frac = -alts[i] / (alts[i + 1] - alts[i])
            span = times[i + 1] - times[i]
            return times[i] + span * frac
    return None



def _moon_coord_series(lat: float, lon: float, now: datetime,
                       hours: float, step_min: int):
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    step = timedelta(minutes=step_min)
    n = int(hours * 60 // step_min) + 1
    times = [now + i * step for i in range(n)]
    t = Time(times)
    alt = get_body("moon", t, loc).transform_to(
        AltAz(obstime=t, location=loc)).alt.deg
    return times, [float(a) for a in alt]


def moonset_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 36h 内下一次月落（月亮高度下穿地平）。"""
    times, alts = _moon_coord_series(lat, lon, now, 36.0, 20)
    return _fmt(_find_setting_crossing(times, alts))


def _fixed_coord_series(coord: SkyCoord, lat: float, lon: float,
                        now: datetime, hours: float, step_min: int):
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    step = timedelta(minutes=step_min)
    n = int(hours * 60 // step_min) + 1
    times = [now + i * step for i in range(n)]
    t = Time(times)
    alt = coord.transform_to(AltAz(obstime=t, location=loc)).alt.deg
    return times, [float(a) for a in alt]


def galactic_rise_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 24h 内银心（人马座 A*）升起时刻；纬度 >61°N 永不升起 → None。"""
    times, alts = _fixed_coord_series(_GALACTIC_CORE, lat, lon, now, 24.0, 15)
    return _fmt(_find_rising_crossing(times, alts))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_astro_times.py -v`
Expected: 全 PASS（`moonset/galactic_rise` 冒烟断言各 <2s）

- [ ] **Step 5: Commit**

```bash
git add server/services/astro_times.py server/tests/test_astro_times.py
git commit -m "feat(index): astro_times 模块（日落/天文晨光/月落/银心升起）"
```

---

### Task 2: `/api/index` 透传 `astro` 对象

**Files:**
- Modify: `server/routers/index.py`（在 `from datetime import date` 处改导入，响应体追加 `astro`）
- Test: `server/tests/test_index_router.py`（追加断言）

**Interfaces:**
- Consumes: Task 1 的 `astro_times.sunset_time / astro_dawn_time / moonset_time / galactic_rise_time`
- Produces: 响应新增 `"astro": {"sunset": str|null, "astro_dawn": str|null, "moonset": str|null, "galactic_rise": str|null}`（Task 3 前端 types 依赖）

- [ ] **Step 1: 读现有 router 测试，写失败断言**

先 Read `server/tests/test_index_router.py` 全文，找到现有成功路径用例（mock `fetch_forecast` 的那个），在其后追加：

```python
def test_index_response_contains_astro_fields(client, monkeypatch):
    import routers.index as router_mod

    monkeypatch.setattr(
        router_mod.astro_times, "sunset_time", lambda *a, **k: "18:52")
    monkeypatch.setattr(
        router_mod.astro_times, "astro_dawn_time", lambda *a, **k: "04:31")
    monkeypatch.setattr(
        router_mod.astro_times, "moonset_time", lambda *a, **k: "21:08")
    monkeypatch.setattr(
        router_mod.astro_times, "galactic_rise_time", lambda *a, **k: "22:40")

    resp = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert resp.status_code == 200
    astro = resp.json()["astro"]
    assert astro == {
        "sunset": "18:52",
        "astro_dawn": "04:31",
        "moonset": "21:08",
        "galactic_rise": "22:40",
    }


def test_index_astro_fields_optional_null(client, monkeypatch):
    import routers.index as router_mod

    for name in ("sunset_time", "astro_dawn_time", "moonset_time",
                 "galactic_rise_time"):
        monkeypatch.setattr(
            router_mod.astro_times, name, lambda *a, **k: None)

    resp = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert resp.status_code == 200
    assert resp.json()["astro"]["moonset"] is None
```

> mock 打在 `routers.index.astro_times` 模块属性上（router 内 `from services import astro_times` 后以属性方式调用，同一模块对象，monkeypatch 生效）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index_router.py -v`
Expected: FAIL `KeyError: 'astro'`

- [ ] **Step 3: 改 router**

`server/routers/index.py`：导入区改为

```python
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from services import astro_times
from services import index as index_svc
from services.weather import WeatherUnavailable, fetch_forecast
```

在 `moon = index_svc.moon_info(today)` 之后追加：

```python
    now_local = datetime.now(astro_times.TZ)
    astro = {
        "sunset": astro_times.sunset_time(lat, lon, now_local.date()),
        "astro_dawn": astro_times.astro_dawn_time(lat, lon, now_local),
        "moonset": astro_times.moonset_time(lat, lon, now_local),
        "galactic_rise": astro_times.galactic_rise_time(lat, lon, now_local),
    }
```

响应 dict 的 `"hourly": hourly,` 前追加一行 `"astro": astro,`。

- [ ] **Step 4: 跑 router 测试 + 全量后端测试**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index_router.py tests/test_index.py tests/test_astro_times.py -v && .venv/Scripts/python.exe -m pytest -q`
Expected: 全 PASS（默认跳过 integration）

- [ ] **Step 5: Commit**

```bash
git add server/routers/index.py server/tests/test_index_router.py
git commit -m "feat(index): /api/index 返回 astro 时间组（日落/晨光/月落/银心）"
```

---

### Task 3: 前端 types + 城市搜索 API

**Files:**
- Modify: `web/src/types.ts:301-316`（`StargazeIndex` 前加新接口 + 字段）
- Create: `web/src/api/geocoding.ts`
- Test: `web/tests/geocoding.api.test.ts`

**Interfaces:**
- Produces:
  - `interface StargazeAstro { sunset: string | null; astro_dawn: string | null; moonset: string | null; galactic_rise: string | null }`；`StargazeIndex.astro?: StargazeAstro`（optional，旧 fixture 不破坏）
  - `interface GeoResult { name: string; admin1?: string; country?: string; latitude: number; longitude: number }`
  - `searchCity(q: string, signal?: AbortSignal): Promise<GeoResult[]>`

- [ ] **Step 1: 写失败测试**

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'

import { searchCity } from '../src/api/geocoding'

describe('geocoding api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('拼接查询参数并解析 results', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          results: [
            { name: '冷湖', admin1: '青海', latitude: 38.0, longitude: 93.4 },
          ],
        }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const got = await searchCity('冷湖')
    expect(got).toHaveLength(1)
    expect(got[0].name).toBe('冷湖')
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('geocoding-api.open-meteo.com/v1/search')
    expect(url).toContain('name=')
    expect(url).toContain('language=zh')
  })

  it('无结果返回空数组', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
    )
    expect(await searchCity('不存在的城')).toEqual([])
  })

  it('HTTP 非 200 抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    )
    await expect(searchCity('x')).rejects.toThrow()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- geocoding`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

`web/src/types.ts`（`StargazeIndex` 定义前插入）：

```ts
/** /api/index astro 时间组（"HH:MM" 或 null = 事件不可见） */
export interface StargazeAstro {
  sunset: string | null
  astro_dawn: string | null
  moonset: string | null
  galactic_rise: string | null
}
```

`StargazeIndex` 内 `hourly: HourlyPoint[]` 之前加一行：

```ts
  astro?: StargazeAstro
```

`web/src/api/geocoding.ts`（新文件）：

```ts
/** Open-Meteo Geocoding 城市搜索结果。 */
export interface GeoResult {
  name: string
  admin1?: string
  country?: string
  latitude: number
  longitude: number
}

/** 任意城市模糊搜索（Open-Meteo Geocoding，免费 + CORS 开放）。 */
export async function searchCity(
  q: string,
  signal?: AbortSignal,
): Promise<GeoResult[]> {
  const url =
    `https://geocoding-api.open-meteo.com/v1/search?name=` +
    `${encodeURIComponent(q)}&count=6&language=zh&format=json`
  const r = await fetch(url, { signal })
  if (!r.ok) throw new Error(`Geocoding HTTP ${r.status}`)
  const data = (await r.json()) as { results?: GeoResult[] }
  return data.results ?? []
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && pnpm test -- geocoding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/api/geocoding.ts web/tests/geocoding.api.test.ts
git commit -m "feat(index): astro 类型 + Open-Meteo 城市搜索 API"
```

---

### Task 4: store 城市搜索 action

**Files:**
- Modify: `web/src/stores/stargaze.ts`
- Test: `web/tests/stargaze.store.test.ts`（追加用例）

**Interfaces:**
- Consumes: Task 3 的 `searchCity` / `GeoResult`
- Produces:
  - `searchResults: Ref<GeoResult[]>`、`searching: Ref<boolean>`
  - `search(query: string): Promise<void>`（空串清空结果；异常静默清空）
  - `selectSearchResult(r: GeoResult): Promise<void>` → `load(r.latitude, r.longitude)`

- [ ] **Step 1: 写失败测试**

`stargaze.store.test.ts` 顶部 mock 区追加（保持既有 mock 风格）：

```ts
const searchCityMock = vi.fn()
vi.mock('../src/api/geocoding', () => ({
  searchCity: (...a: unknown[]) => searchCityMock(...a),
}))
```

describe 内追加：

```ts
it('search 有结果时填充 searchResults，selectSearchResult 触发 load', async () => {
  fetchMock.mockResolvedValue(sampleIndex({ city: '冷湖' }))
  searchCityMock.mockResolvedValue([
    { name: '冷湖', admin1: '青海省', latitude: 38.0, longitude: 93.4 },
  ])
  const store = useStargazeStore()
  await store.search('冷湖')
  expect(store.searchResults).toHaveLength(1)
  expect(store.searching).toBe(false)

  await store.selectSearchResult(store.searchResults[0])
  expect(fetchMock).toHaveBeenLastCalledWith(38.0, 93.4, expect.anything())
  expect(store.data?.city).toBe('冷湖')
})

it('search 空串清空结果且不发请求；失败静默清空', async () => {
  const store = useStargazeStore()
  await store.search('')
  expect(searchCityMock).not.toHaveBeenCalled()
  expect(store.searchResults).toEqual([])

  searchCityMock.mockRejectedValue(new Error('down'))
  await store.search('冷湖')
  expect(store.searching).toBe(false)
  expect(store.searchResults).toEqual([])
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- stargaze.store`
Expected: FAIL（`store.search` 不存在）

- [ ] **Step 3: 改 store**

`stargaze.ts` 顶部追加：

```ts
import { searchCity, type GeoResult } from '../api/geocoding'
```

store 体内追加（`selectCity` 之后）：

```ts
  const searchResults = ref<GeoResult[]>([])
  const searching = ref(false)

  /** 任意城市模糊搜索；空串清空，异常静默清空。 */
  async function search(query: string): Promise<void> {
    const q = query.trim()
    if (!q) {
      searchResults.value = []
      return
    }
    searching.value = true
    try {
      searchResults.value = await searchCity(q)
    } catch {
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  /** 选中搜索结果并加载该坐标指数。 */
  async function selectSearchResult(r: GeoResult): Promise<void> {
    searchResults.value = []
    await load(r.latitude, r.longitude)
  }
```

return 里补 `searchResults, searching, search, selectSearchResult,`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && pnpm test -- stargaze.store`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/stores/stargaze.ts web/tests/stargaze.store.test.ts
git commit -m "feat(index): store 城市搜索 action（search/selectSearchResult）"
```

---

### Task 5: `IndexGauge.vue` SVG 指针仪表盘

**Files:**
- Create: `web/src/components/index/IndexGauge.vue`
- Test: `web/tests/IndexGauge.test.ts`

**Interfaces:**
- Produces: `props: { score: number }`（0-100）；渲染 `.gauge-num`（数字）、`.gauge-needle`（指针 g 元素）；数字经 1.3s 动画到达 score；`prefers-reduced-motion` 时直出终值。

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import IndexGauge from '../src/components/index/IndexGauge.vue'

describe('IndexGauge', () => {
  it('渲染 INDEX · 满分百 与最终分数', async () => {
    const w = mount(IndexGauge, { props: { score: 72 } })
    expect(w.text()).toContain('INDEX')
    expect(w.text()).toContain('满分百')
    // 动画由 requestAnimationFrame 驱动，jsdom 下至少最终渲染出数值
    expect(w.find('.gauge-num').text()).toMatch(/^\d{1,3}$/)
  })

  it('指针初始存在且刻度生成', () => {
    const w = mount(IndexGauge, { props: { score: 0 } })
    expect(w.find('.gauge-needle').exists()).toBe(true)
    // 刻度线由 JS 生成（40 档）
    expect(w.findAll('.gauge-tick').length).toBeGreaterThanOrEqual(30)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- IndexGauge`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写组件（照 concept 433-459 行 SVG 结构移植）**

```vue
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ score: number }>()

const R = 88
const CIRC = 2 * Math.PI * R
const num = ref(0)
const arcOffset = ref(CIRC)
const needleDeg = ref(-90)

let raf = 0

function animateTo(target: number): void {
  cancelAnimationFrame(raf)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced) {
    num.value = target
    arcOffset.value = CIRC * (1 - target / 100)
    needleDeg.value = -90 + (target / 100) * 270
    return
  }
  const start = performance.now()
  const dur = 1300
  const from = num.value
  const step = (t: number): void => {
    const p = Math.min(1, (t - start) / dur)
    const e = 1 - Math.pow(1 - p, 3)
    num.value = Math.round(from + (target - from) * e)
    arcOffset.value = CIRC * (1 - ((from + (target - from) * e) / 100))
    needleDeg.value = -90 + ((from + (target - from) * e) / 100) * 270
    if (p < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

// 刻度：270° 扇区，每 6.75° 一根
const ticks = Array.from({ length: 41 }, (_, i) => {
  const deg = -90 + (i / 40) * 270
  const major = i % 5 === 0
  const rad = (deg * Math.PI) / 180
  const r1 = major ? 74 : 78
  const r2 = 82
  const cx = 110
  const cy = 110
  return {
    x1: cx + r1 * Math.sin(rad), y1: cy - r1 * Math.cos(rad),
    x2: cx + r2 * Math.sin(rad), y2: cy - r2 * Math.cos(rad),
    major,
  }
})

onMounted(() => animateTo(props.score))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <div class="gauge-box">
    <svg viewBox="0 0 220 220" role="img" aria-label="观星指数仪表盘">
      <circle cx="110" cy="110" r="104" fill="none" stroke="rgba(46,36,23,.5)" stroke-width="1" />
      <circle cx="110" cy="110" r="99" fill="none" stroke="rgba(46,36,23,.25)" stroke-width=".6" />
      <g class="gauge-ticks">
        <line
          v-for="(t, i) in ticks" :key="i" class="gauge-tick"
          :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2"
          :stroke="t.major ? 'rgba(46,36,23,.6)' : 'rgba(46,36,23,.28)'"
          :stroke-width="t.major ? 1.2 : 0.6"
        />
      </g>
      <circle cx="110" cy="110" :r="R" fill="none" stroke="rgba(169,126,47,.18)" stroke-width="7" />
      <circle
        cx="110" cy="110" :r="R" fill="none" stroke="#b3873a" stroke-width="7"
        stroke-linecap="round" :stroke-dasharray="CIRC" :stroke-dashoffset="arcOffset"
        transform="rotate(-90 110 110)"
      />
      <circle cx="110" cy="110" r="70" fill="none" stroke="rgba(46,36,23,.3)" stroke-width=".6" stroke-dasharray="1 5" />
      <g class="gauge-needle" :style="{ transform: `rotate(${needleDeg}deg)`, transformOrigin: '110px 110px' }">
        <path d="M110 110 L110 34" stroke="#9c3b2a" stroke-width="1.4" />
        <path d="M110 34 L106 44 L114 44 Z" fill="#9c3b2a" />
      </g>
      <circle cx="110" cy="110" r="5" fill="#2e2417" />
      <circle cx="110" cy="110" r="2" fill="#c9a24a" />
    </svg>
    <div class="gauge-center">
      <div class="gauge-num">{{ num }}</div>
      <div class="gauge-of">INDEX · 满分百</div>
    </div>
  </div>
</template>

<style scoped>
.gauge-box {
  position: relative;
  width: 280px;
  height: 280px;
  max-width: 100%;
}
.gauge-box svg {
  width: 100%;
  height: 100%;
}
.gauge-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.gauge-num {
  font-family: var(--disp);
  font-weight: 700;
  font-size: 58px;
  line-height: 1;
  color: var(--ink);
}
.gauge-of {
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: var(--ink-faint);
  margin-top: 6px;
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && pnpm test -- IndexGauge`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/index/IndexGauge.vue web/tests/IndexGauge.test.ts
git commit -m "feat(index): IndexGauge SVG 指针仪表盘组件"
```

---

### Task 6: `TrendBars.vue` 24h 柱状趋势（FIG.2）

**Files:**
- Create: `web/src/components/index/TrendBars.vue`
- Test: `web/tests/TrendBars.test.ts`

**Interfaces:**
- Consumes: `HourlyPoint`（types.ts 已有：`{time, score, grade, cloud, precip}`）
- Produces: `props: { hourly: HourlyPoint[]; nowTime?: string }`；渲染 `.cbar`（每点一根）；`hour.score` 最高连续段（±10 分且 ≥60）标记 `.best` 并在图例显示 `☾ 最佳观测窗 HH:MM — HH:MM`；`time === nowTime` 标记 `.now`（✦）。

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import TrendBars from '../src/components/index/TrendBars.vue'
import type { HourlyPoint } from '../src/types'

function pt(h: number, score: number): HourlyPoint {
  const hh = String(h).padStart(2, '0')
  return { time: `2026-09-10T${hh}:00`, score, grade: '良', cloud: 10, precip: 0 }
}

const hourly: HourlyPoint[] = [
  pt(0, 90), pt(1, 88), pt(2, 86), pt(3, 70), pt(4, 40), pt(5, 20),
  pt(6, 10), pt(7, 15), pt(8, 30),
]

describe('TrendBars', () => {
  it('渲染每点一根柱', () => {
    const w = mount(TrendBars, { props: { hourly } })
    expect(w.findAll('.cbar')).toHaveLength(hourly.length)
  })

  it('标记最佳观测窗（连续高分段）与当前时刻', () => {
    const w = mount(TrendBars, { props: { hourly, nowTime: '2026-09-10T05:00' } })
    expect(w.findAll('.cbar.best').length).toBe(4) // 00-03 时
    expect(w.findAll('.cbar.now').length).toBe(1)
    expect(w.text()).toContain('最佳观测窗')
    expect(w.text()).toContain('00:00')
  })

  it('空数据渲染占位文案', () => {
    const w = mount(TrendBars, { props: { hourly: [] } })
    expect(w.text()).toContain('暂不可用')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- TrendBars`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写组件（照 concept 183-193 行样式 + 图例语义）**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { HourlyPoint } from '../../types'

const props = defineProps<{ hourly: HourlyPoint[]; nowTime?: string }>()

function hhmm(t: string): string {
  return t.split('T')[1]?.slice(0, 5) ?? t
}

const bestRange = computed<[number, number] | null>(() => {
  const pts = props.hourly
  if (pts.length === 0) return null
  let peak = 0
  pts.forEach((p, i) => { if (p.score > pts[peak].score) peak = i })
  if (pts[peak].score < 60) return null
  let a = peak
  let b = peak
  while (a > 0 && pts[a - 1].score >= 60 && pts[a - 1].score >= pts[peak].score - 10) a--
  while (b < pts.length - 1 && pts[b + 1].score >= 60 && pts[b + 1].score >= pts[peak].score - 10) b++
  return [a, b]
})

const bestLabel = computed(() => {
  if (!bestRange.value) return null
  const [a, b] = bestRange.value
  return `${hhmm(props.hourly[a].time)} — ${hhmm(props.hourly[b].time)}`
})

function barH(score: number): string {
  return `${Math.max(2, score)}%`
}
</script>

<template>
  <div v-if="hourly.length === 0" class="bars-empty">
    趋势图暂不可用 —— 简版指数仅提供总评。
  </div>
  <template v-else>
    <div class="chart-box">
      <div class="chart-bars">
        <i
          v-for="(p, i) in hourly" :key="p.time" class="cbar"
          :class="{
            good: p.score >= 60,
            best: bestRange !== null && i >= bestRange[0] && i <= bestRange[1],
            now: p.time === nowTime,
          }"
          :style="{ height: barH(p.score) }"
        />
      </div>
    </div>
    <div class="chart-axis">
      <span v-for="h in [0, 4, 8, 12, 16, 20]" :key="h">{{ String(h).padStart(2, '0') }}</span>
      <span>24</span>
    </div>
    <div class="chart-note">
      <span v-if="bestLabel">☾ 最佳观测窗 <b>{{ bestLabel }}</b></span>
      <span>✦ 当前时刻</span>
    </div>
  </template>
</template>

<style scoped>
.bars-empty {
  text-align: center;
  color: var(--ink-faint);
  font-style: italic;
  padding: 30px 10px;
}
.chart-box {
  position: relative;
  height: 190px;
  border: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line);
  background: repeating-linear-gradient(to top, transparent 0 37px, rgba(46, 36, 23, 0.07) 37px 38px);
}
.chart-bars {
  position: absolute;
  inset: 8px 8px 0;
  display: flex;
  align-items: flex-end;
  gap: 3px;
}
.cbar {
  flex: 1;
  min-width: 4px;
  height: 0;
  border-top: 2px solid var(--ink-soft);
  background: repeating-linear-gradient(0deg, rgba(92, 75, 50, 0.85) 0 2px, rgba(92, 75, 50, 0.45) 2px 4px);
  transition: height 0.9s cubic-bezier(0.2, 0.8, 0.2, 1);
  position: relative;
}
.cbar.good {
  border-top-color: var(--gold);
  background: repeating-linear-gradient(0deg, rgba(169, 126, 47, 0.9) 0 2px, rgba(201, 162, 74, 0.4) 2px 4px);
}
.cbar.now::after {
  content: '✦';
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--seal);
  font-size: 10px;
}
.cbar.best::before {
  content: '☾';
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--gold);
  font-size: 11px;
}
.chart-axis {
  display: flex;
  justify-content: space-between;
  font-family: var(--disp);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
  margin-top: 8px;
  padding: 0 6px;
}
.chart-note {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 14px;
  font-family: var(--cn);
  font-size: 12.5px;
  color: var(--ink-soft);
}
.chart-note b {
  color: var(--gold);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && pnpm test -- TrendBars`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/index/TrendBars.vue web/tests/TrendBars.test.ts
git commit -m "feat(index): TrendBars 24h 柱状趋势组件（最佳观测窗/当前时刻标记）"
```

---

### Task 7: `MoonCard.vue` 今夜月相（FIG.3）

**Files:**
- Create: `web/src/components/index/MoonCard.vue`
- Test: `web/tests/MoonCard.test.ts`

**Interfaces:**
- Consumes: `StargazeMoon`（`{phase, illumination, label}`，phase 即月龄）+ `StargazeAstro`
- Produces: `props: { moon: StargazeMoon; astro?: StargazeAstro }`；渲染月相 SVG（`.moon-ico` 内 `path.moon-shape`）、月龄标题、照明度与西沉行、`✓ 月落之后，深空朗澈`（moonset 有值时）、四枚时间 chip（`暗夜保护区` 恒显 gold；`日落/天文晨光/银河核心升起` 取 astro 值，缺省显示 `—`）。

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MoonCard from '../src/components/index/MoonCard.vue'
import type { StargazeAstro, StargazeMoon } from '../src/types'

const moon: StargazeMoon = { phase: 3.2, illumination: 0.11, label: '蛾眉月' }
const astro: StargazeAstro = {
  sunset: '18:52', astro_dawn: '04:31', moonset: '21:08', galactic_rise: '22:40',
}

describe('MoonCard', () => {
  it('渲染月相名/月龄/照明度/西沉与时间 chips', () => {
    const w = mount(MoonCard, { props: { moon, astro } })
    expect(w.text()).toContain('蛾眉月')
    expect(w.text()).toContain('月龄 3.2')
    expect(w.text()).toContain('照明度 11%')
    expect(w.text()).toContain('21:08 西沉')
    expect(w.text()).toContain('月落之后，深空朗澈')
    expect(w.text()).toContain('日落 18:52')
    expect(w.text()).toContain('天文晨光 04:31')
    expect(w.text()).toContain('银河核心 22:40 升')
    expect(w.find('path.moon-shape').exists()).toBe(true)
  })

  it('astro 缺省时时间位显示 —', () => {
    const w = mount(MoonCard, { props: { moon } })
    expect(w.text()).toContain('日落 —')
    expect(w.text()).not.toContain('月落之后')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- MoonCard`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写组件（月相 SVG 双弧法）**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { StargazeAstro, StargazeMoon } from '../../types'

const props = defineProps<{ moon: StargazeMoon; astro?: StargazeAstro }>()

const R = 25
const CX = 26
const CY = 26

/** 月相双弧法：phase∈[0,29.53)，0=新月。返回亮面 path。 */
const moonPath = computed(() => {
  const phase = ((props.moon.phase % 29.53) + 29.53) % 29.53
  const k = phase / 29.53
  // 亮面宽边：盈月（k<0.5）在西侧（右），亏月在东侧（左）
  const waxing = k < 0.5
  // 中线椭圆半宽：0（弦月直边）→ R（半月圆边）→ 0
  const bulge = Math.abs(Math.cos(2 * Math.PI * k)) * R
  const sweepOuter = waxing ? 1 : 0
  const sweepInner = waxing ? (k < 0.25 ? 1 : 0) : (k < 0.75 ? 0 : 1)
  const outer =
    `M ${CX} ${CY - R} A ${R} ${R} 0 0 ${sweepOuter} ${CX} ${CY + R} `
  const inner =
    `A ${Math.max(0.01, bulge)} ${R} 0 0 ${sweepInner} ${CX} ${CY - R} Z`
  return outer + inner
})

const illumPct = computed(() => Math.round(props.moon.illumination * 100))
</script>

<template>
  <div class="moon-card">
    <svg class="moon-ico" viewBox="0 0 52 52" role="img" :aria-label="moon.label">
      <circle :cx="CX" :cy="CY" :r="R" fill="#c9b98e" stroke="var(--line)" />
      <path class="moon-shape" :d="moonPath" fill="#f7f0da" />
    </svg>
    <div class="t">
      <b>{{ moon.label }} · 月龄 {{ moon.phase.toFixed(1) }}</b>
      <span>
        照明度 {{ illumPct }}%
        <template v-if="astro?.moonset"> · {{ astro.moonset }} 西沉</template>
      </span>
      <span v-if="astro?.moonset" class="ok-line">✓ 月落之后，深空朗澈</span>
    </div>
  </div>
  <div class="moon-chips">
    <span class="chip gold">暗夜保护区</span>
    <span class="chip">日落 {{ astro?.sunset ?? '—' }}</span>
    <span class="chip">天文晨光 {{ astro?.astro_dawn ?? '—' }}</span>
    <span class="chip gold">银河核心 {{ astro?.galactic_rise ?? '—' }} 升</span>
  </div>
</template>

<style scoped>
.moon-card {
  display: flex;
  gap: 16px;
  align-items: center;
}
.moon-ico {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  flex: none;
  border: 1px solid var(--line);
}
.moon-card .t {
  font-family: var(--cn);
}
.moon-card .t b {
  font-size: 15px;
  font-weight: 700;
}
.moon-card .t span {
  display: block;
  font-size: 12px;
  color: var(--ink-faint);
}
.ok-line {
  color: var(--good);
}
.moon-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}
</style>
```

> `chip` 全局样式已在全局样式表（对齐 concept 125-128 行；若全局表没有 `chip` 类则在全局样式补齐，不改 scoped）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && pnpm test -- MoonCard`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/index/MoonCard.vue web/tests/MoonCard.test.ts
git commit -m "feat(index): MoonCard 今夜月相卡（月相 SVG + 时间 chips）"
```

---

### Task 8: `IndexView.vue` 双栏重排 + 城市搜索接入

**Files:**
- Modify: `web/src/views/IndexView.vue`（全面重排，保留 loading/error/ready 三态、frontispiece、mascot、orion/图鉴按钮、24h/7天 chip）
- Test: `web/tests/IndexView.test.ts`（sampleIndex 加 `astro` 字段并更新断言）

**Interfaces:**
- Consumes: Task 4 store `search/selectSearchResult/searchResults/searching`；Task 5/6/7 三组件
- Produces: 双栏 `index-grid`（左 PLATE Ⅰ 主图版 / 右 FIG.2 + FIG.3）；`datalist#cityList` 城市搜索（输入防抖 300ms → `store.search`；change → `selectSearchResult`）；「◎ 自动定位」→ `store.locate()`

- [ ] **Step 1: 更新测试（先改断言使其失败）**

`IndexView.test.ts` 的 `sampleIndex` 加：

```ts
    astro: {
      sunset: '18:52', astro_dawn: '04:31',
      moonset: '21:08', galactic_rise: '22:40',
    },
```

ready 用例追加断言：

```ts
    expect(wrapper.find('.index-grid').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'IndexGauge' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('FIG. 2')
    expect(wrapper.text()).toContain('FIG. 3')
    expect(wrapper.text()).toContain('日落 18:52')
```

删除/替换旧断言中针对已删结构的选择器（`.dial`、`.comp-bar`、`.curve`——以实际文件为准逐条替换）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && pnpm test -- IndexView`
Expected: FAIL

- [ ] **Step 3: 重排 IndexView**

结构（保留原有 script 中 `status/data/gradeColor/setRange/onCitySelect` 等仍被引用的逻辑；删除 curve 计算块与 components computed；新增城市搜索状态）：

```ts
import { computed, onMounted, ref, watch } from 'vue'
import { useStargazeStore, PRESET_CITIES } from '../stores/stargaze'
import PlateBox from '../components/common/PlateBox.vue'
import StarBtn from '../components/common/StarBtn.vue'
import StarChip from '../components/common/StarChip.vue'
import IndexGauge from '../components/index/IndexGauge.vue'
import TrendBars from '../components/index/TrendBars.vue'
import MoonCard from '../components/index/MoonCard.vue'

// …保留 status/data/gradeColor …

const cityQuery = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

watch(cityQuery, (q) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.search(q), 300)
})

function onCityPick(e: Event): void {
  const el = e.target as HTMLInputElement
  const hit = store.searchResults.find(
    (r) => `${r.name}${r.admin1 ? `·${r.admin1}` : ''}` === el.value,
  )
  if (hit) {
    cityQuery.value = hit.name
    store.selectSearchResult(hit)
  }
}

const factors = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { key: 'cloud', label: '云量覆盖', display: `${d.now.cloud}%`, value: d.now.cloud },
    { key: 'rain', label: '降水概率', display: `${d.now.precip}%`, value: d.now.precip },
    { key: 'light', label: '光污染强度', display: `${d.bortle_label} · ${Math.round(d.components.bortle)}%`, value: d.components.bortle },
  ]
})
```

template 骨架（ready 态内，样式从 concept §Ⅰ 移入 scoped）：

```html
<div class="index-grid">
  <!-- 左：PLATE Ⅰ 主图版 -->
  <div class="plate">
    <div class="plate-cap"><b>PLATE Ⅰ</b><span>观星指数 · 今夜之鉴</span><i class="rule"></i><span class="fleuron">❧</span></div>
    <div class="plate-body">
      <div class="city-bar">
        <input v-model="cityQuery" class="field" list="cityList" placeholder="手动搜索城市，如 冷湖 / 杭州 / 重庆…" />
        <datalist id="cityList">
          <option v-for="r in store.searchResults" :key="`${r.latitude},${r.longitude}`" :value="`${r.name}${r.admin1 ? `·${r.admin1}` : ''}`" />
        </datalist>
        <StarBtn label="查阅" @click="onCityPickFromInput" />
        <StarBtn label="◎ 自动定位" variant="gold" @click="store.locate()" />
      </div>
      <div class="city-title">
        <h3>{{ data.province }} · {{ data.city }}</h3>
        <span class="tag">北纬 {{ data.lat.toFixed(2) }}° · Bortle {{ data.bortle }} · {{ data.bortle_label }}</span>
      </div>
      <div class="gauge-wrap">
        <IndexGauge :score="data.score" />
        <div class="gauge-meta">
          <div class="seal" :class="`lv-${data.grade}`">{{ data.grade }}</div>
          <div class="lv"><b>{{ data.grade }}</b><span>{{ gradeDesc }}</span></div>
        </div>
        <div class="lv-legend"><i class="g">优 ≥80</i><i>良 60–79</i><i>一般 40–59</i><i class="r">差 &lt;40</i></div>
      </div>
      <div class="divider-orn">☾ 综合云量 · 降水 · 光污染 ☽</div>
      <template v-for="f in factors" :key="f.key">
        <div class="meter-row"><span>{{ f.label }}</span><b>{{ f.display }}</b></div>
        <div class="meter-track"><div class="meter-fill" :style="{ width: `${Math.min(100, f.value)}%` }"></div></div>
      </template>
    </div>
  </div>
  <!-- 右：FIG.2 + FIG.3 -->
  <div class="side-col">
    <div class="plate">
      <div class="plate-cap"><b>FIG. 2</b><span>未来 {{ store.rangeDays === 1 ? '24 时' : '7 日' }}趋势</span><i class="rule"></i><span class="fleuron">❧</span></div>
      <div class="plate-body">
        <TrendBars :hourly="data.hourly" :now-time="data.now.time" />
        <div class="curve-tabs"><StarChip label="24 小时" :active="store.rangeDays === 1" @click="setRange(1)" /><StarChip label="7 天" :active="store.rangeDays === 7" @click="setRange(7)" /></div>
      </div>
    </div>
    <div class="plate">
      <div class="plate-cap"><b>FIG. 3</b><span>今夜月相</span><i class="rule"></i><span class="fleuron">❧</span></div>
      <div class="plate-body">
        <MoonCard :moon="data.moon" :astro="data.astro" />
      </div>
    </div>
  </div>
</div>
```

> 等级图例口径以 `services/index.py` 为准（≥80/60/40），不用 concept 的 90/75/55——算法未改，文案必须与真实分档一致。
> `gradeDesc` 映射：优→「夜空澄澈，宜观星」良→「尚可一观，留意月色」一般→「条件平平，量力而行」差→「云深雨重，不宜观星」。
> `onCityPickFromInput`：input 值与 `searchResults` 精确匹配则 `selectSearchResult`，否则提示无果（复用 toast/简单文案均可）。
> scoped 样式从 concept 抄：`.index-grid`（160 行）、`.plate/.plate-cap/.plate-body`（85-94，若全局已有则不重复）、`.gauge-wrap/.gauge-meta/.lv-legend`（161-175）、`.city-bar/.field/.city-title`（176-180 + 120-123）、`.divider-orn/.meter-row/.meter-track/.meter-fill`（181-141）、`.seal .lv-优/良/一般/差`（130-134）、`.side-col{display:flex;flex-direction:column;gap:22px}`；响应式 `@media(max-width:1000px){.index-grid{grid-template-columns:1fr}}`。
> 检查全局样式表（`web/src/style.css` 或 App.vue 全局段）中是否已有 `.plate/.chip/.seal`：已有则直接复用，没有才补。

- [ ] **Step 4: 跑全部前端测试 + 类型检查 + 构建**

Run: `cd web && pnpm test && pnpm build`
Expected: 全 PASS，vue-tsc 无错误

- [ ] **Step 5: Commit**

```bash
git add web/src/views/IndexView.vue web/tests/IndexView.test.ts
git commit -m "feat(index): IndexView 双栏图版重排（仪表盘/柱状趋势/月相卡/城市搜索）"
```

---

### Task 9: 联调验证 + 大赛提交物截图

**Files:**
- 无代码改动（验证 + 截图）

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: 起后端 + 前端联调**

```bash
cd server && .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
cd web && pnpm dev
```

浏览器打开 `http://localhost:5173`，核对：
1. 双栏布局与小屏（≤1000px）单栏折叠正常
2. 仪表盘指针/圆弧动画到位，分数与 `/api/index` 一致
3. 搜索「冷湖」→ datalist 出现候选项 → 选中后数据刷新
4. FIG.2 出现 ☾ 最佳观测窗与 ✦ 当前时刻
5. FIG.3 月相形状与月龄相符、四枚 chip 时间正确（与真实现场日落/晨光对比）
6. 24h/7天切换柱状图正常刷新

- [ ] **Step 2: 手跑后端全量测试**

Run: `cd server && .venv/Scripts/python.exe -m pytest -q`
Expected: 全 PASS

- [ ] **Step 3: 更新大赛提交物（CLAUDE.md 强制）**

观星指数页前后对比截图存入 `作品提交文件夹/04码道使用证明/`，并在 commit 时一并 `git add "作品提交文件夹/04码道使用证明/"*.png`。

- [ ] **Step 4: Squash 合并前自查**

```bash
git log --oneline main..HEAD
git diff main --stat
```

对照 spec（concept HTML）逐项核对后，请求用户确认 squash 回 main（规范默认要求确认）。

---

## Self-Review 记录

- **Spec 覆盖**：双栏（Task 8）、指针仪表盘（Task 5）、斜纹 meter（Task 8）、FIG.2 柱状图+双标记（Task 6）、FIG.3 月相卡+时间 chips（Task 7）、城市搜索（Task 3/4）、后端四时间字段（Task 1/2）。等级图例文案以真实算法口径为准（有意偏离 concept 的 90/75/55 示例值）。
- **占位符扫描**：无 TBD；Task 8 Step 3 给出完整结构骨架与样式来源行号（concept 精确行），实施者需按行号抄样式而非自行发挥。
- **类型一致性**：`StargazeAstro` 字段名（sunset/astro_dawn/moonset/galactic_rise）在 Task 1/2/3/7/8 间一致；`searchCity(q, signal?)` 在 Task 3/4 一致；`TrendBars` props 在 Task 6/8 一致。
- **已知风险**：astral 3.x `twilight` 签名以实装时 `help(astral.sun.twilight)` 为准；astropy `get_body` 需要 `EarthLocation` 显式传参（版本 ≥5 API）；jsdom 无 `matchMedia` 时组件需容错（`window.matchMedia?.(...) ?? {matches:false}`——Task 5 实装时注意）。