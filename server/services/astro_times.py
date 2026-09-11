"""天文时刻计算：日出 / 日落 / 天文暮光 / 天文晨光 / 月出月落 / 银心升落。

- astral 3.x：日出日落（sunrise/sunset）、天文暮光（dusk/dawn，太阳到 -18°）
- astropy：月亮与银心（人马座 A*）高度角采样 + 线性插值过零
  （*_events 系列共享一条序列，出一对升/落只扫一次）
- 时间统一 Asia/Shanghai，输出 "HH:MM"；事件不可见（极昼/极区/窗口外）→ None
- astropy IERS 自动下载必须关闭（离线环境防卡死）
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import dawn as _astral_dawn
from astral.sun import dusk as _astral_dusk
from astral.sun import sunrise as _astral_sunrise
from astral.sun import sunset as _astral_sunset

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
        dt = _astral_sunset(Observer(lat, lon), date=d, tzinfo=TZ)
    except ValueError:
        return None
    return _fmt(dt)


def sunrise_time(lat: float, lon: float, d: date) -> str | None:
    """指定日期的日出时刻（极昼/极夜无日出 → None）。"""
    try:
        dt = _astral_sunrise(Observer(lat, lon), date=d, tzinfo=TZ)
    except ValueError:
        return None
    return _fmt(dt)


def astro_dawn_time(lat: float, lon: float, now: datetime) -> str | None:
    """下一次天文晨光（太阳到 -18° 的上升时刻）；今天的已过则取明天的。"""
    for d in (now.date(), now.date() + timedelta(days=1)):
        try:
            dt = _astral_dawn(
                Observer(lat, lon), date=d, depression=18.0, tzinfo=TZ,
            )
        except ValueError:
            continue
        if dt > now:
            return _fmt(dt)
    return None


def astro_dusk_time(lat: float, lon: float, now: datetime) -> str | None:
    """下一次天文暮光结束（太阳降到 -18° 之下）——今晚真正的暗夜开始时刻。"""
    for d in (now.date(), now.date() + timedelta(days=1)):
        try:
            dt = _astral_dusk(
                Observer(lat, lon), date=d, depression=18.0, tzinfo=TZ,
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


def _coord_series(
    alt_fn, lat: float, lon: float, now: datetime,
    hours: float, step_min: int,
):
    """生成 (times, alts_deg) 序列；alt_fn(t, loc) → 角度（Quantity 或 scalar）。"""
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    step = timedelta(minutes=step_min)
    n = int(hours * 60 // step_min) + 1
    times = [now + i * step for i in range(n)]
    t = Time(times)
    alts = alt_fn(t, loc)
    return times, [float(a) for a in alts]


def _moon_alt(t, loc):
    return get_body("moon", t, loc).transform_to(
        AltAz(obstime=t, location=loc)).alt.deg


def _fixed_alt(coord: SkyCoord):
    def _f(t, loc):
        return coord.transform_to(AltAz(obstime=t, location=loc)).alt.deg
    return _f


def moon_events(lat: float, lon: float, now: datetime) -> dict[str, str | None]:
    """未来 36h 内的月出 / 月落（共享一条高度角序列，只扫一次）。"""
    times, alts = _coord_series(_moon_alt, lat, lon, now, 36.0, 20)
    return {
        "moonrise": _fmt(_find_rising_crossing(times, alts)),
        "moonset": _fmt(_find_setting_crossing(times, alts)),
    }


def galactic_events(lat: float, lon: float, now: datetime) -> dict[str, str | None]:
    """未来 36h 内的银心（人马座 A*）升起 / 落下（共享一条高度角序列）。"""
    times, alts = _coord_series(
        _fixed_alt(_GALACTIC_CORE), lat, lon, now, 36.0, 15,
    )
    return {
        "galactic_rise": _fmt(_find_rising_crossing(times, alts)),
        "galactic_set": _fmt(_find_setting_crossing(times, alts)),
    }


# ---- 单项薄包装（保持旧接口；批量场景请用上面两个 events 函数以免重复扫描） ----


def moonrise_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 36h 内下一次月出。"""
    return moon_events(lat, lon, now)["moonrise"]


def moonset_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 36h 内下一次月落（月亮高度下穿地平）。"""
    return moon_events(lat, lon, now)["moonset"]


def galactic_rise_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 36h 内银心升起时刻；纬度 >61°N 永不升起 → None。"""
    return galactic_events(lat, lon, now)["galactic_rise"]


def galactic_set_time(lat: float, lon: float, now: datetime) -> str | None:
    """未来 36h 内银心落下时刻（淡季时可能落在次日凌晨）。"""
    return galactic_events(lat, lon, now)["galactic_set"]
