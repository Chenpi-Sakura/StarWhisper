# 观星指数页自定义时间区间实施计划（7 天缓存 + 日切 + daily_moon/daily_astro）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/api/index` 一次性拉满 7 天天气并在内存缓存 10min；前端 chip 24h/7天 + 新增日期选择器，按日切 FIG.2 / MoonCard / astro chips；月相与天文时刻按 daily 化数组返回，区间切换走切片不重拉。

**Architecture:**
- 后端：`routers/index.py` 拉一次 days=7 缓存 (lat,lon) → forecast dict；新增 `daily_moon[7]` 与 `daily_astro[7]`（每个元素含 sunset/astro_dawn/moonset/galactic_rise）；响应 `hourly` 为所选区间的切片；接口入参变更为 `start_hour`(0-167) + `hours`(1-168)，保留 `days` 向后兼容（days=1 → start_hour=0, hours=24；days=7 → start_hour=0, hours=168）。
- 前端：types 增加 `daily_moon/daily_astro`；store 增加 `selectedDayIndex(0-6)`、`rangeHours(24|168)`；视图加 `<input type="date">` 选择器（min/today，max/+6day），选中后只改 start_hour/hours 重切片，不重 fetch。

**Tech Stack:** FastAPI + astral 3.x + astropy（已依赖）；Vue 3 + Pinia + vitest（已依赖）。

**Spec:** 用户已通过 question 拍板（UI: chip+日期选择器；缓存位置: 后端路由；月相: daily_moon[7]）；前后端设计点同上。

## Global Constraints

- 评分算法、四档口径、一票否决**一律不动**（`services/index.py` 不得出现在 diff，除非新增 build_daily_moon）
- 接口向后兼容：旧 `?days=1&days=7` 仍工作（映射到 start_hour=0 + hours=24/168）
- 缓存粒度：模块级 dict `_forecast_cache: dict[tuple[float,float], tuple[float, dict]]`，key 用 (round(lat,3), round(lon,3))；TTL 10 分钟；过期重新 fetch
- daily_astro 七天全量预计算（首次慢，缓存命中后切区间 < 100ms）；与 forecast cache 同生命周期
- astro 时区仍统一 Asia/Shanghai（沿用 T2 修复后的 `today = datetime.now(astro_times.TZ).date()`）
- IERS auto_download 仍关闭
- 前端 web 文件无强制末尾换行（仓库 52/52 惯例）
- 字段命名：sunset/astro_dawn/moonset/galactic_rise（沿用）；前端 store 名 `selectedDayIndex`（0-6，0=今天）
- mock 风格：monkeypatch.setattr 打模块属性（沿用 T2 偏好 PREFERENCE_1）

---

### Task 1: 后端 services/index.py + services/astro_times.py —— build_daily_moon + cache 友好的 astro batch

**Files:**
- Modify: `server/services/index.py`（新增 `build_daily_moon(start_date, days=7)` 纯函数）
- Test: `server/tests/test_index.py`（追加 build_daily_moon 测试）

**Interfaces:**
- Produces:
  - `def build_daily_moon(start_date: date, days: int = 7) -> list[dict]`
  - 返回列表元素同 `moon_info(d)` 形态：`{"phase": float, "illumination": float, "label": str}`；长度 == days；每个元素对应 start_date + i 日

- [ ] **Step 1: 写失败测试**

```python
def test_build_daily_moon_length_and_monotonic():
    out = idx.build_daily_moon(date(2026, 9, 10), days=7)
    assert len(out) == 7
    # phase 在 ~28 天周期内每天推进 ~1/29.53
    assert out[1]["phase"] > out[0]["phase"]
    assert out[6]["label"]  # 文案非空


def test_build_daily_moon_default_days_is_7():
    out = idx.build_daily_moon(date(2026, 9, 10))
    assert len(out) == 7
```

- [ ] **Step 2: 跑确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index.py::test_build_daily_moon_length_and_monotonic -v`
Expected: FAIL `AttributeError: module 'services.index' has no attribute 'build_daily_moon'`

- [ ] **Step 3: 写实现**

```python
def build_daily_moon(start_date: date, days: int = 7) -> list[dict]:
    """生成未来 N 天的每日月相（与 moon_info(d) 同形态）。"""
    return [moon_info(start_date + timedelta(days=i)) for i in range(days)]
