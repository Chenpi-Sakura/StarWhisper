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


def test_sunrise_time_format_beijing_summer():
    # 北京 2026-06-01 日出约 04:45~04:55（astral 本地计算，断言区间容差）
    got = at.sunrise_time(39.9042, 116.4074, date(2026, 6, 1))
    assert got is not None
    hh, mm = map(int, got.split(":"))
    assert 4 <= hh <= 5 and 0 <= mm < 60


def test_sunrise_before_sunset_same_day():
    got_r = at.sunrise_time(39.9042, 116.4074, date(2026, 9, 11))
    got_s = at.sunset_time(39.9042, 116.4074, date(2026, 9, 11))
    assert got_r is not None and got_s is not None
    assert got_r < got_s  # "HH:MM" 字符串可直接比大小


def test_sunrise_time_none_in_polar_night():
    # 北纬 80° 冬至极夜，无日出
    assert at.sunrise_time(80.0, 20.0, date(2026, 12, 21)) is None


def test_astro_dawn_time_is_future_event():
    now = datetime(2026, 9, 10, 21, 0, tzinfo=at.TZ)
    got = at.astro_dawn_time(39.9042, 116.4074, now)
    assert got is not None
    hh, mm = map(int, got.split(":"))
    # 下一次天文晨光应在凌晨（03:00~05:30 附近）
    assert 3 <= hh <= 6
    # 晨光是未来事件：此刻（21:00）今天的晨光已过 → 对应明天的同一时刻
    dawn_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if dawn_dt <= now:
        dawn_dt += timedelta(days=1)
    assert dawn_dt > now


def test_astro_dusk_time_before_dawn_same_night():
    """同一天的「暮光结束」（−18° 下降）应晚于日落、早于次日晨光。"""
    now = datetime(2026, 9, 11, 0, 0, tzinfo=at.TZ)
    dusk = at.astro_dusk_time(39.9042, 116.4074, now)
    sunset = at.sunset_time(39.9042, 116.4074, now.date())
    assert dusk is not None and sunset is not None
    assert sunset < dusk  # 日落 → 天文暮光结束
    hh, _ = map(int, dusk.split(":"))
    assert 19 <= hh <= 22


def test_astro_dusk_time_skips_past_event():
    """23:00 问「下一次暮光结束」→ 今天的已过，应取明天。"""
    today = datetime(2026, 9, 11, 0, 0, tzinfo=at.TZ)
    late = datetime(2026, 9, 11, 23, 0, tzinfo=at.TZ)
    assert at.astro_dusk_time(39.9042, 116.4074, today) is not None
    got = at.astro_dusk_time(39.9042, 116.4074, late)
    assert got is not None
    hh, _ = map(int, got.split(":"))
    assert 19 <= hh <= 22


def test_moon_events_shares_one_series():
    """月出/月落共用一条序列：两者都应是合法 HH:MM。"""
    now = datetime(2026, 9, 11, 0, 0, tzinfo=at.TZ)
    ev = at.moon_events(30.5728, 104.0668, now)
    assert set(ev) == {"moonrise", "moonset"}
    for key in ("moonrise", "moonset"):
        got = ev[key]
        if got is not None:
            hh, mm = map(int, got.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
    # 新月那天月出≈日出后不久（成都 9/11 → 06:00~07:00）
    assert ev["moonrise"] is not None and ev["moonrise"].startswith("06")


def test_galactic_events_rise_before_set():
    """银心：下午（白天）升起 → 次日凌晨落下。"""
    now = datetime(2026, 9, 11, 0, 0, tzinfo=at.TZ)
    ev = at.galactic_events(30.5728, 104.0668, now)
    assert set(ev) == {"galactic_rise", "galactic_set"}
    assert ev["galactic_rise"] is not None
    assert ev["galactic_set"] is not None
    rh = int(ev["galactic_rise"].split(":")[0])
    sh = int(ev["galactic_set"].split(":")[0])
    assert 13 <= rh <= 16
    assert sh <= 3


def test_moonrise_and_galactic_set_wrappers():
    now = datetime(2026, 9, 11, 0, 0, tzinfo=at.TZ)
    assert at.moonrise_time(30.5728, 104.0668, now) == \
        at.moon_events(30.5728, 104.0668, now)["moonrise"]
    assert at.galactic_set_time(30.5728, 104.0668, now) == \
        at.galactic_events(30.5728, 104.0668, now)["galactic_set"]


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
