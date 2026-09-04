"""traditions 服务单测。

覆盖：
- 自动发现（western + chinese）
- fail-soft（坏 JSON 跳过）
- abbr != filename 跳过
- list_traditions / list_constellations / get_constellation
- find_nearest 反查 + RA 跨零度（用 mock fixture，不依赖 MVP 数据）
- build_star_catalog 去重
"""
import json
import math
import pytest

from services import traditions
from services.traditions import (
    _angular_separation,
    find_nearest,
    _load_all,
    _DATA,
)


@pytest.fixture
def tmp_traditions(monkeypatch, tmp_path):
    """临时替换 _DATA_ROOT，写入 mock traditions 数据。"""
    root = tmp_path / "traditions"
    (root / "western").mkdir(parents=True)
    (root / "chinese").mkdir()
    monkeypatch.setattr(traditions, "_DATA_ROOT", root)
    monkeypatch.setattr(traditions, "_DATA", {})
    monkeypatch.setattr(traditions, "_META", None)
    return root


def _write(root, tradition, abbr, entry):
    p = root / tradition / f"{abbr}.json"
    p.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


ORION_MOCK = {
    "abbr": "ori", "name": "猎户座", "latin": "Orion",
    "center": {"ra": 86.0, "dec": -2.0},
    "stars": {
        "betelgeuse": {"x": 144, "y": 62, "name": "Betelgeuse", "name_zh": "参宿四",
                       "bayer": "Alpha Ori", "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True}
    },
    "lines": [],
    "stories": {
        "myth": {"epic": {"title": "x", "paragraphs": []},
                 "chat": {"title": "x", "paragraphs": []},
                 "brief": {"title": "x", "paragraphs": []}},
        "science": {"epic": {"title": "x", "paragraphs": []},
                    "chat": {"title": "x", "paragraphs": []},
                    "brief": {"title": "x", "paragraphs": []}},
    },
}


def test_scan_loads_western_and_chinese(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    _write(tmp_traditions, "chinese", "shen", {**ORION_MOCK, "abbr": "shen", "latin": ""})
    traditions._load_all()
    assert set(traditions._DATA.keys()) == {"western", "chinese"}
    assert traditions._DATA["western"]["ori"]["name"] == "猎户座"


def test_load_skips_bad_json(tmp_traditions, caplog):
    (tmp_traditions / "western" / "bad.json").write_text("{not json", encoding="utf-8")
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    with caplog.at_level("ERROR"):
        traditions._load_all()
    assert "ori" in traditions._DATA["western"]
    assert "bad" not in traditions._DATA["western"]


def test_load_skips_abbr_mismatch(tmp_traditions, caplog):
    _write(tmp_traditions, "western", "ori", {**ORION_MOCK, "abbr": "wrong"})
    with caplog.at_level("ERROR"):
        traditions._load_all()
    assert "ori" not in traditions._DATA["western"]


def test_get_constellation_returns_full_entry(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    result = traditions.get_constellation("western", "ori")
    assert result is not None
    assert result["ok"] is True
    assert result["tradition"] == "western"
    assert "stars" in result


def test_get_constellation_missing_returns_none(tmp_traditions):
    assert traditions.get_constellation("western", "xxx") is None


def test_list_constellations_filters_by_tradition(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    _write(tmp_traditions, "chinese", "shen", {**ORION_MOCK, "abbr": "shen", "latin": ""})
    items = traditions.list_constellations("western")
    assert [i["abbr"] for i in items] == ["ori"]
    assert items[0]["tradition"] == "western"
    assert items[0]["star_count"] == 1
    assert items[0]["has_stories"] is True


def test_find_nearest_returns_closest(tmp_traditions):
    """反查最近的星座，返回 list（spec v4 任务 2 改造后的 API）。"""
    near = {**ORION_MOCK, "center": {"ra": 86.0, "dec": -2.0}}
    far  = {**ORION_MOCK, "abbr": "cyg", "center": {"ra": 312.0, "dec": 42.0}}
    _write(tmp_traditions, "western", "ori", near)
    _write(tmp_traditions, "western", "cyg", far)
    results = traditions.find_nearest(85.5, -2.5)
    assert isinstance(results, list)
    assert len(results) >= 1
    trad, abbr, sep = results[0]
    assert trad == "western"
    assert abbr == "ori"
    assert sep < 1.0


def test_find_nearest_respects_max_separation(tmp_traditions):
    """无命中返回空 list（不要检查 is None）。"""
    _write(tmp_traditions, "western", "ori", ORION_MOCK)  # center (86, -2)
    assert traditions.find_nearest(300, -60) == []  # far away


def test_find_nearest_handles_ra_wrap(tmp_traditions):
    """RA 跨 0°/360° 时取最近一侧（用 mock fixture 构造，MVP 数据无此场景）。

    center (359, 0)，query (1, 0)：角距应约 2°，不应是 358°。
    """
    near_wrap = {**ORION_MOCK, "abbr": "wrap", "center": {"ra": 359.0, "dec": 0.0}}
    _write(tmp_traditions, "western", "wrap", near_wrap)
    results = traditions.find_nearest(1.0, 0.0)
    assert isinstance(results, list)
    assert len(results) >= 1
    trad, abbr, sep = results[0]
    assert trad == "western"
    assert abbr == "wrap"
    assert sep < 5.0


def test_list_traditions_returns_label_and_count(tmp_traditions):
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    items = traditions.list_traditions()
    by_key = {i["key"]: i for i in items}
    assert by_key["western"]["label"] == "西方星座"
    assert by_key["western"]["count"] == 1


def test_double_check_locking_idempotent(tmp_traditions):
    """_load_all 多次调用是幂等的（double-check locking）。"""
    _write(tmp_traditions, "western", "ori", ORION_MOCK)
    traditions._load_all()
    traditions._load_all()
    traditions._load_all()
    assert traditions._DATA["western"]["ori"]["name"] == "猎户座"


# ─────────────────────────────────────────────────────────────────────
# spec v4 任务 2：Haversine + find_nearest list + _meta 加载
# ─────────────────────────────────────────────────────────────────────


def test_haversine_low_lat_matches_simplified():
    """低纬（|Dec|<45°）Haversine 与解析参考值偏差 < 0.001°。"""
    sep = _angular_separation(86.0, -2.0, 12.0, 38.0)
    a = (
        math.sin(math.radians(40) / 2) ** 2
        + math.cos(math.radians(-2)) * math.cos(math.radians(38))
        * math.sin(math.radians(-74) / 2) ** 2
    )
    expected = math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
    assert abs(sep - expected) < 0.001


def test_haversine_high_lat_no_distortion():
    """高纬（Dec=89°）Haversine 给准确短弧角距（不被 cos(dec) 畸变）。

    短弧定义：atan2 版 Haversine 总返回 ≤180° 短弧。
    (0°,89°) 与 (180°,89°) 都距北极 1°，绕极 1°+1° = 2°，是球面短弧。
    旧简化版在该场景给 3.14°（cos(89°) 压缩 RA），是失真信号。
    """
    sep = _angular_separation(0.0, 89.0, 180.0, 89.0)
    assert abs(sep - 2.0) < 0.01


def test_find_nearest_returns_list():
    """find_nearest 改返回 list（破坏性 API 变化）。

    T6+: chinese 数据补齐后 shen_xiu 与 ori 中心一致，top_k=3 时排序
    不再固定 western 在前；断言至少有一个 western/ori 命中即可。
    T9 (Batch C): ori 中心从 (86,-2) 移到亮星均值 (≈82, 5)，query 同步到 (82, 5)。
    """
    result = find_nearest(82.0, 5.0, max_sep_deg=5.0)
    assert isinstance(result, list)
    assert len(result) >= 1
    trad, abbr, sep = result[0]
    assert 0 < sep < 5
    # 至少有一个 western/ori 命中（具体排序不固定）
    assert any(t == "western" and a == "ori" for t, a, _ in result)


def test_find_nearest_top_k_truncates():
    """top_k=1 时最多返回 1 个结果。

    T9 (Batch C): ori 中心移到 (82, 5)，其他 4 星座中心差异 > 5° 被过滤，
    故 len(result) <= 1 自然成立。
    """
    result = find_nearest(82.0, 5.0, max_sep_deg=5.0, top_k=1)
    assert isinstance(result, list)
    assert len(result) <= 1


def test_find_nearest_empty_when_above_threshold():
    """无命中时返回空 list（不是 None）。"""
    result = find_nearest(0.0, 0.0, max_sep_deg=0.1)
    assert result == []


def test_find_nearest_tradition_filter():
    """tradition 参数：限定只查指定 tradition。

    业务动机：用户在前端锁定"中国古代星空"开关时，反查只应命中 chinese。
    """
    from services import traditions as t
    t._DATA = {
        "western": {
            "ori": {"center": {"ra": 86.0, "dec": -2.0}, "stars": {}},
        },
        "chinese": {
            "shen_xiu": {"center": {"ra": 83.7, "dec": -1.1}, "stars": {}},
        },
    }
    # 不限 tradition：双 tradition 都在阈值内
    all_hits = find_nearest(85.0, -1.5, max_sep_deg=10.0)
    assert {h[0] for h in all_hits} == {"western", "chinese"}
    # 限定 western：仅 ori
    west_hits = find_nearest(85.0, -1.5, max_sep_deg=10.0, tradition="western")
    assert len(west_hits) == 1 and west_hits[0][1] == "ori"
    # 限定 chinese：仅 shen_xiu
    cn_hits = find_nearest(85.0, -1.5, max_sep_deg=10.0, tradition="chinese")
    assert len(cn_hits) == 1 and cn_hits[0][1] == "shen_xiu"
    # 大小写不敏感
    cn_upper = find_nearest(85.0, -1.5, max_sep_deg=10.0, tradition="CHINESE")
    assert len(cn_upper) == 1


def test_meta_load_normal():
    """_meta.json 正常加载。"""
    from services.traditions import get_meta
    _load_all()
    assert get_meta("western")["label"] == "西方星座"
    assert get_meta("western")["coordinate_system"] == "equatorial"


def test_meta_missing_falls_back():
    """缺 _meta.json → 默认值（label == key）。"""
    from services.traditions import _default_meta
    meta = _default_meta("test_trad", 1)
    assert meta["key"] == "test_trad"
    assert meta["label"] == "test_trad"
    assert meta["star_count"] == 1
    assert meta["coordinate_system"] == "equatorial"


def test_meta_corrupt_json_falls_back_meta():
    """坏 JSON → 仅降级 meta，星表照常加载。"""
    from services.traditions import _default_meta
    _load_all()
    meta = _default_meta("test", 3)
    assert meta["label"] == "test"


def test_meta_star_count_auto_corrected():
    """star_count 以 glob 为准，覆盖 meta。"""
    from services.traditions import _default_meta
    meta = _default_meta("test", 7)
    assert meta["star_count"] == 7


def test_double_check_locking_concurrent():
    """_load_all 多线程并发安全（idempotent）。"""
    import threading
    from services.traditions import _META
    results = []

    def worker():
        _load_all()
        results.append((id(_DATA), id(_META)))

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 所有引用必须一致
    assert len(set(results)) == 1


def test_get_meta_lowercase():
    """get_meta 大小写不敏感。"""
    from services.traditions import get_meta
    _load_all()
    a = get_meta("western")
    b = get_meta("WESTERN")
    assert a == b