```

文件顶部 `from datetime import date, timedelta`（已有 `date`，补 `timedelta`）。

- [ ] **Step 4: 跑通过**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add server/services/index.py server/tests/test_index.py
git commit -m "feat(index): build_daily_moon 7 日月相生成器"
```

---

### Task 2: 后端 routers/index.py —— 7 天缓存 + start_hour/hours 切片 + daily_moon/daily_astro

**Files:**
- Modify: `server/routers/index.py`（重大重构）
- Modify: `server/tests/test_index_router.py`（追加新断言）

**Interfaces:**
- Produces（响应扩展）：
  - `hourly`: 仍是 HourlyPoint[]，但**只包含所选区间**（start_hour..start_hour+hours）
  - `now`: 取区间内第一个小时
  - `score / grade`: 取区间内第一个小时
  - `day_index`: int（0=今天）
  - `daily_moon`: list[{phase, illumination, label}] 长度 7
  - `daily_astro`: list[{sunset, astro_dawn, moonset, galactic_rise}] 长度 7
  - 保留 `moon` 字段（与 daily_moon[day_index] 同值，向后兼容）
- 入参：
- `lat`, /`lon`: 必填
- `days`: 向后兼容（1 或 7），存在时映射 start_hour=0 + hours=24/168
- `start_hour`: int 0-167（默认 0）
- `hours`: int 1-168（默认 168）
- 内部：永远 days=7 拉一次；缓存命中后只切片计算 hourly

- [ ] **Step 1: 在 test_index_router.py 追加失败测试**

读现状 test_index_router.py（已合并 T2、T9 final fixes 调整），在 `test_index_astro_fields_optional_null` 之后追加：

```python
def test_index_response_contains_daily_arrays(client, monkeypatch):
    import routers.index as router_mod
    monkeypatch.setattr(router_mod, "_forecast_cache", {})  # 强制重 fetch
    monkeypatch.setattr(router_mod.astro_times, "sunset_time",
                        lambda *a, **k: "18:52")
    monkeypatch.setattr(router_mod.astro_times, "astro_dawn_time",
                        lambda *a, **k: "04:31")
    monkeypatch.setattr(router_mod.astro_times, "moonset_time",
                        lambda *a, **k: "21:08")
    monkeypatch.setattr(router_mod.astro_times, "galactic_rise_time",
                        lambda *a, **k: "22:40")

    resp = client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    assert resp.status_code == 200
    body = resp.json()
    assert body["day_index"] == 0
    assert isinstance(body["daily_moon"], list) and len(body["daily_moon"]) == 7
    assert isinstance(body["daily_astro"], list) and len(body["daily_astro"]) == 7
    assert body["daily_astro"][0]["sunset"] == "18:52"
    # 区间切片：hours=24 → 24 条
    assert len(body["hourly"]) == 24


def test_index_hours_param_slices_24h(client, monkeypatch):
    import routers.index as router_mod
    monkeypatch.setattr(router_mod, "_forecast_cache", {})
    for n in ("sunset_time", "astro_dawn_time", "moonset_time",
              "galactic_rise_time"):
        monkeypatch.setattr(router_mod.astro_times, n, lambda *a, **k: "12:00")

    r = client.get("/api/index?lat=39.9&lon=116.4&start_hour=24&hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body["day_index"] == 1
    assert len(body["hourly"]) == 24


def test_index_legacy_days_param_still_works(client, monkeypatch):
    import routers.index as router_mod
    monkeypatch.setattr(router_mod, "_forecast_cache", {})
    for n in ("sunset_time", "astro_dawn_time", "moonset_time",
              "galactic_rise_time"):
        monkeypatch.setattr(router_mod.astro_times, n, lambda *a, **k: "12:00")

    r1 = client.get("/api/index?lat=39.9&lon=116.4&days=1")
    assert len(r1.json()["hourly"]) == 24
    r7 = client.get("/api/index?lat=39.9&lon=116.4&days=7")
    assert len(r7.json()["hourly"]) == 168


def test_index_cache_avoids_repeat_fetch(client, monkeypatch):
    import routers.index as router_mod
    monkeypatch.setattr(router_mod, "_forecast_cache", {})
    fetch_calls = []
    real_fetch = router_mod.fetch_forecast

    async def spy(lat, lon, days=7, *, client=None):
        fetch_calls.append((lat, lon, days))
        return await real_fetch(lat, lon, days, client=client)
    monkeypatch.setattr(router_mod, "fetch_forecast", spy)

    client.get("/api/index?lat=39.9&lon=116.4&hours=24")
    client.get("/api/index?lat=39.9&lon=116.4&start_hour=24&hours=24")
    client.get("/api/index?lat=39.9&lon=116.4&hours=168")
    assert len(fetch_calls) == 1  # 三个请求只 fetch 一次
```

