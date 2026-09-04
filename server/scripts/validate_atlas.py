"""Atlas 数据校验脚本。

第一阶段末尾手动跑一次（5 文件完整）；第二期起集成 CI。
硬性校验：abbr 一致、center/stars 必填字段、lines 合法、stories 6 维 title 必填（占位可）
软性校验：center 到 stars 平均角距 < 15°（warning 不报错）

中国星官（coordinate_system == "mansion"）硬规则（spec v5 §3.3）：
- stars 必须含 name_zh
- 白名单内 entry（28 宿 / 3 垣）要求 mansion 与 asterism_id 至少一个非 null；
  扩展星官允许两字段 null
- abbr 满足 ^[a-z0-9_]+$
- lines 无悬空端点（null 或不在 stars 中）
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "traditions"
HARD_ERRORS = 0
SOFT_WARNINGS = 0
NARRATIVES = ("epic", "chat", "brief")
VIEWS = ("myth", "science")

# 白名单：28 宿 + 3 垣。28 宿分化为 wei_xiu_1/2/3, bi_xiu_1/2（任务 5 已消歧）。
MANSION_ABBR_WHITELIST: set[str] = {
    "jiao_xiu", "kang_xiu", "di_xiu", "fang_xiu", "xin_xiu", "wei_xiu_1",
    "ji_xiu",
    "dou_xiu", "niu_xiu", "nu_xiu", "xu_xiu", "wei_xiu_2",
    "shi_xiu", "bi_xiu_1", "bi_xiu_2",
    "kui_xiu", "lou_xiu", "mao_xiu", "wei_xiu_3", "zi_xiu", "shen_xiu",
    "jing_xiu", "gui_xiu", "liu_xiu", "xing_xiu", "zhang_xiu", "yi_xiu",
    "zhen_xiu",
    "zi_wei_yuan", "tai_wei_yuan", "tian_shi_yuan",
}

# 3 垣（紫微/太微/天市）：大量星官成员为无名星（HIP 号占位），
# name_zh 可空。28 宿与扩展星官的 star 必须有 name_zh。
ENCLOSURE_ABBR: set[str] = {"zi_wei_yuan", "tai_wei_yuan", "tian_shi_yuan"}


def _angular_sep_deg(ra1, dec1, ra2, dec2) -> float:
    import math
    dra = (ra1 - ra2 + 180) % 360 - 180
    dra *= math.cos(math.radians((dec1 + dec2) / 2))
    ddec = dec1 - dec2
    return math.sqrt(dra * dra + ddec * ddec)


def check_file(json_path: Path, coord: str = "equatorial") -> None:
    global HARD_ERRORS, SOFT_WARNINGS
    abbr_stem = json_path.stem
    try:
        entry = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"HARD {json_path}: JSON parse failed: {e}")
        HARD_ERRORS += 1
        return

    if entry.get("abbr") != abbr_stem:
        print(f"HARD {json_path}: abbr={entry.get('abbr')!r} != filename={abbr_stem!r}")
        HARD_ERRORS += 1

    center = entry.get("center")
    if not center or "ra" not in center or "dec" not in center:
        print(f"HARD {json_path}: missing center.{{ra,dec}}")
        HARD_ERRORS += 1

    stars = entry.get("stars", {})
    star_keys = set(stars.keys())
    for sk, s in stars.items():
        for f in ("ra", "dec", "magnitude", "label"):
            if f not in s:
                print(f"HARD {json_path}: stars.{sk} missing {f}")
                HARD_ERRORS += 1
        if "label" in s and not isinstance(s["label"], bool):
            print(f"HARD {json_path}: stars.{sk}.label not bool")
            HARD_ERRORS += 1

    for line in entry.get("lines", []):
        if len(line) != 2 or line[0] not in star_keys or line[1] not in star_keys:
            print(f"HARD {json_path}: line {line!r} uses unknown star key")
            HARD_ERRORS += 1

    stories = entry.get("stories", {})
    for view in VIEWS:
        if view not in stories:
            print(f"HARD {json_path}: stories missing view={view}")
            HARD_ERRORS += 1
            continue
        for narr in NARRATIVES:
            v = stories[view].get(narr, {})
            if "title" not in v:
                print(f"HARD {json_path}: stories.{view}.{narr} missing title")
                HARD_ERRORS += 1

    # ── spec v5 §3.3 中国星官硬规则 ───────────────────────────────
    if coord == "mansion":
        # 3 垣（紫微/太微/天市）含大量无名星（HIP 占位），豁免 name_zh 检查；
        # 28 宿与扩展星官必须 name_zh 非空。
        if abbr_stem not in ENCLOSURE_ABBR:
            for sk, s in stars.items():
                if not s.get("name_zh"):
                    print(f"HARD {json_path}: stars.{sk} 缺 name_zh")
                    HARD_ERRORS += 1
        # 白名单内 entry（28 宿 / 3 垣）要求 mansion 与 asterism_id 至少一个非 null；
        # 扩展星官允许两字段 null（spec v5 §3.3 扩展位）。
        if abbr_stem in MANSION_ABBR_WHITELIST:
            if entry.get("mansion") is None and entry.get("asterism_id") is None:
                print(f"HARD {json_path}: mansion 与 asterism_id 均为 null")
                HARD_ERRORS += 1
    if not re.fullmatch(r"[a-z0-9_]+", entry.get("abbr", "")):
        print(f"HARD {json_path}: abbr={entry.get('abbr')!r} 非 ^[a-z0-9_]+$")
        HARD_ERRORS += 1
    for line in entry.get("lines", []):
        for sid in line:
            if sid is None:
                print(f"HARD {json_path}: line {line!r} 含 null 端点")
                HARD_ERRORS += 1
            elif sid not in star_keys:
                print(f"HARD {json_path}: line 端点 {sid!r} 不在 stars 中")
                HARD_ERRORS += 1

    if center and stars:
        avg_sep = sum(
            _angular_sep_deg(center["ra"], center["dec"], s["ra"], s["dec"])
            for s in stars.values()
        ) / len(stars)
        if avg_sep > 15.0:
            print(f"WARN {json_path}: center to stars avg sep {avg_sep:.1f}° > 15°")
            SOFT_WARNINGS += 1

    print(f"OK {json_path.name}")


def validate_meta(meta: dict, dir_name: str, glob_count: int) -> tuple[list, list]:
    """校验 _meta.json 内容。

    Returns:
        (errors, warnings) — errors 阻断，warnings 警告
    """
    errors = []
    warnings = []

    # 必填字段
    for field in ("key", "label", "star_count", "coordinate_system"):
        if field not in meta:
            errors.append(f"_meta.json 缺必填字段: {field}")

    # key 与目录名一致（小写）
    if meta.get("key") != dir_name:
        errors.append(
            f"_meta.json key='{meta.get('key')}' 与目录名 '{dir_name}' 不一致（小写）"
        )

    # coordinate_system 白名单
    valid_cs = {"equatorial", "mansion"}
    if meta.get("coordinate_system") not in valid_cs:
        errors.append(
            f"_meta.json coordinate_system='{meta.get('coordinate_system')}' "
            f"不在白名单 {valid_cs}"
        )

    # star_count 匹配 glob
    if meta.get("star_count") != glob_count:
        warnings.append(
            f"_meta.json star_count={meta.get('star_count')} "
            f"与实际 glob 数量 {glob_count} 不一致（运行时自动校正）"
        )

    return errors, warnings


def _check_meta(meta_path: Path) -> None:
    """校验单文件 _meta.json。"""
    global HARD_ERRORS, SOFT_WARNINGS
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"HARD {meta_path}: JSON parse failed: {e}")
        HARD_ERRORS += 1
        return

    dir_name = meta_path.parent.name
    # _meta.json 自身不计入 star_count
    glob_count = sum(1 for _ in meta_path.parent.glob("*.json")) - 1
    errs, warns = validate_meta(meta, dir_name, glob_count)
    for e in errs:
        print(f"HARD {meta_path}: {e}")
        HARD_ERRORS += 1
    for w in warns:
        print(f"WARN {meta_path}: {w}")
        SOFT_WARNINGS += 1


def main() -> int:
    for trad_dir in sorted(ROOT.iterdir()):
        if not trad_dir.is_dir():
            continue
        meta_path = trad_dir / "_meta.json"
        coord = "equatorial"  # default
        if meta_path.is_file():
            _check_meta(meta_path)
            try:
                coord = json.loads(meta_path.read_text(encoding="utf-8")).get(
                    "coordinate_system", "equatorial"
                )
            except json.JSONDecodeError:
                pass
        for json_file in sorted(trad_dir.glob("*.json")):
            if json_file.name == "_meta.json":
                continue
            check_file(json_file, coord=coord)
    print(f"\nSummary: {HARD_ERRORS} hard errors, {SOFT_WARNINGS} soft warnings")
    return 1 if HARD_ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
