"""西方 88 星座 viewBox 统一性 + center 几何中心 回归测试。

守护 `build_western_stars.py` 的修复：
- viewBox 统一 700×700（与 chinese 一致）
- center 用亮星（label=true, mag<4.5）3D 向量均值
- x/y 从 ra/dec 用 Azimuthal Stereographic 重算

注：T9（Batch C）star keys 改为 HIP_xxxxx（之前是 slug）。Belt / Big Dipper
断言改用 bayer 查找而不是中文名。

Batch D：name 现在是中文（简化后的 CSV.zh），新增 name_en 字段存英文。
"""
import json
import math
from pathlib import Path

from scripts.atlas_projection import compute_center  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "traditions" / "western"


def _load_all() -> list[dict]:
    out = []
    for fp in DATA.glob("*.json"):
        if fp.name == "_meta.json":
            continue
        e = json.loads(fp.read_text(encoding="utf-8"))
        out.append(e)
    return out


def test_all_western_have_unified_viewbox():
    """全部 88 星座 viewBox 统一 700×700（与 chinese atlas 视场对齐）。"""
    entries = _load_all()
    assert len(entries) == 88, f"应有 88 星座，实际 {len(entries)}"
    for e in entries:
        v = e.get("viewBox", {})
        assert v.get("width") == 700, (
            f"{e['name']} viewBox.width={v.get('width')} ≠ 700"
        )
        assert v.get("height") == 700, (
            f"{e['name']} viewBox.height={v.get('height')} ≠ 700"
        )


def test_all_western_center_uses_bright_geometric_mean():
    """center 必须是亮星（mag<4.5）3D 向量均值。

    T9 (Batch C)：build script 改用亮星均值——全 line 端点含暗星（4~5 mag 周边），
    算术平均会偏离视觉中心（如 Ori 24 端点 → (81.5, 7.0)；亮星 19 → (81.9, 5.2)）。

    注：用 magnitude 过滤，不用 label——Batch E 把 label 改成全标，label 不再是亮星
    判据（displayNameFor 会自然回退到 bayer）。
    """
    for e in _load_all():
        stars = list(e.get("stars", {}).values())
        if not stars:
            continue
        bright = [s for s in stars if (s.get("magnitude") or 99) < 4.5]
        # 退化：若 < 3 颗亮星（如极端暗星座），退到全成员
        center_input = bright if len(bright) >= 3 else stars
        if not center_input:
            continue
        expected_ra, expected_dec = compute_center(center_input)
        assert abs(e["center"]["ra"] - expected_ra) < 0.5, (
            f"{e['name']} center.ra={e['center']['ra']} 与亮星均值"
            f" {expected_ra:.2f} 偏差过大"
        )
        assert abs(e["center"]["dec"] - expected_dec) < 0.5, (
            f"{e['name']} center.dec={e['center']['dec']} 与亮星均值"
            f" {expected_dec:.2f} 偏差过大"
        )


def test_orion_belt_is_nearly_horizontal():
    """猎户腰带 3 颗（Alnitak ζ / Alnilam ε / Mintaka δ）Dec 差 < 2°。

    T9 (Batch C)：star keys 改 HIP_xxxxx；bayer 直接用希腊字母（之前是 Latin "Zeta Ori"）。
    投影后腰带 3 颗 y 坐标差应当 < 0.1 × viewBox.height。
    """
    e = next(e for e in _load_all() if e["abbr"] == "ori")
    belt_bayers = {"ζ", "ε", "δ"}
    belt = [s for s in e["stars"].values() if s.get("bayer") in belt_bayers]
    assert len(belt) == 3, f"腰带 3 颗缺失：{[s['bayer'] for s in e['stars'].values()]}"
    ys = [s["y"] for s in belt]
    spread = max(ys) - min(ys)
    # 真实 Dec 差 1.6°，总高 ~30° 视场 → 期望 spread / 700 < 0.06
    assert spread / 700 < 0.1, (
        f"猎户腰带 spread={spread:.1f}px / 700 太大，"
        f"Stereographic 修正可能没生效"
    )


def test_uma_seven_stars_not_collapsed():
    """大熊 7 颗主星 (Big Dipper) 的 x/y 应当合理分散，而非塌缩成 1 点。

    任意 2 颗的像素距离应当 >= viewBox.width 的 5%（即 35px）。
    T9 (Batch C)：HIPs 不变，bayer 改用希腊字母。
    """
    e = next(e for e in _load_all() if e["abbr"] == "uma")
    s = e["stars"]
    bd_hips = {"54061", "53910", "58001", "59774", "62956", "65378", "67301"}
    keys = [k for k in s if k.replace("HIP_", "") in bd_hips]
    assert len(keys) == 7, f"大熊 7 颗主星缺失: {keys}"
    pts = [(s[k]["x"], s[k]["y"]) for k in keys]
    min_d = min(
        ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5
        for i, a in enumerate(pts) for b in pts[i+1:]
    )
    # 7 颗分布至少要有 35px（=5% viewBox 700）的最小间距
    assert min_d >= 35, f"大熊 7 颗最小距离 {min_d:.1f} < 35px，可能塌缩"


def test_metadata_preserved():
    """回归：stories / season / glyph / abbr / latin / name / name_zh 在重生后必须保持。

    T9 (Batch C) 字段策略：
    - name 改用 CSV.en（"Orion"）替代原中文
    - name_zh 改用 CSV.zh（"獵戶座"）
    - season 旧值中文映射到英文
    - star keys 改 HIP_xxxxx（之前 betelgeuse 等 slug）
    - star.bayer 改用希腊字母单字符（之前 "Alpha Ori"）
    """
    e = next(e for e in _load_all() if e["abbr"] == "ori")
    # 字段必须在
    for key in ("abbr", "name", "latin", "glyph", "season", "caption", "stories"):
        assert key in e, f"ori.json 缺 {key}"
    # stories 完整
    assert "myth" in e["stories"] and "science" in e["stories"]
    # Betelgeuse 仍存在（HIP_27989）；字段名按新 schema
    betelgeuse = e["stars"]["HIP_27989"]
    for key in ("bayer", "name", "name_zh", "name_en", "magnitude", "label", "hip"):
        assert key in betelgeuse, f"Betelgeuse 缺 {key}"
    assert betelgeuse["bayer"] == "α"
    # Batch D: name 现为中文（参宿四），name_en 保留英文（Betelgeuse）
    assert betelgeuse["name"] == "参宿四"
    assert betelgeuse["name_en"] == "Betelgeuse"
    assert betelgeuse["name_zh"] == "参宿四"
    assert betelgeuse["hip"] == "27989"
    assert betelgeuse["label"] is True