- [ ] **Step 2: 跑确认失败**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index_router.py -v`
Expected: 至少 `test_index_response_contains_daily_arrays` FAIL（KeyError day_index / TypeError daily_moon）

- [ ] **Step 3: 重构 routers/index.py**

```python
"""观星指数端点。

GET /api/index?lat=&lon=&start_hour=&hours=
       （向后兼容 days=1|7：days=1 → start_hour=0,hours=24；days=7 → 0,168）

- 按最近国内城市反查 Bortle 等级
- 一次性拉 7 天 Open-Meteo，模块级缓存 (lat,lon) 10min
- 计算 daily_moon[7] 与 daily_astro[7]
- 按 start_hour/hours 切片返回 hourly 与聚合 score/grade/now
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from services import astro_times
from services import index as index_svc
from services.weather import WeatherUnavailable, fetch_forecast

router = APIRouter(prefix="/api/index", tags=["index"])

_CACHE_TTL = 600.0  # seconds
_forecast_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 3), round(lon, 3))


async def _get_forecast(lat: float, lon: float) -> dict:
    import time as _t
    key = _cache_key(lat, lon)
    now_ts = _t.time()
    hit = _forecast_cache.get(key)
    if hit and hit[0] > now_ts:
        return hit[1]
    forecast = await fetch_forecast(lat, lon, days=7)
    _forecast_cache[key] = (now_ts + _CACHE_TTL, forecast)
    return forecast


@router.get("")
async def stargaze_index(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    days: int | None = Query(None, ge=1, le=7),
    start_hour: int = Query(0, ge=0, le=167),
    hours: int = Query(168, ge=1, le=168),
):
    # days 向后兼容
    if days is not None:
        if days == 1:
            start_hour, hours = 0, 24
        elif days == 7:
            start_hour, hours = 0, 168

    if start_hour + hours > 168:
        raise HTTPException(400, detail={
            "code": "RANGE_OUT_OF_BOUNDS",
            "message": "start_hour + hours 超出 168 小时",
        })

    city = index_svc.nearest_city(lat, lon)

    try:
        forecast = await _get_forecast(lat, lon)
    except WeatherUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "WEATHER_DOWN",
                    "message": "天气服务暂不可用", "advice": "请稍后重试"},
        ) from exc

    # 7 天 daily_moon
    now_local = datetime.now(astro_times.TZ)
    daily_moon = index_svc.build_daily_moon(now_local.date(), days=7)

    # 7 天 daily_astro
    daily_astro = []
    for i in range(7):
        d = now_local.date() + timedelta(days=i)
        daily_astro.append({
            "sunset": astro_times.sunset_time(lat, lon, d),
            "astro_dawn": astro_times.astro_dawn_time(lat, lon, datetime.combine(d, datetime.min.time()).replace(tzinfo=astro_times.TZ)),
            "moonset": astro_times.moonset_time(lat, lon, datetime.combine(d, datetime.min.time()).replace(tzinfo=astro_times.TZ)),
            "galactic_rise": astro_times.galactic_rise_time(lat, lon, datetime.combine(d, datetime.min.time()).replace(tzinfo=astro_times.TZ)),
        })

    # 区间切片
    sliced_times = forecast["time"][start_hour : start_hour + hours]
    sliced = {
        "time": sliced_times,
        "cloud_cover": forecast["cloud_cover"][start_hour : start_hour + hours],
        "precipitation_probability": forecast["precipitation_probability"][start_hour : start_hour + hours],
        "wind_speed_10m": forecast["wind_speed_10m"][start_hour : start_hour + hours],
        "temperature_2m": forecast["temperature_2m"][start_hour : start_hour + hours],
    }

    # 月相取切片对应日（一天的小时取该日 moon）
    day_index = start_hour // 24
    if day_index >= len(daily_moon):
        day_index = len(daily_moon) - 1
    moon_today = daily_moon[day_index]

    hourly = index_svc.build_hourly(
        sliced,
        moon_today["illumination"],
        city["bortle"],
        hours,
    )
    if not hourly:
        raise HTTPException(502, detail={
            "code": "WEATHER_EMPTY",
            "message": "天气数据为空", "advice": "请稍后重试",
        })

    first = hourly[0]
    components = index_svc.compute_components(
        cloud=first["cloud"],
        precip=first["precip"],
        wind=float(sliced["wind_speed_10m"][0]),
        temp=float(sliced["temperature_2m"][0]),
        illumination=moon_today["illumination"],
        bortle=city["bortle"],
    )

    return {
        "ok": True,
        "city": city["name"],
        "province": city["province"],
        "lat": city["lat"],
        "lon": city["lon"],
        "timezone": forecast.get("timezone"),
        "bortle": city["bortle"],
        "bortle_label": index_svc.bortle_label(city["bortle"]),
        "score": first["score"],
        "grade": first["grade"],
        "moon": moon_today,
        "now": {
            "time": first["time"],
            "cloud": first["cloud"],
            "precip": first["precip"],
            "wind": float(sliced["wind_speed_10m"][0]),
            "temp": float(sliced["temperature_2m"][0]),
        },
        "components": components,
        "hourly": hourly,
        "day_index": day_index,
        "daily_moon": daily_moon,
        "daily_astro": daily_astro,
        "astro": daily_astro[day_index],  # 向后兼容
    }
```

- [ ] **Step 4: 跑测试 + 全量后端**

Run: `cd server && .venv/Scripts/python.exe -m pytest tests/test_index_router.py tests/test_index.py tests/test_astro_times.py -v && .venv/Scripts/python.exe -m pytest -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add server/routers/index.py server/tests/test_index_router.py
git commit -m "feat(index): /api/index 7 天缓存 + start_hour/hours 切片 + daily_moon/daily_astro"
```

---

### Task 3: 前端 types + store + view（区间选择器 + 日切联动）

**Files:**
- Modify: `web/src/types.ts`（StargazeIndex + StargazeAstro 加 dayIndex/dailyMoon/dailyAstro）
- Modify: `web/src/stores/stargaze.ts`（selectedDayIndex、rangeHours、selectDay、load 切片参数）
- Modify: `web/src/api/stargaze.ts`（新增 start_hour/hours 查询参数，days 仍可用但内部映射）
- Modify: `web/src/views/IndexView.vue`（UI 加日期选择器；FIG.2/MoonCard/astro chips 按日切）
- Modify: `web/src/components/index/MoonCard.vue`（props moon 已是当前日，无需改实现；只需让 IndexView 传对值）
- Test: `web/tests/stargaze.store.test.ts`、`IndexView.test.ts`、`MoonCard.test.ts` 适配

**Interfaces:**
- `StargazeIndex` 新增：`dayIndex?: number`、`dailyMoon?: StargazeMoon[]`、`dailyAstro?: StargazeAstro[]`
- Store 新增：`selectedDayIndex: 0-6`、`rangeHours: 24 | 168`、`selectDay(index)`、`setRangeHours(h)`（替代或并存于 setRange）
- API：`fetchStargazeIndex(lat, lon, options)` options 新增 `startHour?: number`、`hours?: number`，days 仍可用
- View：input type="date" 绑 selectedDayIndex 派生的 ISO 日期；change → selectDay

- [ ] **Step 1: 改 types.ts**

在 `StargazeIndex` 接口中 `astro?: StargazeAstro` 后追加：

```ts
  /** /api/index 返回当前所选日的索引（0=今天，最大 6） */
  dayIndex?: number
  /** 未来 7 天每日月相（与 moon 同形态） */
  dailyMoon?: StargazeMoon[]
  /** 未来 7 天每日天文时刻（日落/晨光/月落/银心） */
  dailyAstro?: StargazeAstro[]
```

- [ ] **Step 2: 改 api/stargaze.ts**

```ts
export interface StargazeOptions {
  /** 曲线跨度：1 = 未来 24h，7 = 未来 7 天（向后兼容，映射 startHour=0 + hours=24/168） */
  days?: 1 | 7
  /** 起始小时偏移 0-167 */
  startHour?: number
  /** 区间长度 1-168 */
  hours?: number
  signal?: AbortSignal
}

export async function fetchStargazeIndex(
  lat: number, lon: number,
  options: StargazeOptions = {},
): Promise<StargazeIndex> {
  const { days, startHour, hours, signal } = options
  const params = new URLSearchParams({
    lat: String(lat), lon: String(lon),
  })
  if (days !== undefined) params.set('days', String(days))
  if (startHour !== undefined) params.set('start_hour', String(startHour))
  if (hours !== undefined) params.set('hours', String(hours))
  const r = await fetch(`/api/index?${params.toString()}`, { signal })
  if (!r.ok) throw new Error(`API /api/index HTTP ${r.status}`)
  return (await r.json()) as StargazeIndex
}
```

- [ ] **Step 3: 改 store**

在 stargaze.ts 顶部 `import { computed, watch } from 'vue'`（已 computed，加 watch），state 区追加：

```ts
const selectedDayIndex = ref(0)
const rangeHours = ref<24 | 168>(24)
```

替换 `setRange(days: 1 | 7)` 为：

```ts
async function setRangeHours(h: 24 | 168): Promise<void> {
  rangeHours.value = h
  selectedDayIndex.value = 0  // 切总窗口时回到今天
  await load(location.value.lat, location.value.lon, {
    startHour: 0, hours: h,
  })
}

async function selectDay(idx: number): Promise<void> {
  const i = Math.max(0, Math.min(6, Math.floor(idx)))
  selectedDayIndex.value = i
  await load(location.value.lat, location.value.lon, {
    startHour: i * 24, hours: 24,
  })
}
```

把现有 `setRange` 调用方改为 `setRangeHours` 或保留旧名作薄包装（标记 deprecated）。

`load` 签名扩展：接收 options 对象（或兼容 days）。最简：直接传 params 给 fetchStargazeIndex：

```ts
async function load(
  lat: number, lon: number,
  options: { days?: 1 | 7; startHour?: number; hours?: number; signal?: AbortSignal } = {},
  signal?: AbortSignal,
): Promise<void> {
  status.value = 'loading'
  errorMessage.value = null
  try {
    const result = await fetchStargazeIndex(lat, lon, { ...options, signal })
    data.value = result
    location.value = { lat, lon, label: result.city }
    status.value = 'ready'
  } catch {
    status.value = 'error'
    errorMessage.value = '天气服务暂不可用，请稍后重试'
  }
}
```

注意：abort 取消时不要进 error 态——AbortError 静默跳过。store 内部 catch 不区分错误时已正确处理（取消也算 error），可以接受；若严格可后续改进。

把现有 selectCity / setRange / selectSearchResult 改为新的 options 风格（如 `load(lat, lon, { startHour: ..., hours: ... })`）。

return 字段：`selectedDayIndex, rangeHours, setRangeHours, selectDay,` 替换 `setRange`。

- [ ] **Step 4: 改 IndexView.vue**

新增 state：

```ts
import { computed } from 'vue'
const selectedDay = computed({
  get: () => store.selectedDayIndex,
  set: (v: number) => store.selectDay(v),
})
const dayLabel = computed(() => {
  // ISO 日期 = today + selectedDayIndex
  const d = new Date()
  d.setDate(d.getDate() + store.selectedDayIndex)
  return d.toISOString().slice(0, 10)
})
function minDay() { return new Date().toISOString().slice(0, 10) }
function maxDay() {
  const d = new Date(); d.setDate(d.getDate() + 6)
  return d.toISOString().slice(0, 10)
}
```

UI（FIG.2 区段，FIG.2 plate-cap 之后）：

```html
<div class="date-picker">
  <span class="picker-label">日期</span>
  <input
    type="date" :min="minDay()" :max="maxDay()" :value="dayLabel"
    @change="onDayChange"
  />
</div>
```

`onDayChange`：`const offset = Math.round((Date.parse(target.value) - Date.parse(minDay())) / 86400000); selectedDay.value = offset`。

UI（chip 24h/7天 区域）：保留但调用 store.setRangeHours(h)；初始默认 24h。

MoonCard 接收的 moon/astro 改为按 selectedDayIndex：

```ts
const currentMoon = computed(() =>
  data.value?.dailyMoon?.[store.selectedDayIndex] ?? data.value?.moon
)
const currentAstro = computed(() =>
  data.value?.dailyAstro?.[store.selectedDayIndex] ?? data.value?.astro
)
```

模板 `<MoonCard :moon="currentMoon" :astro="currentAstro" />`。

FIG.2 的 `<TrendBars>` 不变（接收 hourly 切片）。

- [ ] **Step 5: 测试更新**

`stargaze.store.test.ts`：sampleIndex 加 dayIndex/dailyMoon/dailyAstro；增 `setRangeHours` 与 `selectDay` 测试。
`IndexView.test.ts`：sampleIndex 同上；增日期选择器存在 + 切换日期触发 store.selectDay 断言。
`MoonCard.test.ts`：不变（组件无实现变更）。

- [ ] **Step 6: 全量前端测试 + build**

Run: `cd web && pnpm test && pnpm build`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/types.ts web/src/api/stargaze.ts web/src/stores/stargaze.ts \
        web/src/views/IndexView.vue web/tests/stargaze.store.test.ts \
        web/tests/IndexView.test.ts
git commit -m "feat(index): 日期选择器 + selectedDayIndex 联动（FIG.2/MoonCard/astro 切片）"
```

---

### Task 4: 联调验证 + 最终评审

**Files:** 无代码改动

- [ ] **Step 1: 起后端 + 前端**

```bash
cd server && .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
cd web && pnpm dev
```

- [ ] **Step 2: 联调核对**

1. 首次加载：response time 应 ~10-20s（首次算 7 天 daily astro moonset ×7 + galactic_rise ×7）；后续切区间 < 200ms（缓存命中）
2. UI：FIG.2 区段出现日期选择器；默认今天；可前后翻到 +6 day
3. 切日期：FIG.2 柱状图刷新；MoonCard 月相/月龄刷新；astro chips 时间刷新
4. 切 chip 24h/7天：24h 切到 168h 全展示；7天再切回 24h 回到今天切片
5. dev tools 多次 GET /api/index?... 只看到首次网络请求，后续切片请求无 fetch（Network 面板）

- [ ] **Step 3: 全量测试**

后端：`cd server && .venv/Scripts/python.exe -m pytest -q`
前端：`cd web && pnpm test && pnpm build`

- [ ] **Step 4: 派 final code reviewer**

跑 reviewer（task reviewer skill 模板），按最终评审流程走。

## Self-Review 记录

- **Spec 覆盖**：UI 区间（chip+date）+ 后端缓存 + daily_moon/daily_astro + 后端切片 + 前端日切联动 → 全部对应到 Task 1-4。
- **占位符扫描**：无 TBD/TODO。
- **类型一致性**：`StargazeAstro` 字段名沿用；`StargazeIndex.dayIndex/dailyMoon/dailyAstro` 三字段名在 types/api/store/view 间一致。
- **已知风险**：
  - 首次响应 ~10-20s（含 14 次 astropy 扫描）—— 缓存 10min 内仅首次慢，可接受。可后续优化为仅在 daily_moon 切日时懒算对应日 astro（首屏即返回 daily_moon[0].astro + 7 天 moon；切日时再补算）。
  - `load` 的 AbortError 未静默（仍进 error 态）—— 当前实现接受此行为；待 I4 park 后续统一。
  - IERS 即使关了 auto_download 仍可能偶发网络回退到 bundled finals2000A—— 已在 T1 实装验证稳定。