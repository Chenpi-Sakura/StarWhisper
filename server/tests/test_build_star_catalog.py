"""build_star_catalog 单测。"""
import json
import pytest

from services import traditions


@pytest.fixture
def tmp_traditions(monkeypatch, tmp_path):
    root = tmp_path / "traditions"
    (root / "western").mkdir(parents=True)
    (root / "chinese").mkdir()
    monkeypatch.setattr(traditions, "_DATA_ROOT", root)
    monkeypatch.setattr(traditions, "_DATA", {})
    # 同时清 _META 避免污染后续测试（test_traditions 的同名 fixture 也清 _META）
    monkeypatch.setattr(traditions, "_META", None)
    return root


def _write(root, tradition, abbr, entry):
    (root / tradition / f"{abbr}.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8"
    )


def test_dedupes_stars_by_ra_dec(tmp_traditions):
    """参宿四在 western/ori 和 chinese/shen RA/Dec 相同，应只保留一次。"""
    star = {"x": 144, "y": 62, "name": "Betelgeuse", "name_zh": "参宿四",
            "bayer": "Alpha Ori", "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True}
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star},
    })
    _write(tmp_traditions, "chinese", "shen", {
        "abbr": "shen", "name": "参宿", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star},  # 同一组 RA/Dec
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    assert catalog[0]["name"] == "Betelgeuse"


def test_returns_all_required_fields(tmp_traditions):
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": {
            "x": 144, "y": 62, "bayer": "α Ori", "name": "Betelgeuse", "name_zh": "参宿四",
            "magnitude": 0.42, "ra": 88.79, "dec": 7.41, "label": True,
        }},
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    s = catalog[0]
    for field in ("bayer", "name", "name_zh", "magnitude", "ra", "dec", "constellation", "tradition"):
        assert field in s
    assert s["constellation"] == "ori"
    assert s["tradition"] == "western"


def test_catalog_dedup_by_hip(tmp_traditions):
    """同一 HIP 在不同 tradition/entry 只保留一条。"""
    star_w = {"x": 144, "y": 62, "hip": 27989, "ra": 88.79, "dec": 7.41,
              "magnitude": 0.42, "name": "Betelgeuse", "name_zh": "参宿四",
              "bayer": "α Ori", "label": True}
    star_c = {**star_w}  # 同一组坐标 + 同一 HIP
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star_w},
    })
    _write(tmp_traditions, "chinese", "shen_xiu", {
        "abbr": "shen_xiu", "name": "参宿", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star_c},
    })
    catalog = traditions.build_star_catalog()
    hip27989 = [c for c in catalog if c["hip"] == "27989"]
    assert len(hip27989) == 1
    assert hip27989[0]["hip"] == "27989"
    # M-2 修复：跨 entry name_zh 一致（spec §6 验收）
    assert hip27989[0]["name_zh"] == "参宿四"


def test_catalog_fallback_round3(tmp_traditions):
    """无 hip 时 fallback round(ra,3) 去重。"""
    _write(tmp_traditions, "western", "a", {
        "abbr": "a", "name": "A", "center": {"ra": 0, "dec": 0},
        "stars": {"x": {"ra": 10.0001, "dec": 5.0001, "magnitude": 1, "label": True}},
    })
    _write(tmp_traditions, "western", "b", {
        "abbr": "b", "name": "B", "center": {"ra": 0, "dec": 0},
        "stars": {"y": {"ra": 10.0001, "dec": 5.0001, "magnitude": 1, "label": True}},
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    # hip 字段应为空字符串
    assert catalog[0]["hip"] == ""


def test_catalog_collects_all_constellation_memberships(tmp_traditions):
    """★ 多归属修复（用户反馈：选人马座后人马座内部星点不亮）：

    同颗物理星在多个 tradition 出现时，HIP 去重只保留首个（chinese 按
    目录序先加载 → sgr 的 25 颗星全被 ji_xiu/dou_xiu 抢注）→ 前端 dim
    判断 s.constellation === activeAbbr 对 western chip 全部 miss。

    修复后 catalog 条目带 constellations=[所有归属 abbr]（跨 tradition
    聚合），constellation/tradition 保留首个归属向后兼容。"""
    star_w = {"x": 144, "y": 62, "hip": 27989, "ra": 88.79, "dec": 7.41,
              "magnitude": 0.42, "name": "Betelgeuse", "name_zh": "参宿四",
              "bayer": "α Ori", "label": True}
    star_c = {**star_w}  # 同一 HIP + 同一坐标
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star_w},
    })
    _write(tmp_traditions, "chinese", "shen_xiu", {
        "abbr": "shen_xiu", "name": "参宿", "center": {"ra": 86, "dec": -2},
        "stars": {"betelgeuse": star_c},
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    s = catalog[0]
    # 旧字段保留：首个归属（_load_all 按目录序 chinese < western 先加载）
    assert s["constellation"] == "shen_xiu"
    assert s["tradition"] == "chinese"
    # 新字段：跨 tradition 全部归属
    assert sorted(s["constellations"]) == ["ori", "shen_xiu"]


def test_catalog_single_membership_constellations_list(tmp_traditions):
    """无跨 tradition 重叠的星，constellations 也应是单元素列表。"""
    _write(tmp_traditions, "western", "ori", {
        "abbr": "ori", "name": "猎户座", "center": {"ra": 86, "dec": -2},
        "stars": {"mintaka": {
            "x": 200, "y": 70, "hip": 25336, "ra": 84.05, "dec": -0.30,
            "magnitude": 2.23, "name": "Mintaka", "name_zh": "参宿三",
            "bayer": "δ Ori", "label": True,
        }},
    })
    catalog = traditions.build_star_catalog()
    assert len(catalog) == 1
    assert catalog[0]["constellation"] == "ori"
    assert catalog[0]["constellations"] == ["ori"]
