"""validate_atlas._meta.json 校验单测。"""
import pytest

from scripts.validate_atlas import validate_meta


def test_meta_required_fields():
    """_meta.json 必含 key/label/star_count/coordinate_system。"""
    # 合法
    valid = {
        "key": "test", "label": "测试", "star_count": 5,
        "coordinate_system": "equatorial",
    }
    errors, warnings = validate_meta(valid, "test", glob_count=5)
    assert errors == []

    # 缺 label
    invalid = {
        "key": "test", "star_count": 5, "coordinate_system": "equatorial",
    }
    errors, warnings = validate_meta(invalid, "test", glob_count=5)
    assert any("label" in e for e in errors)

    # key 与目录名不一致
    mismatch = {
        "key": "other", "label": "测试", "star_count": 5,
        "coordinate_system": "equatorial",
    }
    errors, warnings = validate_meta(mismatch, "test", glob_count=5)
    assert any("key" in e.lower() for e in errors)

    # coordinate_system 不在白名单
    bad_cs = {
        "key": "test", "label": "测试", "star_count": 5,
        "coordinate_system": "galactic",
    }
    errors, warnings = validate_meta(bad_cs, "test", glob_count=5)
    assert any("coordinate_system" in e for e in errors)


def test_meta_star_count_matches_glob():
    """star_count 校验：以 glob 为准。"""
    meta = {
        "key": "test", "label": "测试", "star_count": 99,
        "coordinate_system": "equatorial",
    }
    # star_count 99 vs glob 5：应该是 warning（不报错），因 glob 自动校正
    errors, warnings = validate_meta(meta, "test", glob_count=5)
    assert errors == []
    assert any("star_count" in w for w in warnings)
